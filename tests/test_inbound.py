"""Structured inbound call: someone calls the Headcount number (Agent 2). Offline: keyword classifier, no Twilio."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import load_settings
from app.engine import Engine
from app.models import Status
from app.seed import load_residents


@pytest.fixture
def api(monkeypatch):
    s = load_settings(gemini_api_key="", phones_file="__none__.json", autopilot=False, twilio_validate=False,
                      public_base_url="https://headcount.test", stagger=999, ring_timeout=999, retry_gap=999)
    eng = Engine(s, load_residents(s), None)
    monkeypatch.setattr(main, "settings", s)
    monkeypatch.setattr(main, "engine", eng)
    main.inbound_notes.clear()
    with TestClient(main.app) as c:
        yield c, eng
        eng.reset()


def call_in(c, phone):
    res = c.post("/twilio/incoming", data={"From": phone, "CallSid": "CAin"})
    assert res.status_code == 200 and "<Gather" in res.text and "step=1" in res.text
    return res


def test_unknown_caller_added_and_routed(api):
    c, eng = api
    n = len(eng.residents)
    res = call_in(c, "+16195551234")
    assert "This is a demo" in res.text
    r = eng.residents[max(eng.residents)]
    assert len(eng.residents) == n + 1 and r.name == "Caller ...1234" and r.status == Status.IN_CALL
    a = r.attempts
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=1", data={"SpeechResult": "I fell and I can't get up"})
    assert "step=2" in res.text.replace("&amp;", "&")
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=2", data={"SpeechResult": "my wife is here and a dog"})
    assert "step=3" in res.text.replace("&amp;", "&")
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=3", data={"SpeechResult": "Corner of Quail Ridge and Lantern Way"})
    assert "<Hangup" in res.text and "being routed" in res.text and "no real responders" in res.text
    assert r.status == Status.NEEDS_MEDICAL
    assert r.reading.where_they_are == "Corner of Quail Ridge and Lantern Way"
    msgs = [e["msg"] for e in eng.events if e["rid"] == r.id]
    assert any(m.startswith("Inbound step 2") for m in msgs) and any(m.startswith("Inbound step 3") for m in msgs)
    assert any("simulated dispatch" in m for m in msgs)


def test_known_resident_keypad_safe(api):
    c, eng = api
    r = eng.residents[3]
    r.phone = "+1 (619) 555-0103"
    call_in(c, "+16195550103")
    a = r.attempts
    c.post(f"/twilio/inbound/3?attempt={a}&step=1", data={"Digits": "1"})
    c.post(f"/twilio/inbound/3?attempt={a}&step=2", data={})
    res = c.post(f"/twilio/inbound/3?attempt={a}&step=3", data={})
    assert r.status == Status.OUT and "being routed" not in res.text and "<Hangup" in res.text


def test_silence_on_step1_reasks_then_unclear_restarts(api):
    c, eng = api
    call_in(c, "+16195559999")
    r = eng.residents[max(eng.residents)]
    a = r.attempts
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=1", data={})
    assert "step=1" in res.text.replace("&amp;", "&")
    c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=1&n=2", data={"SpeechResult": "hmm"})
    c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=2", data={})
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=3", data={})
    assert r.status == Status.IN_CALL and "step=1" in res.text.replace("&amp;", "&")


def test_spanish_resident_hears_spanish(api):
    c, eng = api
    r = next(x for x in eng.residents.values() if x.lang == "es")
    r.phone = "+16195550111"
    res = call_in(c, "+16195550111")
    assert 'language="es-MX"' in res.text and "demostración" in res.text
