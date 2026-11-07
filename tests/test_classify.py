import asyncio

import pytest

from app import classify
from app.classify import classify_text, digits_reading, keyword_classify
from app.models import Answer

CASES = [
    ("Sí, aquí estoy. No tengo carro y uso oxígeno. Necesito que me ayuden a salir.", Answer.NEEDS_RIDE),
    ("We're out, we're at my son's place in El Cajon.", Answer.OUT),
    ("My wife's in a wheelchair and I can't drive anymore. We need help getting out. We have a dog too.", Answer.NEEDS_RIDE),
    ("I'm not leaving. I've got four horses here.", Answer.STAYING),
    ("Me caí en la cocina y no me puedo levantar.", Answer.NEEDS_MEDICAL),
    ("Hmm? Who is this?", Answer.UNCLEAR),
    ("Oh, the fire. Yes, I already left. I'm at the shelter at the high school.", Answer.OUT),
    ("Ya salimos todos, estamos bien.", Answer.OUT),
    ("My caregiver didn't come today. I can't get out of bed by myself.", Answer.NEEDS_RIDE),
    ("I don't need help, I'm out already", Answer.OUT),
    ("I can't get out, I have no car", Answer.NEEDS_RIDE),
    ("mi esposo no puede caminar", Answer.NEEDS_RIDE),
    ("I can't breathe", Answer.NEEDS_MEDICAL),
    ("No me voy, me quedo con mis animales", Answer.STAYING),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_keyword_classify(text, expected):
    assert keyword_classify(text).answer == expected


def test_extraction():
    r = keyword_classify("My wife's in a wheelchair and I can't drive anymore. We have a dog too.")
    assert r.people_with_them == 1 and r.mobility_help and r.pets == ["dog"]
    r = keyword_classify("No tengo carro y uso oxígeno.")
    assert r.medical_equipment == ["oxygen"]
    r = keyword_classify("I'm not leaving. I've got four horses here.")
    assert r.pets == ["4 horses"]
    r = keyword_classify("We're out, we're at my son's place in El Cajon.")
    assert "El Cajon" in r.where_they_are
    assert r.responder_note and r.quote


def test_digits():
    assert digits_reading("1").answer == Answer.OUT
    assert digits_reading("2").answer == Answer.NEEDS_RIDE
    assert digits_reading("3").answer == Answer.NEEDS_MEDICAL
    assert digits_reading("9") is None and digits_reading("") is None
    assert digits_reading("1").engine == "keypad"


def test_no_key_uses_keywords():
    r = asyncio.run(classify_text("we're out", api_key=""))
    assert r.answer == Answer.OUT and r.engine.startswith("keywords")


def test_gemini_error_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(classify, "_gemini_call", boom)
    r = asyncio.run(classify_text("I can't get out, I have no car", api_key="fake"))
    assert r.answer == Answer.NEEDS_RIDE and "error" in r.engine


def test_gemini_timeout_falls_back(monkeypatch):
    import time

    def slow(*a, **k):
        time.sleep(0.5)
    monkeypatch.setattr(classify, "_gemini_call", slow)
    r = asyncio.run(classify_text("we're out", timeout=0.05, api_key="fake"))
    assert r.answer == Answer.OUT and "timed out" in r.engine


def test_gemini_equipment_normalized_to_english(monkeypatch):
    from app.models import CallReading

    def fake(*a, **k):
        return CallReading(answer=Answer.NEEDS_RIDE, medical_equipment=["Oxígeno", "diálisis", "cpap"])
    monkeypatch.setattr(classify, "_gemini_call", fake)
    r = asyncio.run(classify_text("No tengo carro y uso oxígeno", api_key="fake"))
    assert r.medical_equipment == ["oxygen", "dialysis", "cpap"]
    assert r.engine.startswith("Gemini")
