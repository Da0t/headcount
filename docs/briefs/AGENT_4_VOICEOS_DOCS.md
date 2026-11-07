# Headcount build brief: Agent 4 of 4, VoiceOS integration + docs + pitch

You build the voice layer for responders and everything a judge reads: the VoiceOS MCP server, README, COPILOT.md template, pitch script, and license. You only talk to the HTTP API in the contract.

## Your job

### 1. `mcp_server.py` (VoiceOS integration; talks to the HTTP API, never to the engine directly)
```python
try:    from mcp.server.fastmcp import FastMCP as Server      # mcp 1.x, what the VoiceOS guide uses
except ModuleNotFoundError: from mcp.server.mcpserver import MCPServer as Server   # mcp 2.x
BASE = os.getenv("HEADCOUNT_URL", "http://localhost:8000")
mcp = Server("headcount")
```
Tools return short sentences meant to be spoken aloud:
- `evacuation_status()`: for example "4 of 10 are out and safe. 1 needs medical help, 3 need a ride, 1 needs a welfare check, and 0 still being reached." Get the plurals right. If the campaign hasn't started, say so.
- `who_still_needs_help()`: the top 8 residents in WELFARE_CHECK, NEEDS_MEDICAL, NEEDS_RIDE, NEEDS_CALLBACK, or STAYING, each with address and responder note.
- `resident_status(name)`: partial, case-insensitive name match. Return status in words, attempts, their quote, and the family line.
- `start_evacuation_calls()`: `POST /api/start`. The docstring must say it places real phone calls for mapped residents, so VoiceOS shows its confirmation before running it.

Use `urllib.request` with a 5-second timeout. If the server is down, return a sentence saying so instead of a traceback. Run with `mcp.run(transport="stdio")`.

VoiceOS setup to document: Settings > Integrations > Custom Integrations > Add, name it Headcount, launch command `python3 /absolute/path/headcount/mcp_server.py`. Then say "who still needs help?"

### 2. `README.md` (replace the stub)
- **The problem:** alerts broadcast into the dark, and nobody closes the loop on who got out. The people most at risk are older adults on landlines who can't use apps.
- **What it does:** calls, understands English or Spanish or the keypad, retries 3 times, then sends a person; live board; family texts.
- **The rule:** Gemini understands, plain tested code decides.
- **Architecture:** a small diagram in a code block.
- **Quick start.**
- **Twilio setup:** use Agent 2's run book.
  - Trial accounts can only call verified numbers and play a press-any-key preamble.
  - Run `cloudflared tunnel --url http://localhost:8000`.
  - PUBLIC_BASE_URL must match the tunnel exactly and changes on every restart.
  - Map residents in `residents_phones.json`.
- **Simulator and mock mode:** `/phone`, `/?mock=1`.
- **VoiceOS setup.**
- **Tests:** `pytest -q`.
- **Safety:** fictional data; consenting teammates only for real calls; not an official alert system; no Gemini Maps grounding (not allowed for emergency response).
- **Built with:** list every framework (MLH rules ask for this).
- **License:** MIT.

### 3. `COPILOT.md`
A template the Copilot teammate fills in **with real entries as they work**:
- table: time, what we asked Copilot, what it did, what we kept or changed
- sections: Learn, Solve, Test, Document
Do not invent entries.

### 4. `PITCH.md` (2 minutes, plus judge Q&A)

**Script:**
- **0:00:** Open on Maria, 81, on oxygen, no car, speaks Spanish, during a Santa Ana evacuation order. The alert reached her phone. Did she get out? Nobody knows.
- **0:20:** The gap. Alerts are one-way. Responders spend hours knocking on doors of people who already left, while the people who can't leave wait.
- **0:40:** Live demo.
  - Press Start. Teammates' phones ring in the room.
  - One answers in Spanish, and the row flips to NEEDS_RIDE with "uses oxygen".
  - The family text arrives on another phone.
  - Walter never answers. After 3 calls the board says "send a person".
  - Ask VoiceOS out loud: "who still needs help?"
- **1:35:** Gemini understands messy speech in two languages. Plain rules decide who gets help, so every call is explainable.
- **1:50:** The green banner. "Every resident is accounted for or has a responder on the way."

**Q&A prep:**
- **SAP:** Who operates it (county emergency services, senior-services nonprofits, assisted-living operators)? What does it save (responder hours not spent door-knocking people who already left)? What's the metric (minutes to account for every resident in a zone)?
- **VoiceOS:** Voice in for residents who can't use apps; voice out for responders through MCP.
- **Why rules, not the LLM:** auditability and trust.
- **Privacy and consent:** opt-in resident lists from partner agencies; data minimization.
- **What's next:** more languages, TTY and relay support for deaf residents, and a pilot with one senior-living community.

### 5. `LICENSE`
MIT, copyright "Headcount contributors". It is already in the repo; keep it.

## Acceptance checks
- With the server running: `python3 -c "import mcp_server as m; print(m.evacuation_status())"` prints a sensible sentence. With the server stopped, it prints a friendly sentence, not a traceback.
- A teammate who has never seen the repo can follow the README to run the demo.
- The pitch reads aloud in under 2 minutes.

## Do not
- Edit `app/` files.
- Imitate a real agency's branding or claim official status.
- Fabricate COPILOT.md content.

---

# Context and shared contract (identical in all four briefs)

## The project

**Headcount** is a phone-first evacuation census for older adults. When an evacuation order goes out, alerts broadcast into the dark and nobody closes the loop on who actually got out. Headcount calls every resident in the zone, understands what they say (English or Spanish, free speech or keypad 1/2/3), retries three times, and if it still can't reach someone it never guesses: it sends a person (WELFARE_CHECK). Responders watch a live, priority-ranked dispatch board. Families get a text the moment their person is accounted for.

Hackathon: AIC at UC San Diego Hack for Humanity (MLH). Submissions close **4:00 PM PST**; aim to submit by 3:45. Prize tracks: Best Overall, Best Use of the Gemini API, Best Use of GitHub Copilot. Judges: 2 from SAP (operations, measurable value), 1 from VoiceOS (voice that triggers actions, MCP), 1 TBD. No hardware: Twilio is a cloud service, phones are just phones.

**Core rule for the whole codebase:** Gemini only understands speech. Plain, tested Python decides everything that matters (retries, welfare checks, priority, who gets a text). Never let an AI call decide who gets help.

## Who owns what

| Agent | Owns these files | Depends on |
|---|---|---|
| 1. Engine + Gemini | `app/config.py`, `app/models.py`, `app/scripts.py`, `app/classify.py`, `app/priority.py`, `app/engine.py`, `app/seed.py`, `tests/test_engine.py`, `tests/test_classify.py` | nothing |
| 2. Twilio + API server | `app/main.py`, `app/twilio_voice.py`, `tests/test_twilio_webhooks.py`, `.env.example`, `residents_phones.example.json` | Agent 1's interfaces below |
| 3. Frontend | `app/static/board.html`, `app/static/phone.html` | Agent 2's HTTP API below (build mock mode first) |
| 4. VoiceOS + docs | `mcp_server.py`, `README.md`, `COPILOT.md`, `PITCH.md`, `LICENSE` | Agent 2's HTTP API below |

Do not edit another agent's files. If the contract must change, tell the other agents first.

## Shared contract (do not change without telling the others)

### Repo layout
```
headcount/
  app/__init__.py  config.py  models.py  scripts.py  classify.py  priority.py  engine.py  seed.py
  app/main.py  app/twilio_voice.py
  app/static/board.html  app/static/phone.html
  mcp_server.py
  tests/
  requirements.txt   # fastapi uvicorn python-multipart google-genai twilio python-dotenv pydantic mcp pytest httpx
```
Run: `uvicorn app.main:app --port 8000`. Python 3.11+.

### Data model (`app/models.py`, Agent 1)
```python
class Status(str, Enum):
    PENDING, CALLING, IN_CALL, RETRY_WAIT,              # unaccounted
    OUT, NEEDS_RIDE, NEEDS_MEDICAL, STAYING,             # answered
    NEEDS_CALLBACK,   # answered but unclear twice: a human calls back
    WELFARE_CHECK     # never reached after max attempts: a person goes to the door
UNACCOUNTED = {PENDING, CALLING, IN_CALL, RETRY_WAIT}

class Answer(str, Enum): OUT, NEEDS_RIDE, NEEDS_MEDICAL, STAYING, UNCLEAR

class CallReading(BaseModel):   # what one resident said, structured
    answer: Answer
    people_with_them: int = 0
    mobility_help: bool = False
    medical_equipment: list[str] = []
    pets: list[str] = []
    where_they_are: str = ""
    quote: str = ""              # their words, in their language
    responder_note: str = ""     # one English line a responder can act on
    engine: str = ""             # "Gemini (model)", "keywords", "keypad"

@dataclass
class Resident:
    id: int; name: str; age: int; address: str
    lang: str = "en"             # "en" | "es"
    oxygen=False; mobility=False; bedridden=False; lives_alone=False; hearing=False
    contact_name=""; contact_relation=""
    phone=""                     # real number: called via Twilio
    contact_phone=""             # real number: family texted via Twilio
    sim_script: list = []        # per attempt: "no_answer" | "decline" | ["utterance", ...]
    # runtime
    status=PENDING; attempts=0; unclear_count=0; reading: CallReading|None=None
    family_notified=""; channel=""  # "twilio" | "sim"
    call_sid=""; updated: float
    first -> str                 # property: first name
    reset_runtime()
```

### Engine interface (`app/engine.py`, Agent 1 implements, Agent 2 calls)
```python
engine = Engine(settings, residents: list[Resident], twilio=None)
    # twilio, if given, has: place_call(r, attempt) -> call_sid ; send_sms(to, body) -> sid   (Agent 2)
engine.residents: dict[int, Resident]
await engine.start()                         # reset, then dial everyone, staggered
engine.reset()
engine.answered(rid, attempt) -> bool        # they picked up; False if stale
await engine.respond(rid, attempt, reading) -> (say_text, keep_listening: bool)
await engine.no_answer(rid, attempt, reason) # ring-out, decline, busy, silence; ignored if stale or already answered
engine.snapshot() -> dict                    # see /api/state below
engine.ringing_sim() -> list[Resident]       # sim residents currently CALLING or IN_CALL
engine.log(resident_or_None, msg, kind)      # kind: info|start|speech|good|warn|alert|family|error
```
`attempt` is the attempt number the call belongs to. Every event carries it so late webhooks from an old call can never overwrite a newer state.

### Classifier (`app/classify.py`, Agent 1 implements, Agent 2 calls)
```python
await classify_text(text, model, timeout) -> CallReading      # Gemini, falls back to keywords on timeout/error
await classify_audio(audio_bytes, mime, model, timeout) -> CallReading   # Gemini only (simulator mic)
digits_reading("1"|"2"|"3") -> CallReading | None             # 1 OUT, 2 NEEDS_RIDE, 3 NEEDS_MEDICAL
```

### Call scripts (`app/scripts.py`, Agent 1)
`PROMPT[lang]` (has `{first}`), `ASK_AGAIN[lang]`, `CONFIRM[Answer][lang]`, `CALLBACK[lang]`, `RETRY_SOON[lang]`, `FAMILY[...]`, `LANG_CODE = {"en": "en-US", "es": "es-MX"}`, `lang(code)`. The call introduces itself as "Headcount, the evacuation check for your neighborhood". It must never claim to be a government agency.

### HTTP API (`app/main.py`, Agent 2 implements, Agents 3 and 4 call)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/` | | board.html |
| GET | `/phone` | | phone.html |
| GET | `/api/state` | | snapshot JSON (below) plus `"zone"` |
| POST | `/api/start` | | `{"ok": true}` starts the campaign |
| POST | `/api/reset` | | `{"ok": true}` |
| POST | `/api/autopilot?on=true\|false` | | `{"autopilot": bool}` |
| GET | `/api/sim/ringing` | | `[{id, name, first, lang, status, attempt, prompt}]` |
| POST | `/api/sim/{rid}/answer?attempt=N` | | `{"say": prompt}` or 409 if no longer ringing |
| POST | `/api/sim/{rid}/decline?attempt=N&reason=declined` | | `{"ok": true}` (also used for hang up) |
| POST | `/api/sim/{rid}/say?attempt=N` | form: `text` OR file `audio` | `{"say", "keep_listening", "reading"}` |
| POST | `/twilio/voice/{rid}?attempt=N` | Twilio form | TwiML (Gather) |
| POST | `/twilio/gather/{rid}?attempt=N&n=1\|2` | Twilio form | TwiML |
| POST | `/twilio/status/{rid}?attempt=N` | Twilio form | 204 |

`/api/state` example:
```json
{
  "zone": "Alpine (demo zone)", "total": 10, "unaccounted": 0, "done": true,
  "started_at": 1762551000.1, "max_attempts": 3, "twilio": true, "gemini": true, "autopilot": true,
  "counts": {"OUT": 4, "NEEDS_RIDE": 3, "NEEDS_MEDICAL": 1, "STAYING": 1, "WELFARE_CHECK": 1},
  "residents": [
    {"id": 2, "name": "Walter Briggs", "first": "Walter", "age": 87, "address": "3 Arnold Way", "lang": "en",
     "status": "WELFARE_CHECK", "attempts": 3, "channel": "sim", "score": 210,
     "why": ["age 87", "bedridden", "lives alone"], "reading": null,
     "family": "Texted Linda (niece) (simulated)", "updated": 1762551040.2, "real_phone": false},
    {"id": 1, "name": "Maria Gonzalez", "first": "Maria", "age": 81, "address": "1420 Tavern Rd", "lang": "es",
     "status": "NEEDS_RIDE", "attempts": 2, "channel": "twilio", "score": 139, "why": ["age 81", "oxygen", "lives alone"],
     "reading": {"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": false, "medical_equipment": ["oxygen"],
                 "pets": [], "where_they_are": "", "quote": "No tengo carro y uso oxígeno.",
                 "responder_note": "No car, uses oxygen. Needs a ride.", "engine": "Gemini (gemini-3.8-flash)"},
     "family": "Texted Ana (daughter)", "updated": 1762551021.9, "real_phone": true}
  ],
  "events": [{"t": 1762551040.2, "rid": 2, "name": "Walter Briggs", "kind": "alert",
              "msg": "No answer after 3 calls. Welfare check: send a person to 3 Arnold Way."}]
}
```
`residents` is already sorted, highest priority first. `done` = campaign started and nobody unaccounted.

### Environment variables
```
GEMINI_API_KEY=            GEMINI_MODEL=gemini-3.8-flash   (if that name errors, use the current Flash model in AI Studio)
TWILIO_ACCOUNT_SID=        TWILIO_AUTH_TOKEN=              TWILIO_FROM_NUMBER=+1...
PUBLIC_BASE_URL=https://<your-tunnel>   # Twilio must reach your laptop
TWILIO_VALIDATE=1          HEADCOUNT_SEND_SMS=1             HEADCOUNT_PHONES=residents_phones.json
HEADCOUNT_STAGGER=2  HEADCOUNT_RING_TIMEOUT=20  HEADCOUNT_RETRY_GAP=15  HEADCOUNT_MAX_ATTEMPTS=3
HEADCOUNT_GEMINI_TIMEOUT=6  HEADCOUNT_AUTOPILOT=1
```
`residents_phones.json` (gitignored): `{"1": {"phone": "+16195550101", "contact_phone": "+16195550102", "name": "optional override"}}`. Mapped residents are called for real; everyone else is simulated.

### House style
- All residents are fictional. Demo SMS start with "Headcount demo:".
- Board footer: not an official alert system; in an emergency call 911.
- Do not use Gemini's Google Maps grounding: it is not permitted for emergency response use.
