"""Who goes first. Plain arithmetic, no AI: status weight x vulnerability multiplier."""
from __future__ import annotations

from app.models import Resident, Status

WEIGHT = {
    Status.WELFARE_CHECK: 100,
    Status.NEEDS_MEDICAL: 95,
    Status.NEEDS_RIDE: 75,
    Status.NEEDS_CALLBACK: 65,
    Status.STAYING: 55,
    Status.CALLING: 40,
    Status.IN_CALL: 40,
    Status.RETRY_WAIT: 40,
    Status.PENDING: 35,
    Status.OUT: 0,
}


def score(r: Resident) -> tuple[int, list[str]]:
    """Return (priority score, list of reasons). Higher means send help sooner."""
    reading = r.reading
    mult = 1.0
    why: list[str] = []

    if r.age >= 85:
        mult += 0.4
        why.append(f"age {r.age}")
    elif r.age >= 75:
        mult += 0.25
        why.append(f"age {r.age}")

    oxygen_on_call = bool(reading and any("oxygen" in e.lower() for e in reading.medical_equipment))
    if r.oxygen or oxygen_on_call:
        mult += 0.4
        why.append("oxygen")

    if r.bedridden:
        mult += 0.5
        why.append("bedridden")
    elif r.mobility or (reading and reading.mobility_help):
        mult += 0.3
        why.append("mobility")

    if r.lives_alone:
        mult += 0.2
        why.append("lives alone")
    if r.hearing:
        mult += 0.15
        why.append("hard of hearing")

    extra = min(reading.people_with_them, 3) if reading else 0
    if extra > 0:
        mult += 0.1 * extra
        why.append(f"+{extra} with them")

    return int(round(WEIGHT[r.status] * mult)), why
