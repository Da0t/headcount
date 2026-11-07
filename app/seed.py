"""Demo zone: 20 fictional residents whose scripts exercise every path through the engine."""
from __future__ import annotations

import copy
import json
import logging
import os

from app.models import Resident

log = logging.getLogger("headcount.seed")

ZONE = "Tierrasanta, San Diego (demo zone)"
ZONE_CENTER = (32.8240, -117.0990)  # Tierrasanta, City of San Diego, next to Mission Trails Regional Park

# Fictional pin locations (not real residents' homes), all inside the City of San Diego: spread on a jittered ring around the town center.
def _place(rid: int) -> tuple[float, float]:
    import math
    ang = rid * 2.399963  # golden angle
    rad = 0.0045 + 0.0017 * (rid % 7)  # roughly 0.5 to 1.6 km
    return round(ZONE_CENTER[0] + rad * math.sin(ang), 5), round(ZONE_CENTER[1] + rad * 1.2 * math.cos(ang), 5)

# sim_script: one step per attempt. "no_answer" | "decline" | [utterances...]. A lone digit is a keypad press
# (or a "1"/"2"/"3" text reply for contact_mode="text" residents).
SEED: list[Resident] = [
    Resident(1, "Maria Gonzalez", 81, "1420 Tierrasanta Blvd", lang="es", oxygen=True, lives_alone=True,
             contact_name="Ana", contact_relation="daughter",
             sim_script=["no_answer", ["Sí, aquí estoy. No tengo carro y uso oxígeno. Necesito que me ayuden a salir."]]),
    Resident(2, "Walter Briggs", 87, "3 Santo Rd", bedridden=True, lives_alone=True,
             contact_name="Linda", contact_relation="niece",
             sim_script=["no_answer", "no_answer", "no_answer"]),
    Resident(3, "Dorothy Chen", 76, "2210 Clairemont Mesa Blvd", contact_name="Kevin", contact_relation="son",
             sim_script=[["We're out, we're at my son's place in El Cajon."]]),
    Resident(4, "Frank Russo", 84, "915 Rueda Dr", mobility=True, contact_name="Tony", contact_relation="son",
             sim_script=[["My wife's in a wheelchair and I can't drive anymore. We need help getting out. "
                          "We have a dog too."]]),
    Resident(5, "James Whitaker", 79, "18 Antares Dr", hearing=True,
             sim_script=["decline", ["I'm not leaving. I've got four horses here."]]),
    Resident(6, "Rosa Medina", 90, "640 Via Valarta", lang="es", mobility=True, lives_alone=True,
             contact_name="Carmen", contact_relation="granddaughter",
             sim_script=[["Me caí en la cocina y no me puedo levantar."]]),
    Resident(7, "George Patel", 72, "77 Portobelo Dr", hearing=True, contact_mode="text",
             contact_name="Priya", contact_relation="daughter",
             sim_script=[["1"]]),
    Resident(8, "Betty Lawson", 85, "302 Colina Dorada Dr", lives_alone=True, contact_name="Susan", contact_relation="daughter",
             sim_script=[["Hmm? Who is this?",
                          "Oh, the fire. Yes, I already left. I'm at the shelter at the high school."]]),
    Resident(9, "Luis Herrera", 68, "1105 Calle de Vida", lang="es", contact_name="Marco", contact_relation="son",
             sim_script=["no_answer", ["Ya salimos todos, estamos bien."]]),
    Resident(10, "Edna Morales", 93, "48 Tierrasanta Blvd", oxygen=True, bedridden=True, lives_alone=True,
             contact_name="Ruth", contact_relation="neighbor",
             sim_script=["no_answer", ["My caregiver didn't come today. I can't get out of bed by myself."]]),
    Resident(11, "Nicolette Vale", 69, "1842 Clairemont Mesa Blvd",
             contact_name="Mira", contact_relation="niece",
             sim_script=["no_answer", ["We're out at my niece's place in El Cajon. My husband and I brought our cats."]]),
    Resident(12, "Solana Reyes", 78, "2361 Tierrasanta Blvd", lang="es", oxygen=True, mobility=True, lives_alone=True,
             contact_name="Dalia", contact_relation="daughter",
             sim_script=["no_answer", ["No tengo carro y uso oxígeno y andadera. Tengo un perro. Necesito que me ayuden a salir."]]),
    Resident(13, "Mateo Lumbre", 91, "821 Clairemont Mesa Blvd", lang="es", oxygen=True, mobility=True,
             contact_name="Rafa", contact_relation="grandson",
             sim_script=[["Me caí y necesito una ambulancia. También hago diálisis."]]),
    Resident(14, "Juniper Finch", 74, "1297 Santo Rd", hearing=True,
             contact_name="Cedar", contact_relation="spouse",
             sim_script=[["I'm staying here. My CPAP is here and the chickens need feeding."]]),
    Resident(15, "Tomasina Del Sol", 96, "2760 Via Valarta", lang="es", oxygen=True, bedridden=True,
             lives_alone=True,
             sim_script=["no_answer", "no_answer", "no_answer"]),
    Resident(16, "Peregrine Moss", 66, "44 Antares Dr",
             contact_name="Wren", contact_relation="granddaughter",
             sim_script=[["We're safe at the shelter with my granddaughter."]]),
    Resident(17, "Amalia Cielo", 83, "1905 Rueda Dr", lang="es", mobility=True,
             contact_name="Belen", contact_relation="daughter",
             sim_script=["no_answer", ["No puedo caminar y uso silla de ruedas. Tengo dos gatos."]]),
    Resident(18, "Orion Bellweather", 88, "903 Portobelo Dr", mobility=True, hearing=True, contact_mode="text",
             contact_name="Pip", contact_relation="grandchild",
             sim_script=[["2"]]),
    Resident(19, "Maribel Quill", 71, "52 Tierrasanta Blvd", lang="en",
             contact_name="Sol", contact_relation="sister",
             sim_script=[["Maybe later.", "I'm not sure."]]),
    Resident(20, "Tavio Bramble", 82, "1337 Calle de Vida", lang="es", lives_alone=False,
             contact_name="Lio", contact_relation="son",
             sim_script=[["Ya salimos y estamos a salvo en casa de mi hijo en El Cajon. El caballo está con nosotros."]]),
]


def load_residents(settings=None) -> list[Resident]:
    """Fresh copies of the seed, with real numbers from residents_phones.json (gitignored) applied."""
    residents = copy.deepcopy(SEED)
    for r in residents:
        if not (r.lat or r.lng):
            r.lat, r.lng = _place(r.id)
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
