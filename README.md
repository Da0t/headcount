# Headcount

**When an evacuation order goes out, Headcount calls every older adult in the zone until each one is accounted for.**

Built at AIC at UC San Diego Hack for Humanity (MLH), November 7, 2026.

## The problem

Evacuation alerts broadcast into the dark. A phone buzzes, a siren sounds, and nobody closes the loop on who actually got out. Responders end up knocking on the doors of people who left hours ago, while the people who can't leave on their own wait. Those people are most often older adults on landlines who can't use apps: no car, on oxygen, in a wheelchair, living alone, sometimes speaking only Spanish.

## What it does

- **Calls every resident** in the zone, staggered, with a real phone call.
- **Understands the answer** in English or Spanish, in their own words ("mi esposo no puede caminar") or with the keypad: 1 = I'm out, 2 = I need a ride, 3 = I need medical help.
- **Retries three times.** If it still can't reach someone, it never guesses: it flags a **welfare check** and sends a person to the door. If someone answers but can't be understood twice, a human calls them back.
- **Live dispatch board** for responders, ranked by priority (age, oxygen, mobility, bedridden, lives alone), with one English line a responder can act on.
- **Family texts** the moment their person is accounted for.
- **Voice for responders** through VoiceOS: ask out loud, "who still needs help?"

## The rule

**Gemini understands. Plain, tested code decides.**

Gemini only turns messy speech into structured facts (answer, people with them, medical equipment, a responder note). Retries, welfare checks, priority, and who gets a text are ordinary Python with tests. No AI call ever decides who gets help, so every decision on the board can be explained. If Gemini is slow or unavailable, the classifier falls back to keywords.

## How Headcount decides

Every call goes through one state machine (`app/engine.py`). Each event carries the attempt number it belongs to, so a late webhook from an old call can never overwrite a newer answer.

```
PENDING ─► CALLING ─► IN_CALL ─► OUT | NEEDS_RIDE | NEEDS_MEDICAL | STAYING
              │           │
              │           └─ unclear twice ─► NEEDS_CALLBACK  (a person calls back)
              └─ no answer / declined ─► RETRY_WAIT ─► CALLING ...
                                after 3 calls ─► WELFARE_CHECK  (a person goes to the door)
```

**Understanding speech** (`app/classify.py`): Gemini returns a structured `CallReading` (answer, people with them, mobility, medical equipment, pets, where they are, their words, and a one-line responder note). The call never waits on AI: Gemini has a timeout, and on any error or timeout the classifier falls back to English and Spanish keywords. Keypad 1/2/3 skips classification entirely. Using oxygen or other equipment is not by itself a medical emergency: it is recorded (in English, so "oxígeno" shows as "oxygen") and raises priority, but the answer stays what they said. The board shows which engine read each answer: `Gemini (model)`, `keywords (...)` with the reason, or `keypad`.

**Priority** (`app/priority.py`) is plain arithmetic that the board shows next to every resident:

`score = status weight × vulnerability multiplier`

| Status | Weight | | Vulnerability | Adds |
|---|---|---|---|---|
| WELFARE_CHECK | 100 | | age 85+ (or 75+) | +0.4 (+0.25) |
| NEEDS_MEDICAL | 95 | | oxygen, from their profile or said on the call | +0.4 |
| NEEDS_RIDE | 75 | | bedridden (or mobility help) | +0.5 (+0.3) |
| NEEDS_CALLBACK | 65 | | lives alone | +0.2 |
| STAYING | 55 | | hard of hearing | +0.15 |
| calling / retrying | 40 | | each extra person with them (max 3) | +0.1 |
| not yet called | 35 | | | |
| OUT | 0 | | | |

The multiplier starts at 1.0. For example, Walter (87, bedridden, lives alone, never reached) scores 100 × 2.1 = 210 and goes to the top of the board.

**Family texts** go out the moment someone answers, or when a welfare check is called ("we could not reach Walter after 3 calls, a responder is being sent"). Residents without a contact are skipped.

## Architecture

```
                   ┌──────────────── Twilio ────────────────┐
 resident's phone ◄─┤ outbound call, speech + keypad Gather  │
 family's phone   ◄─┤ SMS                                    │
                   └───────────────┬───────────────────────┘
                                   │ webhooks (via tunnel)
                                   ▼
   ┌──────────────────── FastAPI  app/main.py ─────────────────────┐
   │  /twilio/*   /api/*   /api/sim/*   / (board)   /phone (sim)    │
   │                                                                │
   │   classify.py ──► Gemini (speech → CallReading)                │
   │        │          keyword + keypad fallback                    │
   │        ▼                                                       │
   │   engine.py  (state machine: retries, welfare checks, texts)   │
   │   priority.py (who is most at risk)    seed.py (demo zone)     │
   └───────▲──────────────────────────────────────▲─────────────────┘
           │ GET /api/state (polling)             │ HTTP
     board.html / phone.html                mcp_server.py ◄── VoiceOS (stdio MCP)
```

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/Da0t/headcount.git
cd headcount
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add GEMINI_API_KEY (and Twilio settings for real calls)
uvicorn app.main:app --port 8000
```

Open http://localhost:8000 and press **Start**. With no Twilio settings, every resident is simulated and autopilot plays their scripted answers, so the whole demo runs on one laptop.

## Real phone calls with Twilio

1. **Get a number.** In the Twilio console, buy or use a voice-capable number and put it in `TWILIO_FROM_NUMBER`, along with `TWILIO_ACCOUNT_SID` (starts with `AC`) and `TWILIO_AUTH_TOKEN`. You can use an API key instead of the auth token for placing calls and texts: set `TWILIO_API_KEY_SID` (starts with `SK`) and `TWILIO_API_KEY_SECRET`. You still need the account SID either way. Twilio signs its webhooks with the auth token, so with an API key alone, webhook signature checks are skipped. Add the auth token too if you want them.
2. **Trial accounts** can only call and text **Verified Caller IDs**, so verify each teammate's phone in the console first. Trial calls also play a "press any key" message before ours; tell whoever answers to press a key. Upgrading (about $20) removes both limits.
3. **Open a tunnel** so Twilio can reach your laptop:
   ```bash
   cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
   ```
   Put the https URL in `PUBLIC_BASE_URL` **exactly**, with no trailing slash. The URL changes every time the tunnel restarts: update `.env` and restart uvicorn each time. If webhooks return 403, this is almost always why (or set `TWILIO_VALIDATE=0` while debugging).
4. **Map residents to real phones** in `residents_phones.json` (gitignored; copy `residents_phones.example.json`):
   ```json
   {"1": {"phone": "+16195550101", "contact_phone": "+16195550102"}}
   ```
   Mapped residents are called for real and their contact gets real texts. Everyone else stays simulated. Maria (resident 1, Spanish) makes the best real call.
5. `uvicorn app.main:app --port 8000`, open the board, and press **Start**. The phones ring within a few seconds.
6. **If Twilio misbehaves on stage:** delete `residents_phones.json` and restart. Everything still runs simulated.

## Simulator and mock mode

- **`/phone`** is a phone simulator. A teammate can answer any simulated resident's call from a laptop or phone, then type or speak the answer.
- **`/?mock=1`** runs the board entirely in the browser with a fake campaign and no backend. Use it to rehearse, or as a fallback if the server dies.

## VoiceOS (voice for responders)

`mcp_server.py` is an MCP server that reads the same HTTP API as the board. Its tools answer in short spoken sentences:

| Tool | Say something like |
|---|---|
| `evacuation_status` | "What's the evacuation status?" |
| `who_still_needs_help` | "Who still needs help?" |
| `resident_status` | "What's Walter's status?" |
| `start_evacuation_calls` | "Start the evacuation calls." (VoiceOS asks you to confirm, because this places real calls) |

Setup: in VoiceOS, open **Settings > Integrations > Custom Integrations > Add**, name it **Headcount**, and set the launch command to:

```
python3 /absolute/path/to/headcount/mcp_server.py
```

Use the Python that has the requirements installed (for example `/absolute/path/to/headcount/.venv/bin/python`). Set `HEADCOUNT_URL` if the server isn't on `http://localhost:8000`. With the server running, say "who still needs help?" If the server is down, the tools say so instead of failing.

Quick check without VoiceOS:

```bash
python3 -c "import mcp_server as m; print(m.evacuation_status())"
```

## The demo zone

`app/seed.py` holds 10 fictional residents in "Alpine (demo zone)". On autopilot, their scripted answers cover every path:

| Resident | What happens | Ends as |
|---|---|---|
| Maria Gonzalez, 81 (Spanish, oxygen) | misses the first call, then "No tengo carro y uso oxígeno" | NEEDS_RIDE |
| Walter Briggs, 87 (bedridden) | never answers | WELFARE_CHECK |
| Dorothy Chen, 76 | "We're out, we're at my son's place in El Cajon." | OUT |
| Frank Russo, 84 | wife in a wheelchair, can't drive, has a dog | NEEDS_RIDE |
| James Whitaker, 79 (hard of hearing) | declines, then "I'm not leaving. I've got four horses here." | STAYING |
| Rosa Medina, 90 (Spanish) | "Me caí en la cocina y no me puedo levantar." | NEEDS_MEDICAL |
| George Patel, 72 | presses 1 | OUT |
| Betty Lawson, 85 | "Who is this?", then "I already left. I'm at the shelter." | OUT |
| Luis Herrera, 68 (Spanish) | misses the first call, then "Ya salimos todos, estamos bien." | OUT |
| Edna Morales, 93 (oxygen, bedridden) | misses the first call, then "I can't get out of bed by myself." | NEEDS_RIDE |

A full simulated run finishes in under a minute with the faster stage timers below: 4 OUT, 3 NEEDS_RIDE, 1 NEEDS_MEDICAL, 1 STAYING, 1 WELFARE_CHECK.

## Configuration

Everything lives in `.env` (see [`.env.example`](.env.example) for every variable, with comments). Nothing is required: with an empty `.env`, Headcount runs fully simulated with keyword classification.

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | none, `gemini-3.5-flash-lite` | Speech understanding (about 1 second per call). Without a key, keywords and keypad only. |
| `HEADCOUNT_GEMINI_TIMEOUT` | 8 | Seconds before falling back to keywords. Twilio waits about 15 seconds for a reply, so keep this well under that. |
| `HEADCOUNT_STAGGER` | 2 | Seconds between first dials |
| `HEADCOUNT_RING_TIMEOUT` | 20 | Seconds a call rings before it counts as missed |
| `HEADCOUNT_RETRY_GAP` | 15 | Seconds before calling a missed resident again |
| `HEADCOUNT_MAX_ATTEMPTS` | 3 | Calls before a welfare check |
| `HEADCOUNT_AUTOPILOT` | 1 | Simulated residents answer on their own (also a toggle on the board) |

For a faster stage demo, try `HEADCOUNT_STAGGER=1 HEADCOUNT_RING_TIMEOUT=8 HEADCOUNT_RETRY_GAP=4`.

Free-tier Gemini keys can return rate-limit errors (429) when many calls land at once, so Headcount sends at most 3 Gemini requests at a time. If a 429 still happens, the call doesn't fail: that answer falls back to keywords, and the board shows `keywords` with the reason.

## Tests

```bash
pytest -q
```

62 tests, all passing with no API keys. They cover the state machine (three misses to a welfare check, late or stale webhooks never overwrite an answer, two unclear answers to a callback, every seed script on autopilot), the priority formula, the keyword fallback on every seed utterance in both languages plus harder wording (negations, mixed signals, curly apostrophes, uppercase), negated injuries such as "No me caí" or "I'm not hurt" not being read as medical, Gemini errors and timeouts falling back to keywords, and the Twilio webhooks, simulator routes, and signature validation.

## Project layout

```
app/config.py        settings from .env
app/models.py        Status, Answer, CallReading, Resident
app/scripts.py       English and Spanish call scripts and family texts
app/classify.py      Gemini classifier, keyword and keypad fallback
app/priority.py      priority score and the reasons behind it
app/engine.py        call state machine: retries, welfare checks, texts
app/seed.py          the 10 demo residents, plus residents_phones.json mapping
app/main.py          FastAPI server: board, simulator, and Twilio webhooks
app/twilio_voice.py  outbound calls, TwiML, SMS, signature validation
app/static/          board.html (dispatch board), phone.html (phone simulator)
mcp_server.py        VoiceOS tools over the same HTTP API
tests/               engine, classifier, and webhook tests
```

## Safety

- Every resident in the demo is **fictional**. Real calls go only to consenting teammates mapped in `residents_phones.json`. Demo texts start with "Headcount demo:".
- Headcount is **not an official alert system** and never claims to be a government agency. In an emergency, call 911.
- We do **not** use Gemini's Google Maps grounding, which is not permitted for emergency response use.

## Built with

- [Google Gemini API](https://ai.google.dev/) (`google-genai`), for speech understanding (English and Spanish, text and audio)
- [Twilio](https://www.twilio.com/) Programmable Voice and SMS (`twilio`)
- [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [Pydantic](https://docs.pydantic.dev/), `python-multipart`, `python-dotenv`
- [Model Context Protocol](https://modelcontextprotocol.io/) Python SDK (`mcp`), with VoiceOS as the voice client
- Plain HTML, CSS, and JavaScript for the board and phone simulator (no build step)
- [pytest](https://pytest.org/) and [HTTPX](https://www.python-httpx.org/) for tests
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`cloudflared`) or [ngrok](https://ngrok.com/) to reach Twilio webhooks
- [GitHub Copilot](https://github.com/features/copilot), see [COPILOT.md](COPILOT.md)

## How we built it

Four teammates worked in parallel from shared briefs with one interface contract: [Engine + Gemini](docs/briefs/AGENT_1_ENGINE_GEMINI.md), [Twilio + API server](docs/briefs/AGENT_2_TWILIO_API.md), [Frontend](docs/briefs/AGENT_3_FRONTEND.md), and [VoiceOS + docs + pitch](docs/briefs/AGENT_4_VOICEOS_DOCS.md). The pitch is in [PITCH.md](PITCH.md).

## License

MIT. See [LICENSE](LICENSE).
