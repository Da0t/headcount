"""Turn what a resident said into a structured CallReading.

Gemini only *understands* speech. It never decides who gets help: the engine does that in plain Python.
A phone call must never hang waiting on AI, so every Gemini call has a timeout and a keyword fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from typing import Optional

from app.models import Answer, CallReading

log = logging.getLogger("headcount.classify")

PROMPT = """You are listening to one older adult on a phone call during a wildfire evacuation order.
Read what they said and fill in the JSON fields. Rules:
- Use only what they actually said. Never guess or add facts. If you are not sure, answer UNCLEAR.
- They may speak English or Spanish, and the text may be a noisy phone transcription.
- NEEDS_MEDICAL beats NEEDS_RIDE: if anyone is hurt, fell, cannot breathe, or needs an ambulance, it is NEEDS_MEDICAL.
- Cannot walk, uses a wheelchair, has no car, or cannot get out of bed, but nobody is hurt: NEEDS_RIDE.
- Refusing to leave is STAYING.
- Already left, or safely somewhere else: OUT.
- "quote" is their key words, verbatim, in their own language.
- "responder_note" is one short English line a firefighter can act on.
- Leave "engine" empty.
What they said:"""

AUDIO_PROMPT = PROMPT.replace("What they said:", "Their words are in the attached audio. Put a transcription of the key words in \"quote\".")


# --------------------------------------------------------------------------- Gemini

_client = None
_client_key = None


def _api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _get_client(key: str):
    global _client, _client_key
    if _client is None or _client_key != key:
        from google import genai

        _client = genai.Client(api_key=key)
        _client_key = key
    return _client


def _gemini_call(contents: list, model: str, key: str) -> CallReading:
    from google.genai import types

    client = _get_client(key)
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CallReading,
            temperature=0,
        ),
    )
    reading = resp.parsed
    if isinstance(reading, dict):
        reading = CallReading.model_validate(reading)
    if not isinstance(reading, CallReading):
        reading = CallReading.model_validate_json(resp.text)
    return reading


def _short(exc: BaseException) -> str:
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    name = type(exc).__name__
    return f"{name}: {msg[:80]}" if msg else name


async def classify_text(text: str, model: str = "gemini-3.5-flash", timeout: float = 6.0,
                        api_key: Optional[str] = None) -> CallReading:
    """Gemini first; on any error, timeout, or missing key, fall back to keywords."""
    text = (text or "").strip()
    if not text:
        r = keyword_classify(text)
        r.engine = "keywords (nothing heard)"
        return r
    key = api_key if api_key is not None else _api_key()
    if not key:
        r = keyword_classify(text)
        r.engine = "keywords (no Gemini key)"
        return r
    try:
        reading = await asyncio.wait_for(asyncio.to_thread(_gemini_call, [PROMPT, text], model, key), timeout)
        if not reading.quote:
            reading.quote = text
        reading.engine = f"Gemini ({model})"
        return reading
    except asyncio.TimeoutError:
        why = f"Gemini timed out after {timeout:g}s"
    except Exception as exc:  # noqa: BLE001 - any failure falls back
        why = f"Gemini error, {_short(exc)}"
    log.warning("classify_text fallback: %s", why)
    r = keyword_classify(text)
    r.engine = f"keywords ({why})"
    return r


async def classify_audio(audio_bytes: bytes, mime: str = "audio/webm", model: str = "gemini-3.5-flash",
                         timeout: float = 6.0, api_key: Optional[str] = None) -> CallReading:
    """Gemini only. If Gemini is unavailable the reading is UNCLEAR, so the call asks again."""
    key = api_key if api_key is not None else _api_key()
    if not key:
        return CallReading(answer=Answer.UNCLEAR, engine="unavailable (no Gemini key for audio)")
    if not audio_bytes:
        return CallReading(answer=Answer.UNCLEAR, engine="unavailable (empty audio)")
    try:
        from google.genai import types

        part = types.Part.from_bytes(data=audio_bytes, mime_type=mime or "audio/webm")
        reading = await asyncio.wait_for(asyncio.to_thread(_gemini_call, [AUDIO_PROMPT, part], model, key), timeout)
        reading.engine = f"Gemini ({model}, audio)"
        return reading
    except asyncio.TimeoutError:
        why = f"Gemini timed out after {timeout:g}s"
    except Exception as exc:  # noqa: BLE001
        why = f"Gemini error, {_short(exc)}"
    log.warning("classify_audio failed: %s", why)
    return CallReading(answer=Answer.UNCLEAR, engine=f"unavailable ({why})")


# --------------------------------------------------------------------------- keypad

_DIGITS = {
    "1": (Answer.OUT, "Pressed 1: says they are out."),
    "2": (Answer.NEEDS_RIDE, "Pressed 2: needs a ride out."),
    "3": (Answer.NEEDS_MEDICAL, "Pressed 3: needs medical help."),
}


def digits_reading(digits: str) -> Optional[CallReading]:
    d = (digits or "").strip()[:1]
    if d not in _DIGITS:
        return None
    answer, note = _DIGITS[d]
    return CallReading(answer=answer, quote=f"(pressed {d})", responder_note=note, engine="keypad")


# --------------------------------------------------------------------------- keywords

def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"\bcan ?not\b", "can't", t)
    t = re.sub(r"\bcant\b", "can't", t)
    t = re.sub(r"\bwont\b", "won't", t)
    t = re.sub(r"\bim\b", "i'm", t)
    t = re.sub(r"\bwere out\b", "we're out", t)
    t = re.sub(r"\s+", " ", t)
    return " " + t.strip() + " "


MEDICAL = [
    "i fell", "fell down", "she fell", "he fell", "hurt", "injured", "bleeding", "can't breathe",
    "hard to breathe", "chest pain", "heart attack", "stroke", "ambulance", "unconscious", "burned",
    "me cai", "se cayo", "no puedo respirar", "no puede respirar", "ambulancia", "herido", "herida",
    "me lastime", "sangrando", "dolor de pecho",
]
NOT_MEDICAL = ["not hurt", "nobody's hurt", "nobody is hurt", "no one is hurt", "no estoy herid", "nadie esta herid"]
STAYING = [
    "not leaving", "i'm staying", "we're staying", "staying here", "staying home", "won't leave",
    "not going anywhere", "not going to leave", "refuse to leave",
    "no me voy", "me quedo", "nos quedamos", "no vamos a salir", "no voy a salir",
]
OUT = [
    "we're out", "i'm out", "already left", "we left", "i left", "we got out", "i got out", "evacuated",
    "at the shelter", "we're safe", "i'm safe", "already gone", "we're gone",
    "ya salimos", "ya sali", "ya nos fuimos", "ya me fui", "estamos bien", "estamos fuera", "estoy fuera",
    "estamos a salvo", "estoy a salvo",
]
RIDE = [
    "no car", "don't have a car", "don't drive", "can't drive", "can't walk", "wheelchair", "walker",
    "can't get out", "need a ride", "need help getting out", "pick me up", "pick us up", "bedridden",
    "can't leave", "stuck",
    "no tengo carro", "no tengo coche", "no tengo auto", "no manejo", "no puedo manejar", "no puedo caminar",
    "no puede caminar", "silla de ruedas", "andadera", "no me puedo levantar", "no puedo levantarme",
    "no puedo salir", "necesito que me ayuden", "necesito ayuda para salir", "necesito transporte",
]
MOBILITY = [
    "can't walk", "wheelchair", "walker", "bedridden", "can't get out of bed", "can't stand",
    "no puedo caminar", "no puede caminar", "silla de ruedas", "andadera", "no me puedo levantar",
    "no puedo levantarme", "en cama",
]
EQUIPMENT = {
    "oxygen": ["oxygen", "oxigeno", " o2 "],
    "cpap": ["cpap"],
    "dialysis": ["dialysis", "dialisis"],
}
PETS = {
    "dog": ["dog", "perro", "perrito"],
    "cat": ["cat ", "cats", "gato"],
    "horses": ["horse", "caballo"],
    "bird": ["bird", "pajaro", "perico"],
}
NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
SPOUSE = ["my wife", "my husband", "wife's", "husband's", "mi esposo", "mi esposa", "mi marido", "mi mujer", "my spouse"]


def _has(t: str, phrases) -> bool:
    return any(p in t for p in phrases)


def _pets(t: str) -> list[str]:
    found = []
    for name, words in PETS.items():
        for w in words:
            m = re.search(r"(\d+|" + "|".join(NUMBERS) + r") " + re.escape(w.strip()), t)
            if m:
                n = m.group(1)
                found.append(f"{NUMBERS.get(n, n)} {name}")
                break
            if w in t:
                found.append(name)
                break
    return found


# A negation up to 3 words before an injury word cancels it ("no me cai", "haven't fallen or been hurt"),
# unless a clause break or "and/but" sits in between ("I can't walk and I'm hurt" stays medical).
_NEGATED_INJURY = re.compile(
    r"\b(?:not|never|no|nobody|nadie|ni|\w+n't)\b"
    r"(?:\s+(?!and\b|but\b|y\b|pero\b)[\w']+){0,3}?"
    r"\s+(?:hurt|injured|fell|fallen|me cai|se cayo|herid[oa]|lastimad[oa]|me lastime)\b"
    # chained: "haven't fallen or been hurt", "no me cai ni me lastime"
    r"(?:\s+(?:or|nor|ni)(?:\s+[\w']+){0,2}?\s+(?:hurt|injured|fell|fallen|me cai|herid[oa]|lastimad[oa]|me lastime)\b)*"
)

_WHERE = re.compile(
    r"\b(?:we're|we are|i'm|i am|staying)\s+(at|with|in)\s+([^.!?,;]+(?:\s+in\s+[^.!?,;]+)?)", re.I
)
_WHERE_ES = re.compile(r"\b(?:estamos|estoy)\s+(en|con)\s+([^.!?,;]+)", re.I)


def _where(text: str) -> str:
    t = (text or "").replace("’", "'")
    m = _WHERE.search(t) or _WHERE_ES.search(t)
    if not m:
        return ""
    place = f"{m.group(1)} {m.group(2).strip()}"
    if re.match(r"(en|in) (peligro|danger|bed|cama)", place, re.I):
        return ""
    return place


def keyword_classify(text: str) -> CallReading:
    t = _norm(text)
    t_med = _NEGATED_INJURY.sub(" ", t)
    for p in NOT_MEDICAL:
        t_med = t_med.replace(p, " ")

    ride = _has(t, RIDE)
    if _has(t_med, MEDICAL):
        answer = Answer.NEEDS_MEDICAL
    elif _has(t, STAYING):
        answer = Answer.STAYING
    elif _has(t, OUT) and not ride:
        answer = Answer.OUT
    elif ride:
        answer = Answer.NEEDS_RIDE
    else:
        answer = Answer.UNCLEAR

    mobility = _has(t, MOBILITY)
    equipment = [name for name, words in EQUIPMENT.items() if _has(t, words)]
    pets = _pets(t)
    people = 1 if _has(t, SPOUSE) else 0
    where = _where(text) if answer == Answer.OUT else ""

    reading = CallReading(
        answer=answer,
        people_with_them=people,
        mobility_help=mobility,
        medical_equipment=equipment,
        pets=pets,
        where_they_are=where,
        quote=(text or "").strip(),
        engine="keywords",
    )
    reading.responder_note = build_note(reading)
    return reading


_LEAD = {
    Answer.OUT: "Says they are out.",
    Answer.NEEDS_RIDE: "Needs a ride out.",
    Answer.NEEDS_MEDICAL: "Needs medical help.",
    Answer.STAYING: "Refusing to leave.",
    Answer.UNCLEAR: "Answer unclear.",
}


def build_note(r: CallReading) -> str:
    parts = [_LEAD[r.answer]]
    if r.where_they_are:
        parts.append(f"Now {r.where_they_are}.")
    if r.mobility_help:
        parts.append("Mobility help needed.")
    if r.medical_equipment:
        parts.append("Uses " + ", ".join(r.medical_equipment) + ".")
    if r.people_with_them:
        n = r.people_with_them
        parts.append(f"{n} other {'person' if n == 1 else 'people'} with them.")
    if r.pets:
        parts.append("Animals: " + ", ".join(r.pets) + ".")
    return " ".join(parts)
