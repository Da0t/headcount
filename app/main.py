"""Headcount API server: dispatch board API, phone simulator, and Twilio webhooks.

Run: uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.messaging_response import MessagingResponse

from app import accessibility, scripts
from app.classify import classify_audio, classify_text, digits_reading
from app.config import load_settings
from app.engine import Engine
from app.models import Answer, CallReading
from app.seed import ZONE, load_residents
from app.twilio_voice import (TwilioClient, message_twiml, prompt_twiml, say_twiml, signature_ok,
                              text_ask_again)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("headcount.main")

STATIC = Path(__file__).parent / "static"

settings = load_settings()


E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _build_twilio(s) -> Optional[TwilioClient]:
    if s.twilio_ready and not E164.match(s.twilio_from_number):
        log.warning("TWILIO_FROM_NUMBER is not a full E.164 number (like +16195550100). Real calls are OFF; "
                    "everything runs simulated.")
        return None
    if s.twilio_ready:
        try:
            return TwilioClient(s)
        except Exception as exc:  # noqa: BLE001
            log.error("Twilio client could not start (%s). Running fully simulated.", exc)
            return None
    if s.twilio_account_sid or s.twilio_auth_token or s.twilio_api_key_sid or s.twilio_api_key_secret:
        creds = bool(s.twilio_auth_token) or s.twilio_api_key_ready
        missing = [name for name, val in [("TWILIO_ACCOUNT_SID", s.twilio_account_sid),
                                           ("TWILIO_AUTH_TOKEN or TWILIO_API_KEY_SID + TWILIO_API_KEY_SECRET", creds),
                                           ("TWILIO_FROM_NUMBER", s.twilio_from_number),
                                           ("PUBLIC_BASE_URL", s.public_base_url)] if not val]
        log.warning("Twilio credentials found but %s missing. Real calls are OFF; everything runs simulated.",
                    ", ".join(missing))
    return None


twilio = _build_twilio(settings)
if twilio is not None and settings.twilio_validate and not settings.twilio_auth_token:
    log.warning("TWILIO_VALIDATE=1 but no TWILIO_AUTH_TOKEN: webhook signatures cannot be checked with an API key "
                "secret, so validation is OFF.")
engine = Engine(settings, load_residents(settings), twilio)
app = FastAPI(title="Headcount")


# ---------------------------------------------------------------------- pages

def _page(name: str):
    path = STATIC / name
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse(f"<h1>Headcount</h1><p>{name} is not built yet.</p>", status_code=200)


@app.get("/")
async def board():
    return _page("board.html")


@app.get("/phone")
async def phone():
    return _page("phone.html")


# ---------------------------------------------------------------------- dispatch API

@app.get("/api/state")
async def state():
    snap = engine.snapshot()
    snap["zone"] = ZONE
    for row in snap["residents"]:
        r = engine.residents.get(row["id"])
        row["assist"] = accessibility.assist(r) if r else None
    return snap


@app.get("/api/accessibility")
async def accessibility_shelters():
    """Fictional demo shelters and what each can handle."""
    return accessibility.shelters()


@app.get("/api/health")
async def health():
    """Readiness at a glance for the board and the demo. Never includes secrets."""
    return {"ok": True, "gemini": settings.gemini_ready, "twilio": twilio is not None,
            "model": settings.gemini_model, "autopilot": engine.autopilot}


def _running() -> bool:
    snap = engine.snapshot()
    return engine.started_at is not None and not snap["done"]


@app.post("/api/start")
async def start():
    # Idempotent while a campaign is live: a double-click on Start must not wipe answers already collected
    # or re-dial people mid-call. Reset first to start over.
    if _running():
        return {"ok": True, "already_running": True}
    await engine.start()
    return {"ok": True}


@app.post("/api/reset")
async def reset():
    engine.reset()
    return {"ok": True}


@app.post("/api/autopilot")
async def autopilot(on: bool = True):
    settings.autopilot = on
    engine.autopilot = on
    engine.log(None, f"Autopilot {'on' if on else 'off'}.", "info")
    return {"autopilot": engine.autopilot}


# ---------------------------------------------------------------------- phone simulator

def _mode(r) -> str:
    return getattr(r, "contact_mode", "voice") or "voice"


def _prompt(r) -> str:
    return scripts.prompt_for(r)


def _resident(rid: int):
    r = engine.residents.get(rid)
    if r is None:
        raise HTTPException(404, f"no resident {rid}")
    return r


@app.get("/api/sim/ringing")
async def sim_ringing():
    return [
        {"id": r.id, "name": r.name, "first": r.first, "lang": r.lang, "status": r.status.value,
         "attempt": r.attempts, "prompt": _prompt(r), "contact_mode": _mode(r)}
        for r in engine.ringing_sim()
    ]


@app.post("/api/sim/{rid}/answer")
async def sim_answer(rid: int, attempt: int):
    r = _resident(rid)
    if not engine.answered(rid, attempt):
        raise HTTPException(409, "This call is no longer ringing.")
    return {"say": _prompt(r)}


@app.post("/api/sim/{rid}/decline")
async def sim_decline(rid: int, attempt: int, reason: str = "declined"):
    _resident(rid)
    await engine.no_answer(rid, attempt, reason)
    return {"ok": True}


@app.post("/api/sim/{rid}/say")
async def sim_say(rid: int, attempt: int, text: Optional[str] = Form(None), audio: Optional[UploadFile] = File(None)):
    r = _resident(rid)
    if audio is not None:
        if not settings.gemini_ready:
            raise HTTPException(400, "Voice input needs GEMINI_API_KEY. Type your answer instead.")
        data = await audio.read()
        reading = await classify_audio(data, audio.content_type or "audio/webm", settings.gemini_model,
                                       settings.gemini_timeout, api_key=settings.gemini_api_key)
        said = reading.quote or "(audio)"
    elif text and text.strip():
        said = text.strip()
        reading = digits_reading(said) if said.isdigit() else None
        if reading is None:
            reading = await classify_text(said, settings.gemini_model, settings.gemini_timeout,
                                          api_key=settings.gemini_api_key)
    else:
        raise HTTPException(400, "send form field 'text' or file 'audio'")
    engine.log(r, f"Said: “{said}”", "speech")
    say, keep = await engine.respond(rid, attempt, reading)
    return {"say": say, "keep_listening": keep, "reading": reading.model_dump(mode="json")}


# ---------------------------------------------------------------------- Twilio webhooks

async def _twilio_form(request: Request) -> dict:
    """Read the webhook form and check Twilio's signature. 403 if it does not match."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not signature_ok(settings, path, params, request.headers.get("X-Twilio-Signature", "")):
        msg = (f"Rejected Twilio webhook {path}: bad signature. Make PUBLIC_BASE_URL match the tunnel URL "
               "exactly (https, no trailing slash) or set TWILIO_VALIDATE=0.")
        log.warning(msg)
        engine.log(None, msg, "error")
        raise HTTPException(403, "invalid Twilio signature")
    return params


def _twiml(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


def _base() -> str:
    return settings.public_base_url


@app.post("/twilio/voice/{rid}")
async def twilio_voice(rid: int, request: Request, attempt: int = 1):
    await _twilio_form(request)
    r = engine.residents.get(rid)
    if r is None:
        return _twiml(say_twiml(scripts.CALLBACK["en"], "en"))
    if not engine.answered(rid, attempt):
        return _twiml(say_twiml(scripts.CALLBACK[scripts.lang(r.lang)], r.lang))
    return _twiml(prompt_twiml(r, attempt, 1, _base()))


@app.post("/twilio/gather/{rid}")
async def twilio_gather(rid: int, request: Request, attempt: int = 1, n: int = 1):
    params = await _twilio_form(request)
    r = engine.residents.get(rid)
    if r is None:
        return _twiml(say_twiml(scripts.CALLBACK["en"], "en"))
    lang = scripts.lang(r.lang)
    digits = params.get("Digits", "").strip()
    speech = params.get("SpeechResult", "").strip()

    if digits:
        reading = digits_reading(digits) or CallReading(
            answer=Answer.UNCLEAR, quote=f"pressed {digits}", engine="keypad")
    elif speech:
        engine.log(r, f"Said: “{speech}”", "speech")
        reading = await classify_text(speech, settings.gemini_model, settings.gemini_timeout,
                                      api_key=settings.gemini_api_key)
    else:
        if n < 2:
            return _twiml(prompt_twiml(r, attempt, 2, _base()))
        await engine.no_answer(rid, attempt, "answered but said nothing")
        return _twiml(say_twiml(scripts.RETRY_SOON[lang], lang))

    say, keep = await engine.respond(rid, attempt, reading)
    if keep:
        return _twiml(prompt_twiml(r, attempt, 2, _base()))
    return _twiml(say_twiml(say, lang))


_END_REASON = {
    "no-answer": "no answer",
    "busy": "line busy",
    "failed": "call failed",
    "canceled": "call canceled",
    "completed": "call ended without an answer",
}


@app.post("/twilio/status/{rid}")
async def twilio_status(rid: int, request: Request, attempt: int = 1):
    params = await _twilio_form(request)
    reason = _END_REASON.get(params.get("CallStatus", ""))
    if reason:
        await engine.no_answer(rid, attempt, reason)  # ignored if they already answered
    return Response(status_code=204)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


@app.post("/twilio/sms")
async def twilio_sms_inbound(request: Request):
    """The Twilio number's Messaging webhook. Inbound texts carry no resident id, so match on From.

    Only text-mode residents mapped to a real phone in residents_phones.json can match; anyone else gets no reply.
    """
    params = await _twilio_form(request)
    sender = _digits(params.get("From", ""))
    r = next((x for x in engine.residents.values()
              if sender and _mode(x) == "text" and _digits(x.phone) == sender), None)
    if r is None:
        log.info("Inbound SMS from an unmapped number ignored.")
        return _twiml(str(MessagingResponse()))
    return await _sms_reply(r, r.attempts, params)


@app.post("/twilio/sms/{rid}")
async def twilio_sms(rid: int, request: Request, attempt: int = 1):
    """Inbound SMS for a known resident and attempt. Body is a digit or free text."""
    params = await _twilio_form(request)
    r = engine.residents.get(rid)
    if r is None:
        return _twiml(message_twiml(scripts.CALLBACK["en"]))
    return await _sms_reply(r, attempt, params)


async def _sms_reply(r, attempt: int, params: dict) -> Response:
    rid = r.id
    lang = scripts.lang(r.lang)
    body = params.get("Body", "").strip()
    if not body:
        return _twiml(message_twiml(text_ask_again(lang)))
    reading = digits_reading(body) if body[:1].isdigit() and len(body) <= 3 else None
    if reading is None:
        engine.log(r, f"Texted: “{body}”", "speech")
        reading = await classify_text(body, settings.gemini_model, settings.gemini_timeout,
                                      api_key=settings.gemini_api_key)
    say, keep = await engine.respond(rid, attempt, reading)
    return _twiml(message_twiml(text_ask_again(lang) if keep else say))


# ---------------------------------------------------------------------- static assets
# Mounted last so it can never shadow an API route. Serves shared frontend modules, e.g. /static/headcount-api.js.
app.mount("/static", StaticFiles(directory=STATIC), name="static")
