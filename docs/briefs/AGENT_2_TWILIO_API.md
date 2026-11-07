# Headcount build brief: Agent 2 of 4, Twilio + API server

You build the server and the real phone calls: FastAPI app, every HTTP route in the contract, Twilio outbound calls with speech + keypad Gather, status callbacks, signature validation, family SMS, and the phone-simulator endpoints. Agent 1 owns the engine and classifier; until they land, code against the interfaces in the contract with a small fake engine in your tests.

## Your job

### 1. `app/twilio_voice.py`
```python
class TwilioClient:            # passed into Engine(..., twilio=TwilioClient(settings))
    def place_call(self, r, attempt) -> str:
        client.calls.create(
            to=r.phone, from_=TWILIO_FROM_NUMBER,
            url=f"{PUBLIC_BASE_URL}/twilio/voice/{r.id}?attempt={attempt}", method="POST",
            status_callback=f"{PUBLIC_BASE_URL}/twilio/status/{r.id}?attempt={attempt}", status_callback_method="POST",
            timeout=int(ring_timeout))          # Twilio stops ringing after this; final status hits the callback
    def send_sms(self, to, body) -> str: client.messages.create(to=to, from_=TWILIO_FROM_NUMBER, body=body)

def prompt_twiml(r, attempt, n, base) -> str
    # VoiceResponse with Gather(input="speech dtmf", num_digits=1, timeout=7, speech_timeout="auto",
    #   language=LANG_CODE[r.lang], action=f"{base}/twilio/gather/{r.id}?attempt={attempt}&n={n}",
    #   method="POST", action_on_empty_result=True) containing Say(PROMPT if n == 1 else ASK_AGAIN, language=...)
def say_twiml(text, lang) -> str            # Say + Hangup
def signature_ok(settings, path_and_query, params, signature) -> bool
    # if not TWILIO_VALIDATE or no token: True
    # else RequestValidator(token).validate(PUBLIC_BASE_URL + path_and_query, params, signature)
```
Escape the `&` in the action URL properly (the twilio library does this when you pass `action=`).

### 2. `app/main.py`
Module-level: `settings = load_settings()`; build `TwilioClient` only if `settings.twilio_ready` (log a clear warning if Twilio creds exist but PUBLIC_BASE_URL or the from number is missing); `engine = Engine(settings, load_residents(settings), twilio)`; `app = FastAPI()`.
- Pages and dispatch API exactly as in the contract (`/api/state` adds `"zone": ZONE`; `/api/autopilot` flips `settings.autopilot`).
- Simulator routes:
  - `GET /api/sim/ringing`: from `engine.ringing_sim()`, include the localized prompt.
  - `POST /api/sim/{rid}/answer`: `engine.answered`, 409 if it returns False, else `{"say": prompt}`.
  - `POST /api/sim/{rid}/decline`: `await engine.no_answer(rid, attempt, reason)`.
  - `POST /api/sim/{rid}/say`: form `text` or file `audio`. Audio goes to `classify_audio` (400 with the message if there's no Gemini key); text goes to `classify_text`. Log what they said (`kind="speech"`), then return `engine.respond(...)` as `{"say", "keep_listening", "reading"}`.
- Twilio webhooks (every one starts by reading the form and checking `signature_ok`; 403 and a log line telling them to fix PUBLIC_BASE_URL or set TWILIO_VALIDATE=0):
  - `/twilio/voice/{rid}`: `engine.answered(rid, attempt)` then return `prompt_twiml(n=1)`.
  - `/twilio/gather/{rid}`: `Digits` goes to `digits_reading` (unknown digit means UNCLEAR). `SpeechResult` gets logged and goes to `classify_text`. Neither (silence): if n < 2 re-ask with `prompt_twiml(n=2)`, else `await engine.no_answer(rid, attempt, "answered but said nothing")` and say RETRY_SOON. Otherwise `say, keep = await engine.respond(...)`: keep means `prompt_twiml(n=2)`, else `say_twiml(say)`.
  - `/twilio/status/{rid}`: map CallStatus `no-answer`, `busy`, `failed`, `canceled`, `completed` to a reason and call `engine.no_answer` (the engine ignores it if they already answered). Return 204.
- Twilio waits about 15 seconds for a webhook reply; the classifier already caps Gemini at HEADCOUNT_GEMINI_TIMEOUT (6s) and falls back to keywords.

### 3. `.env.example` and `residents_phones.example.json`
All env vars from the contract with comments. Add `.env` and `residents_phones.json` to `.gitignore`.

### 4. Run book you must verify yourself (then hand to Agent 4 for the README)
1. Twilio console: buy or use a voice-capable number (TWILIO_FROM_NUMBER).
2. **Trial accounts** can only call and text **Verified Caller IDs**: verify each teammate's phone in the console first. Trial calls also play a "press any key" preamble before your TwiML; tell the person answering to press a key. Upgrading (about $20) removes both limits.
3. Tunnel so Twilio can reach the laptop: `cloudflared tunnel --url http://localhost:8000` (no account needed) or `ngrok http 8000`. Put the https URL in PUBLIC_BASE_URL **exactly**, no trailing slash. The URL changes every restart; update `.env` and restart uvicorn each time.
4. Map 2 to 3 residents to teammates' phones in `residents_phones.json` (Maria in Spanish is the best real call). Leave autopilot on for the rest.
5. `uvicorn app.main:app --port 8000`, open the board, click Start. The phones ring within a few seconds.
6. If Twilio misbehaves on stage: remove `residents_phones.json` and restart. Everything still runs simulated.

## Acceptance tests (`tests/test_twilio_webhooks.py`, FastAPI TestClient, TWILIO_VALIDATE=0 unless stated)
- Voice webhook for a Spanish resident returns `<Gather` with `language="es-MX"` and an action URL containing `attempt=1&amp;n=1`; resident becomes IN_CALL.
- Gather with `Digits=1` sets OUT and returns Say + Hangup; a later `CallStatus=completed` leaves it OUT.
- Gather with `SpeechResult="My wife is in a wheelchair, we need help getting out"` sets NEEDS_RIDE with mobility_help.
- Silence at n=1 re-asks with n=2; silence at n=2 sets RETRY_WAIT.
- `CallStatus=no-answer` sets RETRY_WAIT.
- With validation on: wrong signature returns 403; a signature from `RequestValidator(token).compute_signature(url, params)` passes.

## Do not
- Edit engine, classifier, priority, models, UI, or MCP files.
- Call real numbers that haven't agreed to it. Demo only to consenting teammates.

## Done when
Tests pass and one real end-to-end call works: a teammate's phone rings, they say "ya salí, estoy bien", the board shows OUT, and the family contact gets a "Headcount demo:" text.

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
