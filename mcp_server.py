"""Headcount MCP server for VoiceOS.

Lets a responder ask out loud: "who still needs help?" Every tool returns short
sentences meant to be spoken. Talks only to the Headcount HTTP API, never to the
engine directly.

Run:  python3 mcp_server.py           (stdio transport, launched by VoiceOS)
Env:  HEADCOUNT_URL (default http://localhost:8000)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

try:  # mcp 1.x, what the VoiceOS guide uses
    from mcp.server.fastmcp import FastMCP as Server
except ModuleNotFoundError:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as Server

BASE = os.getenv("HEADCOUNT_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 5

mcp = Server("headcount")

DOWN = "I can't reach the Headcount server right now. Check that it is running."

UNACCOUNTED = {"PENDING", "CALLING", "IN_CALL", "RETRY_WAIT"}
NEEDS_HELP = ["WELFARE_CHECK", "NEEDS_MEDICAL", "NEEDS_RIDE", "NEEDS_CALLBACK", "STAYING"]

STATUS_WORDS = {
    "PENDING": "not called yet",
    "CALLING": "being called right now",
    "IN_CALL": "on the phone right now",
    "RETRY_WAIT": "didn't answer, and will be called again shortly",
    "OUT": "out and safe",
    "NEEDS_RIDE": "needs a ride out",
    "NEEDS_MEDICAL": "needs medical help",
    "STAYING": "says they are staying",
    "NEEDS_CALLBACK": "answered but wasn't clear, so a person needs to call back",
    "WELFARE_CHECK": "never answered, so a person needs to go to the door",
}


class ServerDown(Exception):
    pass


def _request(method: str, path: str) -> dict:
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
        raise ServerDown(str(exc)) from exc


def _n(count: int, one: str, many: str) -> str:
    """'1 needs a ride' / '3 need a ride'."""
    return f"{count} {one if count == 1 else many}"


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _clean_note(note: str, status_words: str) -> str:
    """Drop note sentences that only repeat the status we already said ('Needs a ride out.')."""
    kept = [x.strip() for x in (note or "").split(".") if x.strip() and x.strip().lower() not in status_words.lower()]
    return ". ".join(kept) + "." if kept else ""


def _quote(reading: dict) -> str:
    """Their words, unless it was a keypad press (nothing to quote)."""
    q = (reading.get("quote") or "").strip()
    if not q or reading.get("engine") == "keypad" or q.startswith("("):
        return ""
    return q


def _status_sentence(state: dict) -> str:
    total = state.get("total", len(state.get("residents", [])))
    counts = state.get("counts", {}) or {}
    if not state.get("started_at"):
        return f"The evacuation calls haven't started yet. {_n(total, 'resident is', 'residents are')} on the list."

    out = counts.get("OUT", 0)
    first = f"{out} of {total} {'is' if out == 1 else 'are'} out and safe."
    parts = [
        _n(counts.get("NEEDS_MEDICAL", 0), "needs medical help", "need medical help"),
        _n(counts.get("NEEDS_RIDE", 0), "needs a ride", "need a ride"),
        _n(counts.get("WELFARE_CHECK", 0), "needs a welfare check", "need a welfare check"),
    ]
    if counts.get("NEEDS_CALLBACK", 0):
        parts.append(_n(counts["NEEDS_CALLBACK"], "needs a callback", "need a callback"))
    if counts.get("STAYING", 0):
        parts.append(_n(counts["STAYING"], "is staying put", "are staying put"))
    unaccounted = state.get("unaccounted")
    if unaccounted is None:
        unaccounted = sum(counts.get(s, 0) for s in UNACCOUNTED)
    parts.append(_n(unaccounted, "is still being reached", "are still being reached"))
    sentence = f"{first} {_join(parts)}."
    if state.get("done"):
        sentence += " Every resident is accounted for or has a responder on the way."
    return sentence


@mcp.tool()
def evacuation_status() -> str:
    """Spoken summary of the evacuation: how many residents are out, need help, or are still being reached."""
    try:
        return _status_sentence(_request("GET", "/api/state"))
    except ServerDown:
        return DOWN


@mcp.tool()
def who_still_needs_help() -> str:
    """The top residents who still need a responder (welfare check, medical, ride, callback, or staying), highest priority first, with address and what to do."""
    try:
        state = _request("GET", "/api/state")
    except ServerDown:
        return DOWN
    if not state.get("started_at"):
        return "The evacuation calls haven't started yet, so nobody has been flagged."
    # residents arrive sorted highest priority first
    flagged = [r for r in state.get("residents", []) if r.get("status") in NEEDS_HELP][:8]
    if not flagged:
        still = state.get("unaccounted", 0)
        if still:
            return f"Nobody has been flagged yet. {_n(still, 'resident is', 'residents are')} still being reached."
        return "Nobody needs help right now. Every resident is out and safe."
    lines = [f"{_n(len(flagged), 'resident needs', 'residents need')} help."]
    for r in flagged:
        reading = r.get("reading") or {}
        note = reading.get("responder_note") or ""
        if r.get("status") == "WELFARE_CHECK":
            note = note or f"No answer after {r.get('attempts', 0)} calls. Send a person."
        words = STATUS_WORDS.get(r.get("status"), r.get("status", "").lower())
        line = f"{r.get('name', 'Unknown')} at {r.get('address', 'unknown address')}: {words}."
        note = _clean_note(note, words)
        if note:
            line += f" {note}"
        lines.append(line)
    return " ".join(lines)


@mcp.tool()
def resident_status(name: str) -> str:
    """Look up one resident by name (partial match is fine) and say their status, call attempts, what they said, and whether family was told."""
    try:
        state = _request("GET", "/api/state")
    except ServerDown:
        return DOWN
    q = (name or "").strip().lower()
    if not q:
        return "Tell me the resident's name."
    matches = [r for r in state.get("residents", []) if q in r.get("name", "").lower()]
    if not matches:
        return f"I couldn't find a resident named {name}."
    if len(matches) > 1:
        names = _join([r.get("name", "") for r in matches[:5]])
        return f"{len(matches)} residents match {name}: {names}. Which one?"
    r = matches[0]
    attempts = r.get("attempts", 0)
    words = STATUS_WORDS.get(r.get("status"), str(r.get("status")).lower())
    parts = [
        f"{r.get('name')}, {r.get('age')}, at {r.get('address')}, {words}.",
        f"{_n(attempts, 'call attempt', 'call attempts')} so far.",
    ]
    reading = r.get("reading") or {}
    quote = _quote(reading)
    if quote:
        parts.append(f'They said: "{quote}"')
    elif reading.get("engine") == "keypad":
        parts.append("They answered with the keypad.")
    note = _clean_note(reading.get("responder_note", ""), words)
    if note:
        parts.append(f"Note: {note}")
    family = r.get("family") or ""
    parts.append(f"{family.rstrip('.')}." if family else "Family hasn't been notified yet.")
    return " ".join(parts)


@mcp.tool()
def system_check() -> str:
    """Say whether Headcount is ready: server up, Gemini on or off, real phone calls on or simulated, autopilot."""
    try:
        h = _request("GET", "/api/health")
    except ServerDown:
        return DOWN
    if not h.get("ok"):
        return "The Headcount server answered but says it isn't ready."
    gemini = "Gemini speech understanding is on" if h.get("gemini") else "Gemini is off, so answers are read with keywords and the keypad"
    twilio = "real phone calls are on" if h.get("twilio") else "phone calls are simulated"
    auto = "Autopilot is on." if h.get("autopilot") else "Autopilot is off."
    return f"Headcount is running. {gemini}, and {twilio}. {auto}"


@mcp.tool()
def start_evacuation_calls() -> str:
    """Start the evacuation campaign. This PLACES REAL PHONE CALLS to every resident mapped to a real number (and texts their families); everyone else is simulated. Confirm with the user before running."""
    try:
        resp = _request("POST", "/api/start")
    except ServerDown:
        return DOWN
    if resp.get("already_running"):
        return "The evacuation calls are already running. Ask me for the status anytime."
    if resp.get("ok"):
        return "Starting the evacuation calls now. Ask me for the status anytime."
    return "The server didn't confirm the start. Check the board."


if __name__ == "__main__":
    mcp.run(transport="stdio")
