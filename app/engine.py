"""The call state machine. Plain, tested Python decides retries, welfare checks, and who gets a text.

Every event carries the attempt number it belongs to, so a late webhook from an old call can never
overwrite a newer state.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Callable, Optional

from app import scripts
from app.classify import classify_text, digits_reading
from app.models import UNACCOUNTED, Answer, CallReading, Resident, Status
from app.priority import score

log = logging.getLogger("headcount.engine")

LIVE = {Status.CALLING, Status.IN_CALL}
MAX_EVENTS = 500

_KIND_FOR = {
    Status.OUT: "good",
    Status.NEEDS_RIDE: "warn",
    Status.STAYING: "warn",
    Status.NEEDS_MEDICAL: "alert",
}
_LABEL = {
    Status.OUT: "Out",
    Status.NEEDS_RIDE: "Needs a ride",
    Status.NEEDS_MEDICAL: "Needs medical help",
    Status.STAYING: "Staying",
}


class Engine:
    def __init__(self, settings, residents: list[Resident], twilio=None):
        self.settings = settings
        self.residents: dict[int, Resident] = {r.id: r for r in residents}
        self.twilio = twilio
        self.autopilot: bool = bool(settings.autopilot)
        self.events: list[dict[str, Any]] = []
        self.started_at: Optional[float] = None
        self._tasks: dict[tuple[int, str], asyncio.Task] = {}

    # ------------------------------------------------------------------ tasks

    def _cancel(self, rid: int, kind: str) -> None:
        task = self._tasks.pop((rid, kind), None)
        if task is None or task.done():
            return
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is current:
            return  # never cancel the task we are running in
        task.cancel()

    def _schedule(self, rid: int, kind: str, delay: float, fn: Callable, *args) -> None:
        """One pending task per (resident, kind). Scheduling replaces the previous one."""
        self._cancel(rid, kind)
        key = (rid, kind)

        async def runner():
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                result = fn(*args)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one resident's bug never stops the campaign
                log.exception("task %s failed", key)
                self.log(self.residents.get(rid), f"Internal error in {kind}: {exc}", "error")
            finally:
                if self._tasks.get(key) is task:
                    self._tasks.pop(key, None)

        task = asyncio.get_running_loop().create_task(runner())
        self._tasks[key] = task

    def _cancel_all(self) -> None:
        for (rid, kind) in list(self._tasks):
            self._cancel(rid, kind)
        self._tasks.clear()

    # ------------------------------------------------------------------ log

    def log(self, r: Optional[Resident], msg: str, kind: str = "info") -> None:
        ev = {"t": time.time(), "rid": r.id if r else None, "name": r.name if r else None, "kind": kind, "msg": msg}
        self.events.append(ev)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        log.info("[%s] %s%s", kind, f"{r.name}: " if r else "", msg)

    def _touch(self, r: Resident, status: Optional[Status] = None) -> None:
        if status is not None:
            r.status = status
        r.updated = time.time()

    # ------------------------------------------------------------------ campaign

    def reset(self) -> None:
        self._cancel_all()
        for r in self.residents.values():
            r.reset_runtime()
        self.events = []
        self.started_at = None

    async def start(self) -> None:
        self.reset()
        self.started_at = time.time()
        n = len(self.residents)
        self.log(None, f"Evacuation order received. Calling {n} residents.", "start")
        for i, rid in enumerate(self.residents):
            self._schedule(rid, "dial", i * self.settings.stagger, self._dial, rid)

    async def _dial(self, rid: int) -> None:
        r = self.residents[rid]
        if r.status not in (Status.PENDING, Status.RETRY_WAIT):
            return
        r.attempts += 1
        attempt = r.attempts
        r.call_sid = ""
        self._touch(r, Status.CALLING)

        if self.twilio is not None and r.phone:
            r.channel = "twilio"
            self.log(r, f"Calling {r.phone} (attempt {attempt}).", "info")
            try:
                sid = await asyncio.to_thread(self.twilio.place_call, r, attempt)
            except Exception as exc:  # noqa: BLE001
                self.log(r, f"Call could not be placed: {exc}", "error")
                await self.no_answer(rid, attempt, reason="call could not be placed")
                return
            if r.attempts == attempt and r.status in LIVE:
                r.call_sid = str(sid or "")
                # safety net in case Twilio's status callback never arrives
                self._schedule(rid, "ring", self.settings.ring_timeout + 120, self.no_answer, rid, attempt,
                               "no status from Twilio")
            return

        r.channel = "sim"
        self.log(r, f"Calling (simulated, attempt {attempt}).", "info")
        self._schedule(rid, "ring", self.settings.ring_timeout, self.no_answer, rid, attempt, "no answer")
        step = self._step(r, attempt)
        if self.autopilot and step is not None and step != "no_answer":
            # pick up before the ring timeout, even if someone shortens HEADCOUNT_RING_TIMEOUT for a demo
            delay = min(random.uniform(2.5, 6), self.settings.ring_timeout * 0.6)
            self._schedule(rid, "auto", delay, self._autopilot, rid, attempt, step)

    @staticmethod
    def _step(r: Resident, attempt: int):
        if 1 <= attempt <= len(r.sim_script):
            return r.sim_script[attempt - 1]
        return None

    # ------------------------------------------------------------------ call events

    async def no_answer(self, rid: int, attempt: int, reason: str = "no answer") -> None:
        r = self.residents.get(rid)
        if r is None or attempt != r.attempts or r.status not in LIVE:
            return  # stale, or they already answered
        self._cancel(rid, "ring")
        self._cancel(rid, "auto")
        max_attempts = self.settings.max_attempts
        if r.attempts >= max_attempts:
            self._touch(r, Status.WELFARE_CHECK)
            self.log(r, f"No answer after {r.attempts} calls. Welfare check: send a person to {r.address}.", "alert")
            await self._text_family(r)
        else:
            self._touch(r, Status.RETRY_WAIT)
            gap = self.settings.retry_gap
            self.log(r, f"Call {attempt} missed ({reason}). Retrying in {gap:g}s.", "warn")
            self._schedule(rid, "dial", gap, self._dial, rid)

    def answered(self, rid: int, attempt: int) -> bool:
        r = self.residents.get(rid)
        if r is None or attempt != r.attempts or r.status not in LIVE:
            return False
        if r.status == Status.IN_CALL:
            return True
        self._touch(r, Status.IN_CALL)
        self.log(r, f"Picked up (attempt {attempt}).", "info")
        watchdog = 150 if r.channel == "twilio" else 90
        self._schedule(rid, "ring", watchdog, self.no_answer, rid, attempt, "call ended without an answer")
        return True

    async def respond(self, rid: int, attempt: int, reading: CallReading) -> tuple[str, bool]:
        r = self.residents.get(rid)
        if r is None:
            return scripts.CALLBACK["en"], False
        lang = scripts.lang(r.lang)
        if attempt != r.attempts or r.status not in LIVE:
            return scripts.CALLBACK[lang], False
        if r.status == Status.CALLING:
            self.answered(rid, attempt)

        heard = reading.quote or "(nothing)"
        self.log(r, f"Heard: “{heard}” ({reading.engine or 'unknown'})", "speech")

        if reading.answer == Answer.UNCLEAR:
            r.unclear_count += 1
            if r.unclear_count >= 2:
                self._cancel(rid, "ring")
                self._cancel(rid, "auto")
                r.reading = reading
                self._touch(r, Status.NEEDS_CALLBACK)
                self.log(r, "Could not understand twice. A person needs to call back.", "warn")
                return scripts.CALLBACK[lang], False
            r.updated = time.time()
            return scripts.ASK_AGAIN[lang], True

        self._cancel(rid, "ring")
        self._cancel(rid, "auto")
        status = Status(reading.answer.value)
        r.reading = reading
        self._touch(r, status)
        note = reading.responder_note or reading.quote
        self.log(r, f"{_LABEL[status]}. {note}".strip(), _KIND_FOR[status])
        await self._text_family(r)
        return scripts.CONFIRM[reading.answer][lang], False

    # ------------------------------------------------------------------ autopilot

    async def _autopilot(self, rid: int, attempt: int, step) -> None:
        r = self.residents[rid]
        if attempt != r.attempts:
            return
        if step == "decline":
            await self.no_answer(rid, attempt, reason="declined")
            return
        if r.status != Status.CALLING:
            return  # a human answered on /phone first, or the call already ended
        if not self.answered(rid, attempt):
            return
        for utterance in step:
            await asyncio.sleep(random.uniform(1.5, 3))
            if attempt != r.attempts or r.status != Status.IN_CALL:
                return
            reading = digits_reading(utterance) if utterance.strip().isdigit() else None
            if reading is None:
                reading = await classify_text(utterance, self.settings.gemini_model, self.settings.gemini_timeout,
                                              api_key=self.settings.gemini_api_key)
            _, keep_listening = await self.respond(rid, attempt, reading)
            if not keep_listening:
                return
        await self.no_answer(rid, attempt, reason="hung up without a clear answer")

    # ------------------------------------------------------------------ family

    async def _text_family(self, r: Resident) -> None:
        if not r.contact_name:
            return
        who = f"{r.contact_name} ({r.contact_relation})" if r.contact_relation else r.contact_name
        quote = r.reading.quote if r.reading else ""
        body = scripts.family_text(r.status.value, r.first, quote=quote, n=r.attempts)
        if self.twilio is not None and self.settings.send_sms and r.contact_phone:
            try:
                await asyncio.to_thread(self.twilio.send_sms, r.contact_phone, body)
                r.family_notified = f"Texted {who}"
                self.log(r, f"Texted {who}.", "family")
            except Exception as exc:  # noqa: BLE001
                r.family_notified = f"Text to {who} failed"
                self.log(r, f"Text to {who} failed: {exc}", "error")
        else:
            r.family_notified = f"Texted {who} (simulated)"
            self.log(r, f"Texted {who} (simulated): {body}", "family")

    # ------------------------------------------------------------------ views

    def ringing_sim(self) -> list[Resident]:
        return [r for r in self.residents.values() if r.channel == "sim" and r.status in LIVE]

    def snapshot(self) -> dict:
        rows = []
        counts: dict[str, int] = {}
        unaccounted = 0
        for r in self.residents.values():
            s, why = score(r)
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
            if r.status in UNACCOUNTED:
                unaccounted += 1
            rows.append({
                "id": r.id, "name": r.name, "first": r.first, "age": r.age, "address": r.address, "lang": r.lang,
                "status": r.status.value, "attempts": r.attempts, "channel": r.channel, "score": s, "why": why,
                "reading": r.reading.model_dump(mode="json") if r.reading else None,
                "family": r.family_notified, "updated": r.updated, "real_phone": bool(r.phone),
            })
        rows.sort(key=lambda x: (-x["score"], x["name"]))
        return {
            "total": len(rows),
            "unaccounted": unaccounted,
            "done": self.started_at is not None and unaccounted == 0,
            "started_at": self.started_at,
            "max_attempts": self.settings.max_attempts,
            "twilio": self.twilio is not None,
            "gemini": bool(self.settings.gemini_ready),
            "autopilot": self.autopilot,
            "counts": counts,
            "residents": rows,
            "events": list(self.events[-200:]),
        }
