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
        assert snap["counts"] == {"NEEDS_RIDE": 3, "WELFARE_CHECK": 1, "OUT": 4, "STAYING": 1, "NEEDS_MEDICAL": 1}
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
    assert snap["done"] is False and snap["total"] == 10
