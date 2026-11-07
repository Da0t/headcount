"""Shared data model. See the contract in docs/briefs."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    # unaccounted
    PENDING = "PENDING"
    CALLING = "CALLING"
    IN_CALL = "IN_CALL"
    RETRY_WAIT = "RETRY_WAIT"
    # answered
    OUT = "OUT"
    NEEDS_RIDE = "NEEDS_RIDE"
    NEEDS_MEDICAL = "NEEDS_MEDICAL"
    STAYING = "STAYING"
    NEEDS_CALLBACK = "NEEDS_CALLBACK"  # answered but unclear twice: a human calls back
    WELFARE_CHECK = "WELFARE_CHECK"  # never reached after max attempts: a person goes to the door


UNACCOUNTED = {Status.PENDING, Status.CALLING, Status.IN_CALL, Status.RETRY_WAIT}


class Answer(str, Enum):
    OUT = "OUT"
    NEEDS_RIDE = "NEEDS_RIDE"
    NEEDS_MEDICAL = "NEEDS_MEDICAL"
    STAYING = "STAYING"
    UNCLEAR = "UNCLEAR"


class CallReading(BaseModel):
    """What one resident said on one call, structured. Field descriptions are Gemini's instructions."""

    answer: Answer = Field(
        description=(
            "OUT: they have already left or are safely away. "
            "NEEDS_RIDE: they want to leave but cannot on their own (no car, cannot walk, wheelchair, "
            "cannot get out of bed) and are not hurt. "
            "NEEDS_MEDICAL: someone is hurt, fell, cannot breathe, or needs an ambulance right now. This beats NEEDS_RIDE. "
            "Using oxygen or other medical equipment is NOT by itself NEEDS_MEDICAL. "
            "STAYING: they refuse to leave. "
            "UNCLEAR: anything else, or if you are not sure. Never guess."
        )
    )
    people_with_them: int = Field(
        0, description="Number of OTHER people with them who also need to get out (e.g. 'my wife' = 1). 0 if not said."
    )
    mobility_help: bool = Field(
        False, description="True only if they said they or someone with them cannot walk, uses a wheelchair or walker, or is bedridden."
    )
    medical_equipment: list[str] = Field(
        default_factory=list,
        description="Medical equipment they mentioned, lowercase English words, e.g. 'oxygen', 'cpap', 'dialysis'.",
    )
    pets: list[str] = Field(default_factory=list, description="Animals they mentioned, lowercase English, e.g. 'dog', '4 horses'.")
    where_they_are: str = Field("", description="Where they are now if they said, e.g. 'son's house in El Cajon'. Empty if not said.")
    quote: str = Field("", description="Their most important words, verbatim, in their own language.")
    responder_note: str = Field(
        "", description="One short English line a firefighter can act on, using only what they said."
    )
    engine: str = Field("", description="Leave empty.")


@dataclass
class Resident:
    id: int
    name: str
    age: int
    address: str
    lang: str = "en"  # "en" | "es"
    oxygen: bool = False
    mobility: bool = False
    bedridden: bool = False
    lives_alone: bool = False
    hearing: bool = False
    contact_name: str = ""
    contact_relation: str = ""
    phone: str = ""  # real number: called via Twilio
    contact_phone: str = ""  # real number: family texted via Twilio
    sim_script: list = field(default_factory=list)  # per attempt: "no_answer" | "decline" | ["utterance", ...]
    # runtime
    status: Status = Status.PENDING
    attempts: int = 0  # attempt TOKEN: keeps counting across resets so late webhooks from an old campaign are stale
    attempt_base: int = 0  # value of attempts when this campaign started
    unclear_count: int = 0
    reading: Optional[CallReading] = None
    family_notified: str = ""
    channel: str = ""  # "twilio" | "sim"
    call_sid: str = ""
    updated: float = field(default_factory=time.time)

    @property
    def first(self) -> str:
        return self.name.split()[0] if self.name else ""

    @property
    def calls(self) -> int:
        """Calls placed in the current campaign (what people see)."""
        return self.attempts - self.attempt_base

    def reset_runtime(self) -> None:
        self.status = Status.PENDING
        self.attempt_base = self.attempts  # never reuse an attempt number after a reset
        self.unclear_count = 0
        self.reading = None
        self.family_notified = ""
        self.channel = ""
        self.call_sid = ""
        self.updated = time.time()
