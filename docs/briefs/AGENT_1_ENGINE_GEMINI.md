# Headcount build brief: Agent 1 of 4, Engine + Gemini

You build the brain: the data model, the call state machine, the retry ladder, priority ranking, the Gemini classifier with a keyword fallback, the bilingual call scripts, and the demo residents. No web server, no Twilio code, no HTML. Agents 2, 3, and 4 build on your interfaces, so **ship `models.py`, `scripts.py`, and `classify.py` first (within ~30 minutes)**, then the engine.

## Your job

### 1. `app/config.py`
`load_settings(**overrides) -> Settings` reading the env vars in the contract (use `python-dotenv` if installed). Properties: `twilio_ready` (sid, token, from number, and PUBLIC_BASE_URL all set) and `gemini_ready` (GEMINI_API_KEY or GOOGLE_API_KEY set). Overrides let tests shrink timers to fractions of a second.

### 2. `app/models.py`
Exactly the data model in the contract. `CallReading` field descriptions matter: they are the instructions Gemini sees through structured output.

### 3. `app/scripts.py`
English and Spanish text for: the opening prompt (offers free speech or keypad 1 out, 2 ride, 3 medical), ask again, confirmations per answer (ride and medical confirmations add "if anyone is in danger right now, hang up and call 911"), human callback, "we'll try again shortly", family texts (OUT includes their words; WELFARE_CHECK says "we could not reach {first} after {n} calls, a responder is being sent").

### 4. `app/classify.py`
- `classify_text`: if a Gemini key is set, call Gemini in a thread (`asyncio.to_thread`) wrapped in `asyncio.wait_for(timeout)`. Use `google-genai`: `client.models.generate_content(model=..., contents=[PROMPT, text], config=GenerateContentConfig(response_mime_type="application/json", response_schema=CallReading, temperature=0))`, read `resp.parsed`. On **any** exception or timeout, fall back to `keyword_classify` and set `engine` to say why. A phone call must never hang waiting on AI.
- Prompt rules for Gemini: use only what they said, never guess, UNCLEAR if unsure; English or Spanish, possibly a noisy phone transcription; NEEDS_MEDICAL beats NEEDS_RIDE; cannot walk but not hurt is NEEDS_RIDE; refusing to leave is STAYING; `responder_note` is one English line a firefighter can act on.
- `classify_audio`: same, but sends the audio bytes as `types.Part.from_bytes(data, mime_type)`. Gemini only.
- `keyword_classify` (EN + ES). Order: MEDICAL ("i fell", "hurt", "can't breathe", "me caí", "no puedo respirar", "ambulancia") then STAYING ("not leaving", "no me voy", "me quedo") then OUT ("we're out", "already left", "ya salimos", "estamos bien") **unless** a hard ride signal is present, then RIDE ("no car", "can't walk", "wheelchair", "can't get out", "no tengo carro", "silla de ruedas", "no me puedo levantar"), else UNCLEAR. A clear "I don't need help, I'm out" must be OUT; "I can't get out" must be RIDE. Also extract mobility_help, oxygen/CPAP/dialysis, pets, "my wife/husband" as people_with_them=1, and build a responder_note.
- `digits_reading`: 1 OUT, 2 NEEDS_RIDE, 3 NEEDS_MEDICAL.

### 5. `app/priority.py`
`score(r) -> (int, why: list[str])` = status weight x vulnerability multiplier. Weights: WELFARE_CHECK 100, NEEDS_MEDICAL 95, NEEDS_RIDE 75, NEEDS_CALLBACK 65, STAYING 55, CALLING/IN_CALL/RETRY_WAIT 40, PENDING 35, OUT 0. Multiplier starts at 1.0: age 85+ +0.4 (else 75+ +0.25), oxygen (profile or mentioned on call) +0.4, bedridden +0.5 (else mobility, profile or call, +0.3), lives alone +0.2, hard of hearing +0.15, +0.1 per extra person with them (max 3). `why` lists each factor so the board can show it.

### 6. `app/engine.py` (the state machine)
- One pending asyncio task per (resident, kind) with kinds `dial`, `ring`, `auto`. Scheduling a kind cancels the previous one of that kind (never cancel the task you are running in). Wrap every task body so an exception is logged, never crashes the campaign.
- `start()`: reset, log "Evacuation order received", schedule `_dial` for each resident at `i * stagger`.
- `_dial(rid)`: only from PENDING or RETRY_WAIT. attempts += 1, status CALLING.
  - If `self.twilio` and the resident has a real phone: channel "twilio", `await asyncio.to_thread(twilio.place_call, r, attempt)`. If it raises, treat as `no_answer(reason="call could not be placed")`. Schedule a safety-net `ring` task at `ring_timeout + 120` in case Twilio's status callback never arrives.
  - Else: channel "sim", schedule `ring` at `ring_timeout` that calls `no_answer`. If autopilot is on and the resident has a `sim_script` step for this attempt that isn't "no_answer", schedule `auto` in 2.5 to 6 seconds.
- `no_answer(rid, attempt, reason)`: ignore unless `attempt == r.attempts` and status is CALLING or IN_CALL. Cancel `ring`. If attempts >= max: WELFARE_CHECK, log alert "No answer after N calls. Welfare check: send a person to {address}", text family. Else RETRY_WAIT and schedule `_dial` after `retry_gap`.
- `answered(rid, attempt)`: stale attempt returns False; already IN_CALL returns True; CALLING becomes IN_CALL and schedules a `ring` watchdog (150s twilio, 90s sim) so a call left hanging still counts as missed.
- `respond(rid, attempt, reading)`: stale returns (CALLBACK text, False). UNCLEAR: unclear_count += 1; at 2 set NEEDS_CALLBACK and return CALLBACK; otherwise return (ASK_AGAIN, True). Any real answer: cancel `ring`, store reading, set status to the same-named Status, log it, text family, return (CONFIRM text, False).
- `_autopilot(rid, attempt, step)`: "decline" calls `no_answer(reason="declined")`. Otherwise only proceed if status is still CALLING (a human may have answered on /phone first), call `answered`, then say each utterance 1.5 to 3 seconds apart through `classify_text` and `respond`, stopping when keep_listening is False. If utterances run out, `no_answer(reason="hung up without a clear answer")`.
- Family texts: if `twilio` and `send_sms` and `contact_phone`: send via `to_thread(twilio.send_sms, ...)`, set `family_notified = "Texted Ana (daughter)"`; else `"Texted Ana (daughter) (simulated)"` and log the body. Skip residents with no contact.
- `snapshot()` exactly matches `/api/state` in the contract (minus `zone`), residents sorted by score desc then name.

### 7. `app/seed.py`
`ZONE = "Alpine (demo zone)"` and 10 fictional residents with scripts that exercise every path, plus `load_residents(settings)` that copies them and applies `residents_phones.json` (phone, contact_phone, optional name/lang override). Suggested cast:
1. Maria Gonzalez, 81, es, oxygen, lives alone, contact Ana (daughter): no answer, then "Sí, aquí estoy. No tengo carro y uso oxígeno. Necesito que me ayuden a salir." (ride)
2. Walter Briggs, 87, bedridden, lives alone, contact Linda (niece): never answers (welfare check)
3. Dorothy Chen, 76, contact Kevin (son): "We're out, we're at my son's place in El Cajon." (out)
4. Frank Russo, 84, mobility: "My wife's in a wheelchair and I can't drive anymore. We need help getting out. We have a dog too." (ride, +1 person, dog)
5. James Whitaker, 79, hard of hearing: declines, then "I'm not leaving. I've got four horses here." (staying)
6. Rosa Medina, 90, es, mobility, lives alone: "Me caí en la cocina y no me puedo levantar." (medical)
7. George Patel, 72: presses 1 (out)
8. Betty Lawson, 85, lives alone: "Hmm? Who is this?" then "Oh, the fire. Yes, I already left. I'm at the shelter at the high school." (unclear then out)
9. Luis Herrera, 68, es: no answer, then "Ya salimos todos, estamos bien." (out)
10. Edna Morales, 93, oxygen, bedridden, lives alone: no answer, then "My caregiver didn't come today. I can't get out of bed by myself." (ride)

## Acceptance tests (pytest, timers shrunk via `load_settings(stagger=0, ring_timeout=0.15, retry_gap=0.05, autopilot=False)`)
- Never answers: WELFARE_CHECK after exactly 3 attempts, family notified.
- Answers on attempt 2 with OUT: status OUT, attempts 2, stays OUT after old timers would have fired.
- Two UNCLEAR answers: second returns keep_listening False and status NEEDS_CALLBACK.
- `no_answer` arriving after a real answer (Twilio "completed" callback) changes nothing.
- Autopilot plays out OUT, STAYING, and NEEDS_RIDE scripts correctly (patch `random.uniform` to be tiny).
- Priority: unreached bedridden 93-year-old > needs-ride 84-year-old > OUT (0), and `why` contains "bedridden" and "oxygen".
- Keyword fallback: every seed utterance above classifies as noted; "I don't need help, I'm out already" is OUT; "I can't get out, I have no car" is NEEDS_RIDE.

## Do not
- Put business decisions in the LLM.
- Block the event loop: Gemini and Twilio calls always go through `asyncio.to_thread`.
- Touch `main.py`, `twilio_voice.py`, `static/`, or `mcp_server.py`.

## Done when
`pytest -q` passes with no Gemini key set, and with a key set `await classify_text("mi esposo no puede caminar", ...)` returns NEEDS_RIDE with engine "Gemini (...)". Tell the other agents when `models.py`, `scripts.py`, and `classify.py` are pushed.

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
