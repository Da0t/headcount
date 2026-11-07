"""Real phone calls and texts through Twilio, plus the TwiML the calls speak.

The engine decides everything. This module only dials, texts, and renders what to say.
"""
from __future__ import annotations

import logging

from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, VoiceResponse

from app import scripts
from app.models import Resident

log = logging.getLogger("headcount.twilio")


class TwilioClient:
    """Passed into Engine(..., twilio=TwilioClient(settings)). Methods are blocking; the engine runs them in a thread."""

    def __init__(self, settings):
        from twilio.rest import Client

        self.settings = settings
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    def place_call(self, r: Resident, attempt: int) -> str:
        base = self.settings.public_base_url
        call = self.client.calls.create(
            to=r.phone,
            from_=self.settings.twilio_from_number,
            url=f"{base}/twilio/voice/{r.id}?attempt={attempt}",
            method="POST",
            status_callback=f"{base}/twilio/status/{r.id}?attempt={attempt}",
            status_callback_method="POST",
            timeout=int(self.settings.ring_timeout),
        )
        return call.sid

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


def say_twiml(text: str, lang: str) -> str:
    """Say one thing, then hang up."""
    resp = VoiceResponse()
    resp.say(text, language=scripts.LANG_CODE[scripts.lang(lang)])
    resp.hangup()
    return str(resp)


def signature_ok(settings, path_and_query: str, params: dict, signature: str) -> bool:
    """Check X-Twilio-Signature against PUBLIC_BASE_URL + path. Off when TWILIO_VALIDATE=0 or there is no token."""
    if not settings.twilio_validate or not settings.twilio_auth_token:
        return True
    url = settings.public_base_url + path_and_query
    return RequestValidator(settings.twilio_auth_token).validate(url, params, signature or "")
