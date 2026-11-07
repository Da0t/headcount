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
    c.post(f"/twilio/inbound/3?attempt={a}&step=2", data={"SpeechResult": "nobody, no pets"})
    res = c.post(f"/twilio/inbound/3?attempt={a}&step=3", data={"SpeechResult": "Lantern Way"})
    assert r.status == Status.OUT and "being routed" not in res.text and "<Hangup" in res.text


def test_silence_reasks_same_step_and_unclear_restarts(api):
    c, eng = api
    call_in(c, "+16195559999")
    r = eng.residents[max(eng.residents)]
    a = r.attempts
    c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=1", data={"SpeechResult": "hmm"})
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=2", data={})  # silence on step 2: same step again
    assert "step=2&amp;n=2" in res.text and "Take your time" in res.text and "<Hangup" not in res.text
    c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=2&n=2", data={"SpeechResult": "uh"})
    res = c.post(f"/twilio/inbound/{r.id}?attempt={a}&step=3", data={"SpeechResult": "blah"})
    assert r.status == Status.IN_CALL and "step=1" in res.text and "<Hangup" not in res.text  # unclear: start over


def test_silence_cap_ends_with_callback(api):
    c, eng = api
    call_in(c, "+16195557777")
    r = eng.residents[max(eng.residents)]
    res = c.post(f"/twilio/inbound/{r.id}?attempt={r.attempts}&step=1&n=20", data={})
    assert "<Hangup" in res.text and "911" in res.text
    assert r.status == Status.NEEDS_CALLBACK


def test_outbound_call_asks_three_questions(api):
    c, eng = api
    r = eng.residents[4]
    r.phone, r.attempts, r.status, r.channel = "+16195550104", 1, Status.CALLING, "twilio"
    res = c.post("/twilio/voice/4?attempt=1", data={})
    assert "Hello Frank" in res.text and "out=1" in res.text
    c.post("/twilio/inbound/4?attempt=1&step=1&out=1", data={"SpeechResult": "I can't drive and my wife uses a wheelchair"})
    c.post("/twilio/inbound/4?attempt=1&step=2&out=1", data={"SpeechResult": "my wife and our dog"})
    res = c.post("/twilio/inbound/4?attempt=1&step=3&out=1", data={"SpeechResult": "915 Lantern Way"})
    assert r.status == Status.NEEDS_RIDE and "being routed" in res.text
    assert r.reading.where_they_are == "915 Lantern Way"
    assert any(e["msg"].startswith("Call step 3") for e in eng.events if e["rid"] == 4)


def test_spanish_resident_hears_spanish(api):
    c, eng = api
    r = next(x for x in eng.residents.values() if x.lang == "es")
    r.phone = "+16195550111"
    res = call_in(c, "+16195550111")
    assert 'language="es-MX"' in res.text and "demostración" in res.text


def test_silence_reask_carries_n2(api):
    c, eng = api
    call_in(c, "+16195558888")
    r = eng.residents[max(eng.residents)]
    res = c.post(f"/twilio/inbound/{r.id}?attempt={r.attempts}&step=1", data={})
    assert "step=1&amp;n=2" in res.text


def test_sim_inbound_same_flow_and_logs(api, monkeypatch):
    c, eng = api
    monkeypatch.setattr(main, "DEMO_RID", None)
    n = len(eng.residents)
    start = c.post("/api/sim/incoming").json()
    assert start["step"] == 1 and "This is a demo" in start["say"] and len(eng.residents) == n + 1
    rid, a = start["rid"], start["attempt"]
    s1 = c.post(f"/api/sim/inbound/{rid}?attempt={a}&step=1", data={"text": "3"}).json()
    assert s1["step"] == 2 and not s1["done"] and "pets" in s1["say"]
    c.post(f"/api/sim/inbound/{rid}?attempt={a}&step=2", data={"text": "just me"})
    s3 = c.post(f"/api/sim/inbound/{rid}?attempt={a}&step=3", data={"text": "Lantern Way and Quail Ridge"}).json()
    assert s3["done"] and s3["status"] == "NEEDS_MEDICAL" and "being routed" in s3["say"]
    assert s3["reading"]["where_they_are"] == "Lantern Way and Quail Ridge"
    msgs = [e["msg"] for e in eng.events if e["rid"] == rid]
    assert any(m.startswith("Incoming call from") for m in msgs) and "Pressed 3" in msgs
    assert any(m.startswith("Inbound step 3") for m in msgs) and any("simulated dispatch" in m for m in msgs)


def test_sim_incoming_uses_demo_rid_or_404(api, monkeypatch):
    c, eng = api
    monkeypatch.setattr(main, "DEMO_RID", 3)
    assert c.post("/api/sim/incoming").json()["rid"] == 3
    assert c.post("/api/sim/incoming", json={"rid": 5}).json()["rid"] == 5
    assert c.post("/api/sim/incoming?rid=999").status_code == 404
