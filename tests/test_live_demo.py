"""Single-resident live demo: profile, call-one with confirm guard, Twilio status timeline (Agent 2). Offline."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import load_settings
from app.engine import Engine
from app.models import Status
from app.seed import load_residents


class FakeTwilio:
    def __init__(self):
        self.calls = []

    def place_call(self, r, attempt):
        self.calls.append((r.id, attempt))
        return f"CA{r.id}x{attempt}"

    def send_sms(self, to, body):
        return "SM1"

    def send_checkin(self, r, attempt):
        return "SM2"


@pytest.fixture
def api(monkeypatch):
    s = load_settings(gemini_api_key="", phones_file="__none__.json", autopilot=False, twilio_validate=False,
                      public_base_url="https://headcount.test", stagger=999, ring_timeout=999, retry_gap=999)
    fake = FakeTwilio()
    eng = Engine(s, load_residents(s), fake)
    eng.residents[1].phone = "+16195550101"  # the presenter's phone (fake, never dialed)
    monkeypatch.setattr(main, "settings", s)
    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(main, "twilio", fake)
    monkeypatch.setattr(main, "DEMO_RID", 1)
    main.last_call_status.clear()
    with TestClient(main.app) as c:
        yield c, eng, fake
        eng.reset()


def wait(pred, c, n=50):
    import time
    for _ in range(n):
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_real_call_needs_confirm(api):
    c, eng, fake = api
    res = c.post("/api/residents/1/call")
    assert res.status_code == 409 and res.json()["detail"] == "Confirm to place a real call"
    assert fake.calls == []
    res = c.post("/api/residents/1/call", headers={"X-Headcount-Confirm": "yes"})
    assert res.json() == {"ok": True, "real_phone": True}
    assert wait(lambda: fake.calls, c)
    assert fake.calls[0][0] == 1


def test_simulated_call_needs_no_confirm(api):
    c, eng, fake = api
    assert c.post("/api/residents/3/call").json() == {"ok": True, "real_phone": False}
    assert wait(lambda: eng.residents[3].status == Status.CALLING, c)
    assert fake.calls == []


def test_unknown_resident_404(api):
    c, _, _ = api
    assert c.post("/api/residents/999/call").status_code == 404
    assert c.get("/api/residents/999").status_code == 404


def test_status_timeline_and_profile(api):
    c, eng, fake = api
    c.post("/api/residents/1/call", headers={"X-Headcount-Confirm": "yes"})
    assert wait(lambda: eng.residents[1].call_sid, c)
    a = eng.residents[1].attempts
    for st in ("initiated", "ringing", "in-progress"):
        assert c.post(f"/twilio/status/1?attempt={a}", data={"CallStatus": st, "CallSid": "CA1"}).status_code == 204
    p = c.get("/api/residents/1").json()
    assert p["last_call_status"]["status"] == "in-progress" and p["demo"] is True
    msgs = [e["msg"] for e in p["events"]]
    assert "Twilio: ringing" in msgs and "Twilio: in-progress" in msgs
    assert all(e["rid"] == 1 for e in p["events"])
    for k in ("assist", "contact_mode", "call_sid", "status", "name", "real_phone"):
        assert k in p
    assert eng.residents[1].status == Status.CALLING  # status pings never change the answer state


def test_old_attempt_status_logged_but_not_latest(api):
    c, eng, _ = api
    c.post("/api/residents/3/call")
    assert wait(lambda: eng.residents[3].attempts > 0, c)
    c.post("/twilio/status/3?attempt=0", data={"CallStatus": "completed"})
    assert main.last_call_status.get(3) is None
    assert any("old call" in e["msg"] for e in eng.events if e["rid"] == 3)


def test_health_has_demo_rid(api):
    c, _, _ = api
    assert c.get("/api/health").json()["demo_rid"] == 1


def test_place_call_requests_all_status_events():
    from app.twilio_voice import TwilioClient

    seen = {}

    class Calls:
        def create(self, **kw):
            seen.update(kw)
            return type("C", (), {"sid": "CA1"})()

    tc = TwilioClient.__new__(TwilioClient)
    tc.settings = load_settings(public_base_url="https://headcount.test", twilio_from_number="+16195550100",
                                phones_file="__none__.json")
    tc.client = type("Cl", (), {"calls": Calls()})()
    r = load_residents(tc.settings)[0]
    r.phone = "+16195550101"
    tc.place_call(r, 1)
    assert seen["status_callback_event"] == ["initiated", "ringing", "answered", "completed"]
