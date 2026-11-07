"""End-to-end campaign through the HTTP API, plus API error paths (Agent 2).

Offline and deterministic: Gemini is replaced with the keyword classifier, random delays are pinned,
timers are shrunk, and Twilio is never constructed.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import classify, engine as engine_mod, main
from app.config import load_settings
from app.engine import Engine
from app.models import Status
from app.seed import load_residents

EXPECTED = {"NEEDS_RIDE": 6, "WELFARE_CHECK": 2, "OUT": 7, "STAYING": 2, "NEEDS_MEDICAL": 2, "NEEDS_CALLBACK": 1}


async def fake_classify_text(text, model="", timeout=0.0, api_key=None):
    r = classify.keyword_classify(text)
    r.engine = "keywords (test)"
    return r


@pytest.fixture
def api(monkeypatch):
    s = load_settings(gemini_api_key="", phones_file="__none__.json", autopilot=True, twilio_validate=False,
                      stagger=0, ring_timeout=0.3, retry_gap=0.05, max_attempts=3)
    eng = Engine(s, load_residents(s), None)
    monkeypatch.setattr(main, "settings", s)
    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(main, "twilio", None)
    monkeypatch.setattr(engine_mod, "classify_text", fake_classify_text)
    monkeypatch.setattr(main, "classify_text", fake_classify_text)
    monkeypatch.setattr(engine_mod.random, "uniform", lambda a, b: 0.001)
    with TestClient(main.app) as c:
        yield c, eng
        eng.reset()


def poll_done(c, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = c.get("/api/state").json()
        if st["done"]:
            return st
        time.sleep(0.05)
    raise AssertionError(f"campaign not done: {c.get('/api/state').json()['counts']}")


def test_full_campaign_over_http(api):
    c, eng = api
    assert c.post("/api/start").json() == {"ok": True}
    st = poll_done(c)
    assert st["counts"] == EXPECTED
    assert st["unaccounted"] == 0 and st["total"] == 20 and st["zone"]
    scores = [row["score"] for row in st["residents"]]
    assert scores == sorted(scores, reverse=True)
    walter = next(r for r in st["residents"] if r["id"] == 2)
    assert walter["status"] == "WELFARE_CHECK" and walter["attempts"] == 3
    assert all(r["family"].endswith("(simulated)") for r in st["residents"] if r["family"])
    ts = [e["t"] for e in st["events"]]
    assert ts == sorted(ts)  # chronological
    assert not eng._tasks  # nothing left scheduled once everyone is accounted for


def test_start_while_running_is_idempotent(api):
    c, eng = api
    c.post("/api/start")
    first_started = eng.started_at
    assert c.post("/api/start").json() == {"ok": True, "already_running": True}
    assert eng.started_at == first_started
    poll_done(c)
    # once done, Start runs a fresh campaign
    assert c.post("/api/start").json() == {"ok": True}
    assert eng.started_at != first_started
    poll_done(c)


def test_reset_mid_campaign_leaves_no_orphans(api):
    c, eng = api
    c.post("/api/start")
    time.sleep(0.05)
    assert c.post("/api/reset").json() == {"ok": True}
    assert not eng._tasks
    time.sleep(0.6)  # longer than ring_timeout + retry_gap: any orphan would have fired by now
    st = c.get("/api/state").json()
    assert st["started_at"] is None and st["events"] == []
    assert all(r["status"] == "PENDING" and r["attempts"] == 0 for r in st["residents"])


def test_health(api):
    c, eng = api
    h = c.get("/api/health").json()
    assert h == {"ok": True, "gemini": False, "twilio": False, "model": main.settings.gemini_model,
                 "autopilot": True}
    c.post("/api/autopilot?on=false")
    assert c.get("/api/health").json()["autopilot"] is False


@pytest.mark.parametrize("method,path", [
    ("post", "/api/sim/999/answer?attempt=1"),
    ("post", "/api/sim/999/decline?attempt=1"),
    ("post", "/api/sim/999/say?attempt=1"),
])
def test_unknown_resident_404_with_detail(api, method, path):
    c, _ = api
    res = getattr(c, method)(path, data={"text": "hi"} if path.endswith("say?attempt=1") else None)
    assert res.status_code == 404
    assert "999" in res.json()["detail"]


def test_missing_attempt_is_422_with_detail(api):
    c, _ = api
    res = c.post("/api/sim/3/answer")
    assert res.status_code == 422 and res.json()["detail"]


def test_say_on_stale_call_does_not_change_state(api):
    c, eng = api
    r = eng.residents[3]
    r.attempts, r.status, r.channel = 2, Status.OUT, "sim"
    out = c.post("/api/sim/3/say?attempt=1", data={"text": "I need help"}).json()
    assert out["keep_listening"] is False
    assert r.status == Status.OUT


def test_twilio_webhook_unknown_resident_still_returns_twiml(api):
    c, _ = api
    res = c.post("/twilio/voice/999?attempt=1", data={})
    assert res.status_code == 200 and "<Hangup" in res.text


def test_static_mount_does_not_shadow_api(api):
    c, _ = api
    assert c.get("/static/.gitkeep").status_code == 200
    assert c.get("/static/nope.js").status_code == 404
    assert c.get("/api/health").json()["ok"] is True
