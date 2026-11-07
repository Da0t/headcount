#!/usr/bin/env python3
"""Preflight: is this laptop ready to demo Headcount?

    python scripts/preflight.py          # free: no Gemini call
    python scripts/preflight.py --live   # also makes ONE Gemini call (uses quota)

- Reports which settings are set (never prints their values).
- With --live only: makes ONE Gemini call (classify_text("we are out")) and reports latency.
- Checks that Twilio credentials authenticate, read-only. It never places a call or sends a text.
- Exits 1 if there is no Gemini key, or (with --live) the Gemini call fails; 0 otherwise. Twilio problems are warnings: the demo runs simulated.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # so .env and residents_phones.json resolve from the repo root

from app.classify import classify_text  # noqa: E402  (loads .env via app.config)
from app.config import load_settings  # noqa: E402
from app.models import Answer  # noqa: E402

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "


def line(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}")


def check_settings(s) -> None:
    print("Settings (values hidden):")
    secret = {
        "GEMINI_API_KEY": s.gemini_api_key,
        "TWILIO_ACCOUNT_SID": s.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": s.twilio_auth_token,
        "TWILIO_API_KEY_SID": s.twilio_api_key_sid,
        "TWILIO_API_KEY_SECRET": s.twilio_api_key_secret,
        "TWILIO_FROM_NUMBER": s.twilio_from_number,
        "PUBLIC_BASE_URL": s.public_base_url,
    }
    for name, val in secret.items():
        line(OK if val else WARN, f"{name:24} {'set' if val else 'not set'}")
    # non-secret settings are safe to show
    print(f"         GEMINI_MODEL={s.gemini_model}  timeout={s.gemini_timeout:g}s  TWILIO_VALIDATE={int(s.twilio_validate)}"
          f"  SEND_SMS={int(s.send_sms)}  AUTOPILOT={int(s.autopilot)}")
    print(f"         stagger={s.stagger:g}s  ring={s.ring_timeout:g}s  retry_gap={s.retry_gap:g}s"
          f"  max_attempts={s.max_attempts}")
    if s.public_base_url and (not s.public_base_url.startswith("https://") or s.public_base_url.endswith("/")):
        line(WARN, "PUBLIC_BASE_URL should be https:// with no trailing slash, or Twilio signatures will not match")
    phones = Path(s.phones_file)
    if phones.exists():
        try:
            n = len(json.loads(phones.read_text(encoding="utf-8")) or {})
            line(OK, f"{s.phones_file}: {n} resident(s) mapped to real phones")
        except Exception as exc:  # noqa: BLE001
            line(FAIL, f"{s.phones_file} is not valid JSON: {exc}")
    else:
        line(OK, f"{s.phones_file} not present: every resident is simulated")


def check_gemini(s, live: bool) -> bool:
    print("\nGemini:")
    if not s.gemini_ready:
        line(FAIL, "GEMINI_API_KEY not set. Speech would fall back to keywords.")
        return False
    if not live:
        line(OK, f"key set, model {s.gemini_model}. Live call skipped (run with --live to spend one request).")
        return True
    t0 = time.perf_counter()
    reading = asyncio.run(classify_text("we are out", s.gemini_model, s.gemini_timeout, api_key=s.gemini_api_key))
    ms = (time.perf_counter() - t0) * 1000
    if not reading.engine.startswith("Gemini"):
        line(FAIL, f"Gemini call fell back after {ms:.0f} ms: {reading.engine}")
        return False
    if reading.answer != Answer.OUT:
        line(WARN, f"Gemini answered {reading.answer.value} for 'we are out' (expected OUT), {ms:.0f} ms")
        return True
    tag = OK if ms < s.gemini_timeout * 1000 * 0.75 else WARN
    line(tag, f"{reading.engine}: 'we are out' -> OUT in {ms:.0f} ms (timeout {s.gemini_timeout:g}s)")
    return True


def check_twilio(s) -> None:
    print("\nTwilio (read-only, no calls or texts):")
    if not s.twilio_account_sid:
        line(WARN, "TWILIO_ACCOUNT_SID not set: real calls off, demo runs simulated")
        return
    if s.twilio_api_key_ready:
        user, pw, how = s.twilio_api_key_sid, s.twilio_api_key_secret, "API key"
    elif s.twilio_auth_token:
        user, pw, how = s.twilio_account_sid, s.twilio_auth_token, "auth token"
    else:
        line(WARN, "no TWILIO_AUTH_TOKEN or API key pair: real calls off")
        return
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client

    client = Client(user, pw, s.twilio_account_sid)
    try:
        acct = client.api.v2010.accounts(s.twilio_account_sid).fetch()
        line(OK, f"{how} authenticates; account status {acct.status}, type {acct.type}")
    except TwilioRestException as exc:
        if exc.code == 70004:  # Twilio sends 401 + 70004 for "authenticated, but this key may not read that"
            line(OK, f"{how} authenticates (restricted key: account read not permitted, code 70004)")
        elif exc.status == 401:
            line(FAIL, f"{how} rejected (401, code {exc.code}): check the SID/secret pair and the account SID")
            return
        elif exc.status == 403:
            line(OK, f"{how} authenticates (403: account read not permitted)")
        else:
            line(WARN, f"account check returned {exc.status} {exc.code}: {exc.msg}")
    except Exception as exc:  # noqa: BLE001
        line(WARN, f"could not reach Twilio: {exc}")
        return
    if s.twilio_from_number and not re.match(r"^\+[1-9]\d{7,14}$", s.twilio_from_number):
        line(WARN, "TWILIO_FROM_NUMBER is not a full E.164 number (like +16195550100): the server keeps calls OFF")
    elif s.twilio_from_number:
        try:
            nums = client.incoming_phone_numbers.list(phone_number=s.twilio_from_number, limit=1)
            line(OK if nums else WARN, "TWILIO_FROM_NUMBER " + ("is on this account" if nums else "not found on this account"))
        except Exception as exc:  # noqa: BLE001  (list pages raise a plain TwilioException)
            restricted = "70004" in str(exc)
            line(WARN, "could not list numbers: " + ("restricted key lacks that permission (70004)" if restricted
                                                     else str(exc)[:120]))
    if not s.twilio_auth_token and s.twilio_validate:
        line(WARN, "TWILIO_VALIDATE=1 but no auth token: webhook signatures cannot be checked (validation off)")
    live = s.twilio_ready and bool(re.match(r"^\+[1-9]\d{7,14}$", s.twilio_from_number))
    line(OK if live else WARN, "real calls would be " + ("ON for residents in " + s.phones_file if live else
         "OFF (needs account SID, creds, a valid from number, PUBLIC_BASE_URL)"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Check that Headcount is ready to demo.")
    ap.add_argument("--live", action="store_true", help="make ONE real Gemini call (uses free-tier quota)")
    args = ap.parse_args(argv)
    s = load_settings()
    check_settings(s)
    gemini_ok = check_gemini(s, args.live)
    check_twilio(s)
    print("\nResult:", "READY" if gemini_ok else "NOT READY (Gemini)")
    return 0 if gemini_ok else 1


if __name__ == "__main__":
    sys.exit(main())
