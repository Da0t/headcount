"""Real phone calls and texts through Twilio, plus the TwiML the calls speak.

The engine decides everything. This module only dials, texts, and renders what to say.
"""
from __future__ import annotations

import logging

from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Gather, VoiceResponse

from app import scripts
from app.models import Resident

log = logging.getLogger("headcount.twilio")


class TwilioClient:
    """Passed into Engine(..., twilio=TwilioClient(settings)). Methods are blocking; the engine runs them in a thread."""

    def __init__(self, settings):
        from twilio.rest import Client

        self.settings = settings
        if settings.twilio_api_key_ready:
            # API key (SK...) + secret, scoped to the account SID
            self.client = Client(settings.twilio_api_key_sid, settings.twilio_api_key_secret,
                                 settings.twilio_account_sid)
        else:
            self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    def place_call(self, r: Resident, attempt: int) -> str:
        base = self.settings.public_base_url
        core = dict(to=r.phone, from_=self.settings.twilio_from_number,
                    url=f"{base}/twilio/voice/{r.id}?attempt={attempt}")  # POST is the default; trial accounts reject an explicit method
        status = dict(status_callback=f"{base}/twilio/status/{r.id}?attempt={attempt}")
        # Richest first. Trial accounts reject some optional parameters with HTTP 400 ("limited parameter
        # access"); a rejected request places no call, so fall back until Twilio accepts one.
        tries = [
            {**core, **status, "status_callback_event": ["initiated", "ringing", "answered", "completed"],
             "timeout": int(self.settings.ring_timeout)},
            {**core, **status},
            core,
        ]
        last = None
        for params in tries:
            try:
                return self.client.calls.create(**params).sid
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "status", None) != 400:
                    raise
                last = exc
        raise last

    def send_checkin(self, r: Resident, attempt: int) -> str:
        """Text check-in instead of a call (contact_mode="text"). The reply arrives at /twilio/sms."""
        return self.send_sms(r.phone, scripts.prompt_for(r))

    def send_sms(self, to: str, body: str) -> str:
        msg = self.client.messages.create(to=to, from_=self.settings.twilio_from_number, body=body)
        return msg.sid


def prompt_twiml(r: Resident, attempt: int, n: int, base: str) -> str:
    """Ask the question (n=1) or ask again (n=2), listening for speech or one keypad digit."""
    lang = scripts.lang(r.lang)
    code = scripts.LANG_CODE[lang]
    text = scripts.PROMPT[lang].format(first=r.first) if n == 1 else scripts.ASK_AGAIN[lang]
    resp = VoiceResponse()
    gather = Gather(
        input="speech dtmf",
        num_digits=1,
        timeout=7,
        speech_timeout="auto",
        language=code,
        action=f"{base}/twilio/gather/{r.id}?attempt={attempt}&n={n}",
        method="POST",
        action_on_empty_result=True,
    )
    gather.say(text, language=code)
    resp.append(gather)
    return str(resp)


# Structured inbound call (someone calls the Headcount number). Demo line: never dispatches real responders.
INBOUND_STEPS = {
    1: {
        "en": "Headcount emergency line. This is a demo, if this is a real emergency hang up and call 911. "
              "Are you safe right now, or do you need help? You can say it in your own words, "
              "or press 1 if you are safe, 2 if you need a ride, 3 for medical help.",
        "es": "Línea de emergencia de Headcount. Esto es una demostración; si es una emergencia real, cuelgue y llame "
              "al 911. ¿Está a salvo ahora mismo o necesita ayuda? Puede decirlo con sus propias palabras, "
              "u oprimir 1 si está a salvo, 2 si necesita transporte, 3 si necesita ayuda médica.",
    },
    2: {"en": "Is anyone with you, and do you have pets?",
        "es": "¿Hay alguien con usted, y tiene mascotas?"},
    3: {"en": "What is your address or the nearest cross street?",
        "es": "¿Cuál es su dirección o la esquina más cercana?"},
}
INBOUND_STEP_LABEL = {1: "are you safe or do you need help", 2: "anyone with you, pets", 3: "address or cross street"}
ROUTED = {
    "en": " A responder is being routed to you now. This is a demo; no real responders are dispatched.",
    "es": " Un equipo de rescate va en camino. Esto es una demostración; no se envía a ningún equipo real.",
}


def inbound_twiml(r: Resident, attempt: int, step: int, base: str, text: str | None = None, n: int = 1) -> str:
    """One step of the structured inbound call: speak, then listen for speech (or a digit on step 1)."""
    lang = scripts.lang(r.lang)
    code = scripts.LANG_CODE[lang]
    resp = VoiceResponse()
    gather = Gather(
        input="speech dtmf",
        num_digits=1,
        timeout=7,
        speech_timeout="auto",
        language=code,
        action=f"{base}/twilio/inbound/{r.id}?attempt={attempt}&step={step}" + (f"&n={n}" if n > 1 else ""),
        method="POST",
        action_on_empty_result=True,
    )
    gather.say(text or INBOUND_STEPS[step][lang], language=code)
    resp.append(gather)
    return str(resp)


def say_twiml(text: str, lang: str) -> str:
    """Say one thing, then hang up."""
    resp = VoiceResponse()
    resp.say(text, language=scripts.LANG_CODE[scripts.lang(lang)])
    resp.hangup()
    return str(resp)


def text_ask_again(lang: str) -> str:
    return scripts.TEXT_ASK_AGAIN[scripts.lang(lang)]


def message_twiml(text: str) -> str:
    """Reply to an inbound SMS with one message."""
    resp = MessagingResponse()
    resp.message(text)
    return str(resp)


def signature_ok(settings, path_and_query: str, params: dict, signature: str) -> bool:
    """Check X-Twilio-Signature against PUBLIC_BASE_URL + path.

    Off when TWILIO_VALIDATE=0 or there is no auth token. Twilio signs webhooks with the account auth token,
    so an API key secret cannot validate them: with only an API key, validation is effectively off.
    """
    if not settings.twilio_validate or not settings.twilio_auth_token:
        return True
    url = settings.public_base_url + path_and_query
    return RequestValidator(settings.twilio_auth_token).validate(url, params, signature or "")
