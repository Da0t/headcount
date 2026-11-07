# Headcount build brief: Agent 3 of 4, Frontend (dispatch board + phone simulator)

You build the two screens the judges will actually see. They are **plain HTML/CSS/JS files with no build step** (hackathon wifi, any laptop, `uvicorn` serves them). You only talk to the HTTP API in the contract. Build **mock mode first** so you never wait on the backend.

## Design direction
- The board is projected on a screen in a room. It must read from the back row: big numbers, high contrast, dark background by default, one red action button.
- It should feel like a real emergency dispatch tool, calm and serious, not a startup landing page. No gradients, no emoji, no stock icons. One sans-serif for text, one monospace for numbers and tags (for example Inter + IBM Plex Mono from Google Fonts, with system fallbacks so it works offline).
- Status colors (use CSS variables, provide a light theme too):
  - red: WELFARE_CHECK, NEEDS_MEDICAL
  - orange: NEEDS_RIDE
  - violet: NEEDS_CALLBACK
  - amber: STAYING
  - blue: CALLING, IN_CALL (pulse while ringing)
  - gray: PENDING, RETRY_WAIT
  - green: OUT
- Motion with purpose only:
  - a row briefly highlights when its status changes
  - the Unaccounted number counts down
  - the green "done" banner fades in
- Works at 1440px wide (projector) and at phone width (no horizontal scroll).
- Escape every string from the API before inserting it into HTML.

## 1. `app/static/board.html`

### Data
- Poll `GET /api/state` every 1 second.
- **Mock mode:** if the URL has `?mock=1`, never call the API. Instead run a client-side fake campaign over the 10 demo residents from the contract:
  - Start makes rows go CALLING.
  - Over about 40 seconds they resolve to the same outcomes as the seed cast.
  - Walter misses 3 attempts and becomes WELFARE_CHECK.
  - Fake events stream into the feed.
- Use mock mode to build and to rehearse the pitch if the backend dies.

### Layout
- **Header:**
  - "Headcount" wordmark
  - zone name
  - status tags: `PHONE: TWILIO LIVE` or `PHONE: SIM`, and `GEMINI: ON` or `GEMINI: OFF (keywords)`
  - Autopilot toggle (`POST /api/autopilot?on=`)
  - link to `/phone`
  - Reset (`POST /api/reset`)
  - primary red button **"Evacuation order: start calls"** (`POST /api/start`)
- **Counter row:**
  - **Unaccounted** as the biggest number
  - then Welfare check, Need medical, Need a ride, Call back, Staying, Out and safe
- **Done banner** when `done` is true: "Every resident is accounted for or has a responder on the way." This is the pitch's last frame.
- **Ranked list.** The API already sorts it; never re-sort. Each row shows:
  - rank number
  - name and age, plus a "REAL PHONE" chip when `real_phone`
  - address and language
  - `why` chips (age 93, oxygen, bedridden...)
  - `reading.responder_note`
  - `reading.quote` in italics
  - status badge
  - attempt dots like `●●○` (out of `max_attempts`)
  - the family line, for example "Texted Ana (daughter)"
  - small `reading.engine` text (shows the Gemini story)
- **WELFARE_CHECK rows** add a red line: "No answer after N calls. Send a person to {address}."
- **Live feed** column from `events`, newest first, with a timestamp and resident name. Color by kind:
  - alert: red
  - warn: orange
  - good: green
  - family: violet
  - speech: blue
  - error: red italic
- **Footer:** "Demo. Residents are fictional. Headcount is not an official alert system; in an emergency call 911."

## 2. `app/static/phone.html` (a teammate plays residents from a laptop or phone)

- Phone-like dark UI, max width about 420px.
- Polls `GET /api/sim/ringing` every second and shows incoming-call cards for entries with status `CALLING`:
  - resident name
  - "Incoming call · Headcount · attempt N"
  - red Decline and green Answer circles
- **Answer:**
  - `POST /api/sim/{id}/answer?attempt=N`. On 409, refresh the list.
  - Show the returned prompt in a chat bubble and speak it with `speechSynthesis` (lang `es-MX` for Spanish residents, else `en-US`).
- **In-call screen:**
  - keypad buttons 1 (I'm out), 2 (ride), 3 (medical)
  - textarea "Answer in your own words, English or Spanish"
  - **Speak** button: records with MediaRecorder and uploads form field `audio`, so Gemini hears the actual voice
  - **Send** button
  - **Hang up** button: `POST /api/sim/{id}/decline?attempt=N&reason=hung up`
- **Submitting** (`POST /api/sim/{id}/say?attempt=N`, form `text` or file `audio`):
  - It returns `{say, keep_listening, reading}`. Speak `say`.
  - If `keep_listening`, stay in the call with the new bubble.
  - Otherwise show "Heard as: OUT · Gemini (...)" and return to the list after about 4 seconds.
- Show API error `detail` in red (for example, voice needs a Gemini key).
- Note at the top: "Turn Autopilot off on the board to play residents yourself."
- **Mock mode** `?mock=1`:
  - Fake one ringing call.
  - Answer it, type, and get a canned response, with no backend.

## Acceptance checks
- `board.html?mock=1`:
  - Press Start and watch all 10 rows resolve.
  - Walter ends as WELFARE_CHECK.
  - The green banner appears.
  - No console errors.
- Against Agent 2's real server with autopilot on, you get the same result with real data.
- `phone.html`: answer a ringing call, type "ya salimos, estamos bien", and the board shows OUT within 2 seconds.
- Looks right at 1440x900 and 390x844, in dark and light.

## Do not
- Add a framework, bundler, or npm step.
- Edit any Python file. If you need an API change, ask Agent 2.
- Use a real agency's name, seal, or branding.

## Done when
The board in mock mode and live mode both run the full demo loop cleanly on a projector-sized screen, and the phone page can play any resident end to end.

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
