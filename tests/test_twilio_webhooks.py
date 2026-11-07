"""Twilio webhook + API acceptance tests (Agent 2). No network: Twilio is never actually called."""
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app import main
from app.config import load_settings
from app.engine import Engine
from app.models import Answer, Status
from app.seed import load_residents

BASE = "https://headcount.test"
TOKEN = "test-auth-token"


class FakeTwilio:
    def __init__(self):
        self.calls, self.texts = [], []

    def place_call(self, r, attempt):
        self.calls.append((r.id, attempt))
        return f"CA{r.id}{attempt}"

    def send_sms(self, to, body):
        self.texts.append((to, body))
        return "SM1"


def make(monkeypatch, validate=False):
    s = load_settings(public_base_url=BASE, twilio_validate=validate, twilio_auth_token=TOKEN,
                      gemini_api_key="", phones_file="__none__.json", autopilot=False,
                      stagger=999, ring_timeout=999, retry_gap=999)
    residents = load_residents(s)
    fake = FakeTwilio()
    eng = Engine(s, residents, fake)
    monkeypatch.setattr(main, "settings", s)
    monkeypatch.setattr(main, "engine", eng)
    return s, eng, fake


def ringing(eng, rid, phone="+16195550101", contact="+16195550102"):
    """Put a resident in the state right after Twilio was asked to dial them (attempt 1)."""
    r = eng.residents[rid]
    r.phone, r.contact_phone = phone, contact
    r.attempts, r.status, r.channel = 1, Status.CALLING, "twilio"
    return r


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_voice_webhook_spanish_gather(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 1)  # Maria, Spanish
    res = client.post("/twilio/voice/1?attempt=1", data={"CallSid": "CA1", "CallStatus": "in-progress"})
    assert res.status_code == 200
    assert "<Gather" in res.text
    assert 'language="es-MX"' in res.text
    assert "attempt=1&amp;n=1" in res.text
    assert "Maria" in res.text
    assert r.status == Status.IN_CALL


def test_keypad_1_out_then_completed_stays_out(monkeypatch, client):
    _, eng, fake = make(monkeypatch)
    r = ringing(eng, 7)
    client.post("/twilio/voice/7?attempt=1", data={})
    res = client.post("/twilio/gather/7?attempt=1&n=1", data={"Digits": "1"})
    assert "<Say" in res.text and "<Hangup" in res.text
    assert r.status == Status.OUT
    res = client.post("/twilio/status/7?attempt=1", data={"CallStatus": "completed"})
    assert res.status_code == 204
    assert r.status == Status.OUT
    assert fake.texts and fake.texts[0][1].startswith("Headcount demo:")


def test_speech_wheelchair_needs_ride(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 4)
    client.post("/twilio/voice/4?attempt=1", data={})
    res = client.post("/twilio/gather/4?attempt=1&n=1",
                      data={"SpeechResult": "My wife is in a wheelchair, we need help getting out"})
    assert res.status_code == 200
    assert r.status == Status.NEEDS_RIDE
    assert r.reading.mobility_help is True


def test_silence_reasks_then_retry_wait(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 3)
    client.post("/twilio/voice/3?attempt=1", data={})
    res = client.post("/twilio/gather/3?attempt=1&n=1", data={})
    assert "<Gather" in res.text and "attempt=1&amp;n=2" in res.text
    assert r.status == Status.IN_CALL
    res = client.post("/twilio/gather/3?attempt=1&n=2", data={})
    assert "<Hangup" in res.text
    assert r.status == Status.RETRY_WAIT


def test_unknown_digit_is_unclear_and_reasks(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 3)
    client.post("/twilio/voice/3?attempt=1", data={})
    res = client.post("/twilio/gather/3?attempt=1&n=1", data={"Digits": "9"})
    assert "attempt=1&amp;n=2" in res.text
    assert r.status == Status.IN_CALL and r.unclear_count == 1


def test_status_no_answer_retry_wait(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 3)
    res = client.post("/twilio/status/3?attempt=1", data={"CallStatus": "no-answer"})
    assert res.status_code == 204
    assert r.status == Status.RETRY_WAIT


def test_stale_status_ignored(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = ringing(eng, 3)
    r.attempts = 2
    client.post("/twilio/status/3?attempt=1", data={"CallStatus": "no-answer"})
    assert r.status == Status.CALLING


def test_signature_validation(monkeypatch, client):
    _, eng, _ = make(monkeypatch, validate=True)
    ringing(eng, 3)
    params = {"CallStatus": "ringing", "CallSid": "CA3"}
    path = "/twilio/status/3?attempt=1"
    bad = client.post(path, data=params, headers={"X-Twilio-Signature": "nope"})
    assert bad.status_code == 403
    sig = RequestValidator(TOKEN).compute_signature(BASE + path, params)
    good = client.post(path, data=params, headers={"X-Twilio-Signature": sig})
    assert good.status_code == 204


def test_api_state_and_sim_flow(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    st = client.get("/api/state").json()
    assert st["zone"] and st["total"] == 10 and st["twilio"] is True
    assert client.post("/api/autopilot?on=false").json() == {"autopilot": False}
    assert eng.autopilot is False

    r = eng.residents[3]
    r.attempts, r.status, r.channel = 1, Status.CALLING, "sim"
    ring = client.get("/api/sim/ringing").json()
    assert [x["id"] for x in ring] == [3] and "Dorothy" in ring[0]["prompt"] and ring[0]["attempt"] == 1
    assert "Dorothy" in client.post("/api/sim/3/answer?attempt=1").json()["say"]
    assert client.post("/api/sim/3/answer?attempt=9").status_code == 409
    out = client.post("/api/sim/3/say?attempt=1", data={"text": "We're out, at my son's place in El Cajon."}).json()
    assert out["keep_listening"] is False and out["reading"]["answer"] == Answer.OUT.value
    assert r.status == Status.OUT
    assert client.post("/api/sim/3/say?attempt=1").status_code == 400

    r9 = eng.residents[9]
    r9.attempts, r9.status, r9.channel = 1, Status.CALLING, "sim"
    assert client.post("/api/sim/9/decline?attempt=1&reason=declined").json() == {"ok": True}
    assert r9.status == Status.RETRY_WAIT


def test_audio_without_gemini_is_400(monkeypatch, client):
    _, eng, _ = make(monkeypatch)
    r = eng.residents[3]
    r.attempts, r.status, r.channel = 1, Status.IN_CALL, "sim"
    res = client.post("/api/sim/3/say?attempt=1", files={"audio": ("a.webm", b"xx", "audio/webm")})
    assert res.status_code == 400 and "GEMINI" in res.json()["detail"]


def test_twiml_helpers():
    from app.twilio_voice import say_twiml
    xml = say_twiml("Hola", "es")
    assert 'language="es-MX"' in xml and "<Hangup" in xml
