import asyncio

import pytest

from app import engine as engine_mod
from app.classify import keyword_classify
from app.config import load_settings
from app.engine import Engine
from app.models import Answer, CallReading, Resident, Status
from app.priority import score
from app.seed import load_residents


def fast(**kw):
    base = dict(stagger=0, ring_timeout=0.15, retry_gap=0.05, autopilot=False, gemini_api_key="",
                phones_file="__none__.json")
    base.update(kw)
    return load_settings(**base)


def one(**kw):
    defaults = dict(id=1, name="Test Person", age=80, address="1 Main St", contact_name="Ana", contact_relation="daughter")
    defaults.update(kw)
    return Resident(**defaults)


def run(coro):
    return asyncio.run(coro)


async def wait_for(pred, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return pred()


def test_never_answers_goes_to_welfare_check():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.WELFARE_CHECK)
        assert r.attempts == 3
        assert r.family_notified == "Texted Ana (daughter) (simulated)"
        assert any(ev["kind"] == "alert" and "1 Main St" in ev["msg"] for ev in e.events)
        e.reset()
    run(go())


def test_answers_on_second_attempt_out_and_stays_out():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.CALLING and r.attempts == 2)
        assert e.answered(1, 2)
        say, keep = await e.respond(1, 2, CallReading(answer=Answer.OUT, quote="We're out"))
        assert keep is False and "safely out" in say
        await asyncio.sleep(0.5)  # longer than any old timer
        assert r.status == Status.OUT and r.attempts == 2
        e.reset()
    run(go())


def test_two_unclear_answers_need_callback():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        assert await wait_for(lambda: e.residents[1].status == Status.CALLING)
        assert e.answered(1, 1)
        _, keep = await e.respond(1, 1, CallReading(answer=Answer.UNCLEAR, quote="hmm"))
        assert keep is True
        _, keep = await e.respond(1, 1, CallReading(answer=Answer.UNCLEAR, quote="what"))
        assert keep is False
        assert e.residents[1].status == Status.NEEDS_CALLBACK
        e.reset()
    run(go())


def test_late_no_answer_after_real_answer_changes_nothing():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        assert await wait_for(lambda: e.residents[1].status == Status.CALLING)
        e.answered(1, 1)
        await e.respond(1, 1, CallReading(answer=Answer.NEEDS_RIDE, quote="no car"))
        await e.no_answer(1, 1, reason="completed")
        await e.no_answer(1, 0, reason="stale")
        assert e.residents[1].status == Status.NEEDS_RIDE
        assert e.residents[1].attempts == 1
        e.reset()
    run(go())


def test_stale_respond_returns_callback():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        assert await wait_for(lambda: e.residents[1].attempts == 2)
        say, keep = await e.respond(1, 1, CallReading(answer=Answer.OUT))
        assert keep is False and e.residents[1].status != Status.OUT
        assert e.answered(1, 1) is False
        e.reset()
    run(go())


@pytest.mark.parametrize("rid,expected", [(3, Status.OUT), (5, Status.STAYING), (4, Status.NEEDS_RIDE),
                                          (1, Status.NEEDS_RIDE), (6, Status.NEEDS_MEDICAL), (7, Status.OUT),
                                          (8, Status.OUT), (9, Status.OUT), (10, Status.NEEDS_RIDE),
                                          (2, Status.WELFARE_CHECK)])
def test_autopilot_plays_seed_scripts(monkeypatch, rid, expected):
    monkeypatch.setattr(engine_mod.random, "uniform", lambda a, b: 0.001)

    async def go():
        residents = [r for r in load_residents(fast()) if r.id == rid]
        e = Engine(fast(autopilot=True, ring_timeout=0.3), residents)
        await e.start()
        r = e.residents[rid]
        assert await wait_for(lambda: r.status not in {Status.PENDING, Status.CALLING, Status.IN_CALL, Status.RETRY_WAIT})
        assert r.status == expected
        e.reset()
    run(go())


def test_full_seed_campaign_finishes():
    async def go():
        import random as _r
        e = Engine(fast(autopilot=True, ring_timeout=0.3), load_residents(fast()))
        orig = _r.uniform
        engine_mod.random.uniform = lambda a, b: 0.001
        try:
            await e.start()
            assert await wait_for(lambda: e.snapshot()["done"], timeout=5)
        finally:
            engine_mod.random.uniform = orig
        snap = e.snapshot()
        assert snap["counts"] == {"NEEDS_RIDE": 6, "WELFARE_CHECK": 2, "OUT": 7, "STAYING": 2, "NEEDS_MEDICAL": 2,
                                  "NEEDS_CALLBACK": 1}
        scores = [row["score"] for row in snap["residents"]]
        assert scores == sorted(scores, reverse=True)
        assert snap["residents"][-1]["status"] == "OUT"
        e.reset()
    run(go())


def test_priority_order_and_reasons():
    edna = one(id=10, name="Edna Morales", age=93, oxygen=True, bedridden=True, lives_alone=True)
    edna.status = Status.WELFARE_CHECK
    frank = one(id=4, name="Frank Russo", age=84, mobility=True)
    frank.status = Status.NEEDS_RIDE
    frank.reading = keyword_classify("My wife's in a wheelchair and I can't drive anymore.")
    dorothy = one(id=3, name="Dorothy Chen", age=76)
    dorothy.status = Status.OUT
    s_edna, why = score(edna)
    s_frank, _ = score(frank)
    s_dot, _ = score(dorothy)
    assert s_edna > s_frank > s_dot == 0
    assert "bedridden" in why and "oxygen" in why


def test_contract_example_scores():
    walter = one(name="Walter Briggs", age=87, bedridden=True, lives_alone=True)
    walter.status = Status.WELFARE_CHECK
    assert score(walter) == (210, ["age 87", "bedridden", "lives alone"])
    maria = one(name="Maria Gonzalez", age=81, oxygen=True, lives_alone=True)
    maria.status = Status.NEEDS_RIDE
    assert score(maria) == (139, ["age 81", "oxygen", "lives alone"])


def test_failed_twilio_call_counts_as_missed():
    class BrokenTwilio:
        def place_call(self, r, attempt):
            raise RuntimeError("boom")

        def send_sms(self, to, body):
            return "SM1"

    async def go():
        e = Engine(fast(), [one(phone="+16195550101", contact_phone="+16195550102")], twilio=BrokenTwilio())
        await e.start()
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.WELFARE_CHECK)
        assert r.channel == "twilio" and r.family_notified == "Texted Ana (daughter)"
        e.reset()
    run(go())


def test_snapshot_shape():
    e = Engine(fast(), load_residents(fast()))
    snap = e.snapshot()
    for key in ["total", "unaccounted", "done", "started_at", "max_attempts", "twilio", "gemini", "autopilot",
                "counts", "residents", "events"]:
        assert key in snap
    row = snap["residents"][0]
    for key in ["id", "name", "first", "age", "address", "lang", "status", "attempts", "channel", "score", "why",
                "reading", "family", "updated", "real_phone"]:
        assert key in row
    assert snap["done"] is False and snap["total"] == 20


def test_late_callback_from_previous_campaign_is_stale():
    """Copilot review finding: attempt numbers must not be reused after a reset."""
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        assert await wait_for(lambda: e.residents[1].status == Status.CALLING)
        old_attempt = e.residents[1].attempts
        await e.start()  # reset + new campaign
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.CALLING)
        assert r.attempts != old_attempt and r.calls == 1
        assert e.answered(1, old_attempt) is False
        say, keep = await e.respond(1, old_attempt, CallReading(answer=Answer.OUT))
        assert keep is False and r.status == Status.CALLING
        assert e.snapshot()["residents"][0]["attempts"] == 1
        e.reset()
    run(go())


def test_welfare_check_counts_calls_not_tokens_after_reset():
    async def go():
        e = Engine(fast(), [one()])
        await e.start()
        assert await wait_for(lambda: e.residents[1].status == Status.WELFARE_CHECK)
        await e.start()
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.WELFARE_CHECK)
        assert r.calls == 3 and r.attempts == 6
        assert any("after 3 calls" in ev["msg"] for ev in e.events)
        e.reset()
    run(go())


def test_autopilot_off_stops_scheduled_answers(monkeypatch):
    monkeypatch.setattr(engine_mod.random, "uniform", lambda a, b: 0.05)

    async def go():
        residents = [r for r in load_residents(fast()) if r.id == 3]
        e = Engine(fast(autopilot=True, ring_timeout=5), residents)
        await e.start()
        assert await wait_for(lambda: e.residents[3].status == Status.CALLING)
        e.autopilot = False
        await asyncio.sleep(0.3)
        assert e.residents[3].status == Status.CALLING  # nobody answered for them
        e.reset()
    run(go())


def test_family_text_finishing_after_reset_is_ignored():
    import threading
    gate = threading.Event()

    class SlowTwilio:
        def place_call(self, r, attempt):
            return "CA1"

        def send_sms(self, to, body):
            gate.wait(2)
            return "SM1"

    async def go():
        e = Engine(fast(), [one(phone="+16195550101", contact_phone="+16195550102")], twilio=SlowTwilio())
        await e.start()
        assert await wait_for(lambda: e.residents[1].status == Status.CALLING)
        e.answered(1, e.residents[1].attempts)
        task = asyncio.create_task(e.respond(1, e.residents[1].attempts, CallReading(answer=Answer.OUT, quote="out")))
        await asyncio.sleep(0.05)
        e.reset()
        gate.set()
        await task
        assert e.residents[1].family_notified == ""
        assert not any(ev["kind"] == "family" for ev in e.events)
    run(go())


def test_twilio_ready_rejects_placeholders():
    base = dict(twilio_account_sid="AC" + "0" * 32, twilio_api_key_sid="SK1", twilio_api_key_secret="x",
                twilio_from_number="+16195550100", public_base_url="https://abc.trycloudflare.com")
    assert load_settings(**base).twilio_ready
    assert not load_settings(**{**base, "twilio_from_number": "+1"}).twilio_ready
    assert not load_settings(**{**base, "public_base_url": "https://your-tunnel.trycloudflare.com"}).twilio_ready
    assert not load_settings(**{**base, "public_base_url": "http://abc.trycloudflare.com"}).twilio_ready
    assert not load_settings(**{**base, "twilio_api_key_secret": ""}).twilio_ready


def test_text_mode_resident_gets_text_checkin_and_digit_reply():
    from app import scripts
    from app.classify import digits_reading

    async def go():
        e = Engine(fast(), [one(contact_mode="text", lang="es")])
        await e.start()
        r = e.residents[1]
        assert await wait_for(lambda: r.status == Status.CALLING)
        assert any("Texted check-in" in ev["msg"] for ev in e.events)
        assert "Responda 1" in scripts.prompt_for(r)
        say, keep = await e.respond(1, r.attempts, digits_reading("2"))
        assert r.status == Status.NEEDS_RIDE and keep is False
        assert any(ev["msg"].startswith("Replied") for ev in e.events)
        assert e.snapshot()["residents"][0]["contact_mode"] == "text"
        e.reset()
    run(go())


def test_text_mode_uses_twilio_send_checkin_not_place_call():
    calls = []

    class FakeTwilio:
        def place_call(self, r, attempt):
            calls.append("call")
            return "CA1"

        def send_checkin(self, r, attempt):
            calls.append("text")
            return "SM1"

        def send_sms(self, to, body):
            return "SM2"

    async def go():
        e = Engine(fast(), [one(contact_mode="text", phone="+16195550101")], twilio=FakeTwilio())
        await e.start()
        assert await wait_for(lambda: calls)
        assert calls == ["text"]
        e.reset()
    run(go())


def test_george_is_text_mode_in_seed():
    g = [r for r in load_residents(fast()) if r.name == "George Patel"][0]
    assert g.contact_mode == "text" and g.hearing


def test_call_one_dials_only_that_resident():
    async def go():
        e = Engine(fast(), [one(id=1), one(id=2, name="Other Person")])
        assert await e.call_one(2) is True
        assert await wait_for(lambda: e.residents[2].status == Status.CALLING)
        assert e.residents[1].status == Status.PENDING and e.residents[1].attempts == 0
        assert any("single call requested" in ev["msg"] for ev in e.events)
        assert await e.call_one(99) is False
        e.reset()
    run(go())
