"""Bilingual call scripts and family texts. Headcount never claims to be a government agency."""
from __future__ import annotations

from app.models import Answer

LANG_CODE = {"en": "en-US", "es": "es-MX"}


def lang(code: str | None) -> str:
    """Normalize a language code to 'en' or 'es'."""
    return "es" if (code or "").lower().startswith("es") else "en"


PROMPT = {
    "en": (
        "Hello {first}, this is Headcount, the evacuation check for your neighborhood. "
        "There is an evacuation order for your area. Please tell me, in your own words, are you out, "
        "or do you need help? You can also press 1 if you are out, 2 if you need a ride, "
        "or 3 if you need medical help."
    ),
    "es": (
        "Hola {first}, le habla Headcount, la verificación de evacuación de su vecindario. "
        "Hay una orden de evacuación para su zona. Por favor dígame, con sus propias palabras, "
        "¿ya salió o necesita ayuda? También puede oprimir 1 si ya salió, 2 si necesita transporte, "
        "o 3 si necesita ayuda médica."
    ),
}

ASK_AGAIN = {
    "en": "Sorry, I didn't catch that. Are you out, or do you need help? Press 1 if you are out, 2 for a ride, 3 for medical help.",
    "es": "Perdón, no le entendí. ¿Ya salió o necesita ayuda? Oprima 1 si ya salió, 2 para transporte, 3 para ayuda médica.",
}

_DANGER = {
    "en": " If anyone is in danger right now, hang up and call 911.",
    "es": " Si alguien está en peligro ahora mismo, cuelgue y llame al 911.",
}

CONFIRM = {
    Answer.OUT: {
        "en": "Thank you. I've marked you as safely out. We'll let your family know. Stay safe.",
        "es": "Gracias. Lo marqué como fuera de peligro. Le avisaremos a su familia. Cuídese.",
    },
    Answer.NEEDS_RIDE: {
        "en": "Thank you. I've marked that you need a ride, and a responder will come to you." + _DANGER["en"],
        "es": "Gracias. Anoté que necesita transporte y un equipo de rescate irá por usted." + _DANGER["es"],
    },
    Answer.NEEDS_MEDICAL: {
        "en": "Thank you. I've marked that you need medical help, and responders are being told right now." + _DANGER["en"],
        "es": "Gracias. Anoté que necesita ayuda médica y estamos avisando a los equipos de rescate ahora mismo." + _DANGER["es"],
    },
    Answer.STAYING: {
        "en": "I understand you are staying. I've let responders know. If you change your mind, please leave as soon as you can.",
        "es": "Entiendo que se va a quedar. Ya les avisé a los equipos de rescate. Si cambia de opinión, por favor salga lo antes posible.",
    },
}

CALLBACK = {
    "en": "Thank you. A person from our team will call you back shortly. If you are in danger, call 911.",
    "es": "Gracias. Una persona de nuestro equipo le llamará pronto. Si está en peligro, llame al 911.",
}

# Text check-in for deaf and hard-of-hearing residents (contact_mode="text").
TEXT_PROMPT = {
    "en": (
        "Headcount, the evacuation check for your neighborhood: there is an evacuation order for your area, {first}. "
        "Reply 1 if you are out, 2 if you need a ride, 3 if you need medical help, or reply in your own words. "
        "If anyone is in danger right now, text or call 911."
    ),
    "es": (
        "Headcount, la verificación de evacuación de su vecindario: hay una orden de evacuación para su zona, {first}. "
        "Responda 1 si ya salió, 2 si necesita transporte, 3 si necesita ayuda médica, o responda con sus palabras. "
        "Si alguien está en peligro ahora mismo, envíe un texto o llame al 911."
    ),
}


def prompt_for(r) -> str:
    """The opening message for a resident: a spoken prompt for voice, a text for contact_mode='text'."""
    table = TEXT_PROMPT if getattr(r, "contact_mode", "voice") == "text" else PROMPT
    return table[lang(r.lang)].format(first=r.first)


RETRY_SOON = {
    "en": "We'll try calling again shortly. Goodbye.",
    "es": "Volveremos a llamarle en un momento. Adiós.",
}

_PREFIX = "Headcount demo: "

FAMILY = {
    "OUT": _PREFIX + "{first} is accounted for and says they are out. Their words: \"{quote}\"",
    "NEEDS_RIDE": _PREFIX + "{first} answered and needs a ride out. A responder has been told.",
    "NEEDS_MEDICAL": _PREFIX + "{first} answered and needs medical help. Responders have been told.",
    "STAYING": _PREFIX + "{first} answered and says they are staying home. Responders have been told.",
    "NEEDS_CALLBACK": _PREFIX + "{first} answered but we could not understand. A person will call them back.",
    "WELFARE_CHECK": _PREFIX + "We could not reach {first} after {n} calls, a responder is being sent.",
}


def family_text(status: str, first: str, quote: str = "", n: int = 0) -> str:
    return FAMILY[status].format(first=first, quote=quote, n=n)
