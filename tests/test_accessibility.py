"""Accessible evacuation help (plain rules) and the text check-in SMS webhook (Agent 2). Offline: no Gemini, no Twilio."""
import pytest
from fastapi.testclient import TestClient

from app import accessibility, main
from app.accessibility import SHELTERS, assist
from app.classify import keyword_classify
from app.config import load_settings
from app.engine import Engine
from app.models import Answer, CallReading, Status
from app.seed import load_residents

BY_NAME = {s.name: s for s in SHELTERS}


def seed():
    return {r.id: r for r in load_residents(load_settings(phones_file="__none__.json", gemini_api_key=""))}


def answered(r, text):
    """Resident after answering with `text`, classified by the keyword rules (deterministic)."""
    r.reading = keyword_classify(text)
    r.status = Status(r.reading.answer.value)
    return assist(r)


def last_utterance(r):
    return next(s for s in r.sim_script if isinstance(s, list))[-1]


# ---------------------------------------------------------------------- seed residents

def test_frank_wheelchair_van_and_pet_shelter():
    r = seed()[4]
    a = answered(r, last_utterance(r))
    assert r.status == Status.NEEDS_RIDE
    assert a["transport"] == "wheelchair van"
    sh = BY_NAME[a["shelter"]]
    assert sh.pets_allowed and sh.wheelchair_accessible
    assert any("dog" in n for n in a["needs"])


def test_edna_wheelchair_van_and_oxygen_power():
    r = seed()[10]
    a = answered(r, last_utterance(r))
    assert a["transport"] == "wheelchair van"
    sh = BY_NAME[a["shelter"]]
    assert sh.oxygen_power and sh.wheelchair_accessible
    assert any("oxygen" in n for n in a["needs"]) and any("bedridden" in n for n in a["needs"])


def test_rosa_ambulance_and_medical_staff():
    r = seed()[6]
    a = answered(r, last_utterance(r))
    assert r.status == Status.NEEDS_MEDICAL
    assert a["transport"] == "ambulance"
    assert BY_NAME[a["shelter"]].medical_staff


def test_james_staying_with_horses_note():
    r = seed()[5]
    a = answered(r, last_utterance(r))
    assert r.status == Status.STAYING
    assert a["transport"] is None
    assert any("horses" in n and "trailer" in n for n in a["needs"])
    assert BY_NAME[a["shelter"]].large_animals
    assert any("hearing" in n for n in a["needs"])


def test_maria_oxygen_needs_ride_standard_car_with_power():
    r = seed()[1]
    a = answered(r, last_utterance(r))
    assert r.status == Status.NEEDS_RIDE
    assert a["transport"] == "standard car"
    assert BY_NAME[a["shelter"]].oxygen_power


def test_out_gets_no_transport_or_shelter():
    r = seed()[3]
    a = answered(r, last_utterance(r))
    assert a["transport"] is None and a["shelter"] is None
    assert "El Cajon" in a["shelter_why"][0]


def test_welfare_check_plan_from_profile_alone():
    r = seed()[2]  # Walter, bedridden, never answers
    r.status = Status.WELFARE_CHECK
    a = assist(r)
    assert a["transport"] == "wheelchair van"
    assert BY_NAME[a["shelter"]].wheelchair_accessible


def test_pending_no_profile_needs_has_no_transport_yet():
    r = seed()[9]
    assert assist(r)["transport"] is None


# ---------------------------------------------------------------------- rules in isolation

def reading(**kw):
    kw.setdefault("answer", Answer.NEEDS_RIDE)
    return CallReading(**kw)


def test_horses_alone_get_large_animal_trailer():
    r = seed()[9]
    r.reading, r.status = reading(pets=["4 horses"]), Status.NEEDS_RIDE
    a = assist(r)
    assert a["transport"] == "large-animal trailer" and BY_NAME[a["shelter"]].large_animals


def test_mobility_help_from_reading_counts_as_wheelchair():
    r = seed()[9]
    r.reading, r.status = reading(mobility_help=True), Status.NEEDS_RIDE
    assert assist(r)["transport"] == "wheelchair van"


def test_medical_beats_wheelchair_and_cpap_needs_power():
    r = seed()[4]
    r.reading, r.status = reading(answer=Answer.NEEDS_MEDICAL, medical_equipment=["cpap"]), Status.NEEDS_MEDICAL
    a = assist(r)
    assert a["transport"] == "ambulance"
    sh = BY_NAME[a["shelter"]]
    assert sh.medical_staff and sh.oxygen_power
    assert any("cpap" in n and "power" in n for n in a["needs"])


def test_tie_keeps_scarce_medical_shelter_free():
    r = seed()[10]  # wheelchair + oxygen, not medical: the High School gym, not the medical shelter
    r.reading, r.status = reading(), Status.NEEDS_RIDE
    assert not BY_NAME[assist(r)["shelter"]].medical_staff


def test_all_shelters_marked_fictional():
    assert len(SHELTERS) >= 3
    for s in accessibility.shelters():
        assert s["fictional"] is True and "(demo)" in s["name"]


# ---------------------------------------------------------------------- API + SMS webhook

@pytest.fixture
def api(monkeypatch):
    s = load_settings(gemini_api_key="", phones_file="__none__.json", autopilot=False, twilio_validate=False,
                      public_base_url="https://headcount.test", stagger=999, ring_timeout=999, retry_gap=999)
    eng = Engine(s, load_residents(s), None)
    monkeypatch.setattr(main, "settings", s)
    monkeypatch.setattr(main, "engine", eng)
    with TestClient(main.app) as c:
        yield c, eng
        eng.reset()


def texting(eng, rid=7, phone="+16195550107"):
    r = eng.residents[rid]
    r.phone, r.attempts, r.status, r.channel = phone, 1, Status.CALLING, "twilio"
    return r


def test_state_has_assist_and_shelters_endpoint(api):
    c, _ = api
    st = c.get("/api/state").json()
    assert all("assist" in row and set(row["assist"]) == {"transport", "shelter", "shelter_why", "needs"}
               for row in st["residents"])
    sh = c.get("/api/accessibility").json()
    assert {x["name"] for x in sh} == set(BY_NAME)


def test_sms_digit_reply_marks_out_with_message_twiml(api):
    c, eng = api
    r = texting(eng)
    assert r.contact_mode == "text"
    res = c.post("/twilio/sms/7?attempt=1", data={"From": r.phone, "Body": "1"})
    assert res.status_code == 200 and "<Message>" in res.text
    assert r.status == Status.OUT


def test_sms_unclear_asks_again_then_callback(api):
    c, eng = api
    r = texting(eng)
    res = c.post("/twilio/sms/7?attempt=1", data={"Body": "what?"})
    assert "Reply 1" in res.text and r.status == Status.IN_CALL
    c.post("/twilio/sms/7?attempt=1", data={"Body": "huh"})
    assert r.status == Status.NEEDS_CALLBACK


def test_sms_free_text_needs_ride(api):
    c, eng = api
    r = texting(eng)
    c.post("/twilio/sms/7?attempt=1", data={"Body": "I can't drive, I need a ride out"})
    assert r.status == Status.NEEDS_RIDE


def test_sms_inbound_matched_by_from_number(api):
    c, eng = api
    r = texting(eng)
    res = c.post("/twilio/sms", data={"From": "+1 (619) 555-0107", "Body": "2"})
    assert "<Message>" in res.text and r.status == Status.NEEDS_RIDE


def test_sms_inbound_unknown_sender_gets_no_reply(api):
    c, eng = api
    texting(eng)
    res = c.post("/twilio/sms", data={"From": "+15555550000", "Body": "1"})
    assert res.status_code == 200 and "<Message>" not in res.text
    assert eng.residents[7].status == Status.CALLING


def test_sms_stale_attempt_does_not_change_state(api):
    c, eng = api
    r = texting(eng)
    r.attempts = 2
    c.post("/twilio/sms/7?attempt=1", data={"Body": "1"})
    assert r.status == Status.CALLING


def test_sms_signature_checked(api, monkeypatch):
    c, eng = api
    main.settings.twilio_validate, main.settings.twilio_auth_token = True, "tok"
    texting(eng)
    assert c.post("/twilio/sms/7?attempt=1", data={"Body": "1"}, headers={"X-Twilio-Signature": "bad"}).status_code == 403


def test_sim_ringing_and_answer_use_text_prompt(api):
    c, eng = api
    r = eng.residents[7]
    r.attempts, r.status, r.channel = 1, Status.CALLING, "sim"
    ring = c.get("/api/sim/ringing").json()
    assert ring[0]["contact_mode"] == "text" and "Reply 1" in ring[0]["prompt"]
    assert "Reply 1" in c.post("/api/sim/7/answer?attempt=1").json()["say"]
    out = c.post("/api/sim/7/say?attempt=1", data={"text": "1"}).json()
    assert out["reading"]["engine"] == "keypad" and r.status == Status.OUT


def test_send_checkin_texts_the_prompt():
    from app.twilio_voice import TwilioClient

    sent = []
    tc = TwilioClient.__new__(TwilioClient)
    tc.send_sms = lambda to, body: sent.append((to, body)) or "SM1"
    r = seed()[7]
    r.phone = "+16195550107"
    assert tc.send_checkin(r, 1) == "SM1"
    assert sent[0][0] == r.phone and "Reply 1" in sent[0][1]


def test_text_ask_again_lives_in_scripts_and_says_reply():
    from app import scripts
    from app.twilio_voice import text_ask_again
    for lang in ("en", "es"):
        assert text_ask_again(lang) == scripts.TEXT_ASK_AGAIN[lang]
        assert text_ask_again(lang).startswith("Headcount")
    assert "Reply 1" in scripts.TEXT_ASK_AGAIN["en"] and "Responda 1" in scripts.TEXT_ASK_AGAIN["es"]
    assert "press" not in scripts.TEXT_ASK_AGAIN["en"].lower()
