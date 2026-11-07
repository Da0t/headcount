"""Demo zone: 10 fictional residents whose scripts exercise every path through the engine."""
from __future__ import annotations

import copy
import json
import logging
import os

from app.models import Resident

log = logging.getLogger("headcount.seed")

ZONE = "Alpine (demo zone)"

# sim_script: one step per attempt. "no_answer" | "decline" | [utterances...]. A lone digit is a keypad press
# (or a "1"/"2"/"3" text reply for contact_mode="text" residents).
SEED: list[Resident] = [
    Resident(1, "Maria Gonzalez", 81, "1420 Tavern Rd", lang="es", oxygen=True, lives_alone=True,
             contact_name="Ana", contact_relation="daughter",
             sim_script=["no_answer", ["Sí, aquí estoy. No tengo carro y uso oxígeno. Necesito que me ayuden a salir."]]),
    Resident(2, "Walter Briggs", 87, "3 Arnold Way", bedridden=True, lives_alone=True,
             contact_name="Linda", contact_relation="niece",
             sim_script=["no_answer", "no_answer", "no_answer"]),
    Resident(3, "Dorothy Chen", 76, "2210 Alpine Blvd", contact_name="Kevin", contact_relation="son",
             sim_script=[["We're out, we're at my son's place in El Cajon."]]),
    Resident(4, "Frank Russo", 84, "915 Victoria Dr", mobility=True, contact_name="Tony", contact_relation="son",
             sim_script=[["My wife's in a wheelchair and I can't drive anymore. We need help getting out. "
                          "We have a dog too."]]),
    Resident(5, "James Whitaker", 79, "18 Harbison Canyon Rd", hearing=True,
             sim_script=["decline", ["I'm not leaving. I've got four horses here."]]),
    Resident(6, "Rosa Medina", 90, "640 South Grade Rd", lang="es", mobility=True, lives_alone=True,
             contact_name="Carmen", contact_relation="granddaughter",
             sim_script=[["Me caí en la cocina y no me puedo levantar."]]),
    Resident(7, "George Patel", 72, "77 Marshall Rd", hearing=True, contact_mode="text",
             contact_name="Priya", contact_relation="daughter",
             sim_script=[["1"]]),
    Resident(8, "Betty Lawson", 85, "302 Olive Ln", lives_alone=True, contact_name="Susan", contact_relation="daughter",
             sim_script=[["Hmm? Who is this?",
                          "Oh, the fire. Yes, I already left. I'm at the shelter at the high school."]]),
    Resident(9, "Luis Herrera", 68, "1105 Japatul Valley Rd", lang="es", contact_name="Marco", contact_relation="son",
             sim_script=["no_answer", ["Ya salimos todos, estamos bien."]]),
    Resident(10, "Edna Morales", 93, "48 Viejas View Pl", oxygen=True, bedridden=True, lives_alone=True,
             contact_name="Ruth", contact_relation="neighbor",
             sim_script=["no_answer", ["My caregiver didn't come today. I can't get out of bed by myself."]]),
]


def load_residents(settings=None) -> list[Resident]:
    """Fresh copies of the seed, with real numbers from residents_phones.json (gitignored) applied."""
    residents = copy.deepcopy(SEED)
    path = getattr(settings, "phones_file", "") or "residents_phones.json"
    if not os.path.exists(path):
        return residents
    try:
        with open(path, encoding="utf-8") as f:
            mapping = json.load(f)
    except Exception as exc:  # noqa: BLE001
        log.error("could not read %s: %s", path, exc)
        return residents
    by_id = {r.id: r for r in residents}
    for key, info in (mapping or {}).items():
        r = by_id.get(int(key)) if str(key).isdigit() else None
        if not r or not isinstance(info, dict):
            continue
        r.phone = str(info.get("phone", "") or "")
        r.contact_phone = str(info.get("contact_phone", "") or "")
        if info.get("name"):
            r.name = str(info["name"])
        if info.get("lang"):
            r.lang = "es" if str(info["lang"]).lower().startswith("es") else "en"
    return residents
