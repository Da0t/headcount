# Headcount

**When an evacuation order goes out, Headcount calls every older adult in the zone until each one is accounted for.**

Alerts broadcast into the dark. Nobody closes the loop on who actually got out, and the people most at risk are older adults on landlines who can't use apps. Headcount phones every resident and understands what they say, in English or Spanish, or with the keypad 1/2/3. If it can't reach someone after three calls, it never guesses: it sends a person. Responders watch a live, priority-ranked dispatch board, and families get a text the moment their person is accounted for.

Built at AIC at UC San Diego Hack for Humanity (MLH), November 7, 2026.

## How it works

- **Twilio** places real phone calls and family texts.
- **Gemini** understands free speech ("mi esposo no puede caminar") and turns it into structured facts.
- **Plain, tested Python** decides everything that matters: retries, welfare checks, priority, who gets a text. AI never decides who gets help.
- **VoiceOS** lets a responder ask out loud, "who still needs help?"

## Building it (four agents in parallel)

| Agent | Brief | Owns |
|---|---|---|
| 1 | [Engine + Gemini](docs/briefs/AGENT_1_ENGINE_GEMINI.md) | `app/config.py` `models.py` `scripts.py` `classify.py` `priority.py` `engine.py` `seed.py` |
| 2 | [Twilio + API server](docs/briefs/AGENT_2_TWILIO_API.md) | `app/main.py` `app/twilio_voice.py` |
| 3 | [Frontend](docs/briefs/AGENT_3_FRONTEND.md) | `app/static/board.html` `app/static/phone.html` |
| 4 | [VoiceOS + docs + pitch](docs/briefs/AGENT_4_VOICEOS_DOCS.md) | `mcp_server.py` `README.md` `COPILOT.md` `PITCH.md` |

Each brief ends with the same shared contract, so the pieces plug together. Agent 1 ships `models.py`, `scripts.py`, and `classify.py` first; Agent 3 starts in mock mode (`/?mock=1`) so nobody waits.

## Quick start (once built)

```bash
pip install -r requirements.txt
cp .env.example .env        # add GEMINI_API_KEY and Twilio settings
uvicorn app.main:app --port 8000
```

## Safety

All residents in the demo are fictional unless mapped to a consenting teammate's phone. Headcount is not an official alert system; in an emergency, call 911.

## License

MIT. See [LICENSE](LICENSE).
