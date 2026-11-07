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

1. **Get a number.** In the Twilio console, buy or use a voice-capable number and put it in `TWILIO_FROM_NUMBER`, along with `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`.
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

## Tests

```bash
pytest -q
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
