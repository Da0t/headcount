import pytest

from app.classify import keyword_classify
from app.models import Answer


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I am not hurt, I just have no car.", Answer.NEEDS_RIDE),
        ("I’m not hurt, I don’t have a car.", Answer.NEEDS_RIDE),
        ("No puedo salir sin ayuda; no tengo carro.", Answer.NEEDS_RIDE),
        ("NO PUEDO CAMINAR Y NO TENGO AUTO.", Answer.NEEDS_RIDE),
        ("I fell and hurt my ankle, but I have no car.", Answer.NEEDS_MEDICAL),
        ("I can't get out of my apartment on my own, and there's no vehicle here.", Answer.NEEDS_RIDE),
        ("YA SALIMOS, ESTAMOS A SALVO.", Answer.OUT),
    ],
)
def test_keyword_classify_extra_phrasings(text, expected):
    assert keyword_classify(text).answer == expected


def test_negated_spanish_fall_is_not_medical():
    assert keyword_classify("No me caí, solo no puedo manejar.").answer == Answer.NEEDS_RIDE


def test_negated_english_injury_is_not_medical():
    reading = keyword_classify("I can't get out of my apartment, though I haven't fallen or been hurt.")
    assert reading.answer == Answer.NEEDS_RIDE


def test_extracts_spanish_companions_pets_and_equipment():
    reading = keyword_classify("Mi esposa está conmigo. Tengo dos gatos y uso CPAP.")

    assert reading.people_with_them == 1
    assert reading.pets == ["2 cat"]
    assert reading.medical_equipment == ["cpap"]
