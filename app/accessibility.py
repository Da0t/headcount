"""Build rule-based transport and shelter recommendations for a resident.

The recommendations use the resident profile and, when available, their call
reading. They do not decide who receives help or trigger a real dispatch.
Every shelter below is fictional demo data for Tierrasanta, San Diego. None is
a real facility or real evacuation guidance.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

from app.models import Answer, Resident, Status

CAPABILITIES = ("wheelchair_accessible", "oxygen_power", "medical_staff", "pets_allowed", "large_animals")

_CAP_LABEL = {
    "wheelchair_accessible": "wheelchair accessible",
    "oxygen_power": "backup power for oxygen concentrators",
    "medical_staff": "medical staff on site",
    "pets_allowed": "pets allowed",
    "large_animals": "takes large animals",
}


@dataclass(frozen=True)
class Shelter:
    name: str
    address: str
    wheelchair_accessible: bool = False
    oxygen_power: bool = False
    medical_staff: bool = False
    pets_allowed: bool = False
    large_animals: bool = False
    lat: float = 0.0  # fictional map position in the demo zone
    lng: float = 0.0
    short: str = ""
    fictional: bool = True

    def caps(self) -> set[str]:
        return {c for c in CAPABILITIES if getattr(self, c)}


SHELTERS: list[Shelter] = [
    Shelter("Mesa Lantern Shelter (demo)", "fictional, Tierrasanta demo zone, City of San Diego",
            wheelchair_accessible=True, oxygen_power=True, lat=32.8262, lng=-117.1035, short="Mesa Lantern"),
    Shelter("Quail Ridge Community Shelter (demo)", "fictional, Tierrasanta demo zone, City of San Diego",
            wheelchair_accessible=True, pets_allowed=True, lat=32.8298, lng=-117.0905, short="Quail Ridge"),
    Shelter("Sage Hollow Medical Shelter (demo)", "fictional, Tierrasanta demo zone, City of San Diego",
            wheelchair_accessible=True, oxygen_power=True, medical_staff=True, lat=32.8178, lng=-117.1115,
            short="Sage Hollow"),
    Shelter("Canyon Lark Equestrian Grounds (demo)", "fictional, Tierrasanta demo zone, City of San Diego",
            pets_allowed=True, large_animals=True, lat=32.8335, lng=-117.0800, short="Canyon Lark"),
]

LARGE_ANIMALS = re.compile(r"\b(horse|horses|pony|ponies|cow|cows|cattle|goat|goats|sheep|pig|pigs|llama|llamas|"
                           r"alpaca|alpacas|donkey|donkeys|mule|mules|livestock|caballo|caballos|vaca|vacas)\b", re.I)
POWERED_EQUIPMENT = ("oxygen", "concentrator", "cpap", "bipap", "ventilator", "oxígeno", "oxigeno")


def shelters() -> list[dict]:
    return [asdict(s) for s in SHELTERS]


def _pets(r: Resident) -> tuple[list[str], list[str]]:
    """(small pets, large animals) from what they said."""
    pets = list(r.reading.pets) if r.reading else []
    large = [p for p in pets if LARGE_ANIMALS.search(p)]
    small = [p for p in pets if p not in large]
    return small, large


def pick_shelter(required: set[str]) -> tuple[Optional[Shelter], list[str]]:
    """Choose the demo shelter covering the most required capabilities.

    Ties prefer the shelter with fewer capabilities beyond those required; the
    returned reasons list capabilities met and unmet. This is a recommendation,
    not a reservation or dispatch.
    """
    if not SHELTERS:
        return None, []
    best = min(SHELTERS, key=lambda s: (-len(required & s.caps()), len(s.caps() - required), SHELTERS.index(s)))
    met = sorted(required & best.caps(), key=CAPABILITIES.index)
    missing = sorted(required - best.caps(), key=CAPABILITIES.index)
    why = [_CAP_LABEL[c] for c in met]
    why += [f"no demo shelter also has: {_CAP_LABEL[c]}" for c in missing]
    if not required:
        why = ["general shelter, no special needs known"]
    return best, why


def assist(r: Resident) -> dict:
    """Return a rule-based assistance plan for one resident.

    The result includes transport, shelter, reasons, responder needs, and
    shelter coordinates. It describes what kind of help may fit, not whether
    the resident receives help or whether anyone is dispatched.
    """
    reading = r.reading
    answer = reading.answer if reading else None
    equipment = [e.lower() for e in (reading.medical_equipment if reading else [])]
    small_pets, large_animals = _pets(r)

    medical = answer == Answer.NEEDS_MEDICAL or r.status == Status.NEEDS_MEDICAL
    wheelchair = r.bedridden or r.mobility or bool(reading and reading.mobility_help)
    oxygen = r.oxygen or any(any(k in e for k in POWERED_EQUIPMENT) for e in equipment)

    needs: list[str] = []
    required: set[str] = set()
    if medical:
        required |= {"medical_staff"}
        needs.append("medical help: ambulance crew")
    if wheelchair:
        required.add("wheelchair_accessible")
        needs.append("bedridden: needs a stretcher or lift" if r.bedridden else "wheelchair or walker: accessible vehicle")
    if oxygen:
        required.add("oxygen_power")
        if r.oxygen or any("ox" in e for e in equipment):
            needs.append("oxygen: bring portable tanks, shelter needs backup power")
    for e in equipment:
        if "ox" in e or e in ("wheelchair", "walker"):
            continue  # already covered above
        powered = any(k in e for k in POWERED_EQUIPMENT)
        needs.append(f"equipment: {e}" + (" (needs power)" if powered else ""))
    if small_pets:
        required.add("pets_allowed")
        needs.append("pets: " + ", ".join(small_pets))
    if large_animals:
        required.add("large_animals")
        needs.append("large animals: " + ", ".join(large_animals) + " (large-animal trailer)")
    if reading and reading.people_with_them:
        needs.append(f"{reading.people_with_them} more person(s) with them")
    if r.hearing:
        needs.append("hard of hearing: use text or face-to-face, not a loudspeaker")

    # transport: the most capable vehicle the situation calls for
    if answer in (Answer.OUT, Answer.STAYING) or r.status in (Status.OUT, Status.STAYING):
        transport = None
    elif medical:
        transport = "ambulance"
    elif wheelchair:
        transport = "wheelchair van"
    elif large_animals:
        transport = "large-animal trailer"
    elif answer == Answer.NEEDS_RIDE or r.status in (Status.NEEDS_RIDE, Status.WELFARE_CHECK):
        transport = "standard car"
    else:
        transport = None  # not known yet

    if r.status == Status.STAYING or answer == Answer.STAYING:
        needs.insert(0, "staying: plan ready in case they change their mind")
    if transport and large_animals and transport != "large-animal trailer":
        needs.append("send a large-animal trailer separately")

    if r.status == Status.OUT or answer == Answer.OUT:
        where = reading.where_they_are if reading else ""
        return {"transport": None, "shelter": None,
                "shelter_why": [f"already out: {where}" if where else "already out"], "needs": needs,
                "shelter_lat": None, "shelter_lng": None}

    shelter, why = pick_shelter(required)
    return {"transport": transport, "shelter": shelter.name if shelter else None, "shelter_why": why, "needs": needs,
            "shelter_lat": shelter.lat if shelter else None, "shelter_lng": shelter.lng if shelter else None}
