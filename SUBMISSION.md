# Headcount: MLH submission draft

Draft text for the [MLH submission form](https://www.mlh.com/events/aic-at-uc-san-diego-hack-for-humanity/submissions/new). Every claim below can be checked in this repo. Paste each section into the matching field.

## One-liner

When an evacuation order goes out, Headcount phones every older adult in the zone, in English or Spanish, until each one is accounted for.

## The problem

Evacuation alerts broadcast one way. A phone buzzes and nobody closes the loop on who actually got out. Responders end up knocking on the doors of people who already left, while the people who can't leave on their own wait. Many of them are older adults: on oxygen, in a wheelchair, without a car, living alone, on a landline, sometimes speaking only Spanish. They can't use an app, and an alert can't tell anyone whether they made it out.

## What it does

- **Calls every resident in the zone**, staggered, with a real phone call through Twilio, or a built-in phone simulator when Twilio is off.
- **Text check-in for deaf and hard-of-hearing residents.** Instead of a call, they get a text asking them to reply 1, 2, 3, or in their own words, in English or Spanish. Replies go through the same understanding and the same rules, including three tries and then a welfare check. In the demo, George (hard of hearing) is checked in by text and replies "1".
- **Understands the answer** in their own words, in English or Spanish ("No tengo carro y uso oxígeno"), or from the keypad (1 = I'm out, 2 = I need a ride, 3 = I need medical help).
- **Never guesses.** A missed call is retried. After three missed calls, the resident is flagged for a **welfare check** and a person is sent to the door. Two unclear answers mean a human calls them back.
- **Live dispatch board** for responders, ranked by a priority score that shows its reasons (for example "age 87, bedridden, lives alone"), with one English line a responder can act on, such as "No car, uses oxygen. Needs a ride."
- **Family texts** the moment their person is accounted for, or when a welfare check is called.
- **Voice for responders** through VoiceOS: an MCP server lets a responder ask out loud "who still needs help?" or "what's Walter's status?" and hear a spoken answer. The tool that starts calls is marked as placing real phone calls, so VoiceOS asks for confirmation before running it.
- **Demo-safe:** a 10-resident fictional demo zone, a phone simulator (`/phone`), a no-backend mock mode (`/?mock=1`), and a preflight check that never places calls.

## How we built it

- **Backend:** Python, FastAPI and Uvicorn. One call state machine (`app/engine.py`) tags every event with its call attempt, so a late webhook from an old call can never overwrite a newer answer.
- **Speech understanding:** the Google Gemini API (`google-genai`) returns a structured `CallReading` (answer, people with them, mobility, medical equipment, pets, their words, and a responder note) from English or Spanish text, plus audio from the simulator mic. If Gemini errors, times out or is rate-limited, the classifier falls back to tested English and Spanish keyword rules. Keypad input skips classification entirely.
- **Decisions in plain code:** retries, welfare checks, priority scores (`app/priority.py`, a weight times a vulnerability multiplier) and family texts are ordinary Python with tests. Gemini never decides who gets help.
- **Phone calls:** Twilio Programmable Voice (speech and keypad Gather, status callbacks, signature validation) and SMS.
- **Frontend:** plain HTML, CSS and JavaScript (no build step) for the dispatch board and phone simulator.
- **Voice for responders:** an MCP server (`mcp_server.py`, Python MCP SDK) that VoiceOS launches over stdio. It reads the same HTTP API as the board.
- **Testing:** pytest, with more than 80 tests that pass with no API keys. They cover the state machine, the priority formula, the classifier in both languages, the Twilio webhooks and full simulated campaigns.
- **GitHub Copilot** CLI, brought in for the second half of the build, for explanations, extra tests, code review and docstrings, logged in [COPILOT.md](COPILOT.md).
- **Teamwork:** four parallel workstreams (engine and Gemini, Twilio and API, frontend, VoiceOS and docs) built against one written interface contract (`docs/briefs/`).

## Challenges we ran into

- **Late phone-company webhooks.** Twilio can deliver a status update for an old call after a newer call has already been answered. We added an attempt number to every event, and a Copilot code review then found that resetting a campaign could reuse those numbers. That is fixed and tested.
- **Free-tier AI limits.** Bursts of calls hit Gemini rate limits and timeouts. We switched to a faster model (about a second per answer), capped Headcount at 3 Gemini requests at a time, and made sure every call still completes on keyword rules if Gemini doesn't answer within 8 seconds.
- **Negation in two languages.** "No me caí" (I didn't fall) was being read as a medical emergency by our keyword fallback. Extra tests caught it before the demo, and it's now a regression test.
- **Oxygen isn't an emergency.** Saying "I use oxygen" should raise someone's priority, not turn them into an ambulance call. The classifier now records equipment without changing the answer.
- **Real calls without real risk.** Trial Twilio accounts, tunnels that change URL on every restart, and placeholder numbers. Real calls stay off unless every Twilio setting is valid, and everything else runs simulated.

## Accomplishments that we're proud of

- The whole loop works end to end: call, understand, decide, dispatch, text the family, and answer a responder by voice.
- Every decision on the board can be explained ("three unanswered calls", "age 87, bedridden, lives alone") instead of "the model said so".
- Spanish speakers are first-class: the call itself and the understanding of their answer both work in Spanish.
- The demo is built not to hurt anyone: fictional residents, real calls only to consenting teammates, and a "not an official alert system; in an emergency call 911" footer on the board.

## What we learned

- Language models are great at understanding messy speech and should not make life-safety decisions. Splitting those two jobs made the system easier to build, test and trust.
- Real-world telephony is mostly about timing: retries, late callbacks, ring timeouts and webhook deadlines.
- Planning for failure (AI down, Twilio down, wifi down) is part of the product for emergency software, not an afterthought.
- A written interface contract let four people build in parallel without stepping on each other.

## What's next for Headcount

- Family texts in the family's language, more languages, and TTY and relay support for deaf and hard-of-hearing residents.
- Importing opt-in resident lists from partner agencies (county emergency services, senior-services nonprofits, assisted-living operators).
- A pilot with one senior-living community, measured by minutes to account for every resident in a zone.

## Prize tracks

**Best Overall.** Headcount closes the loop that evacuation alerts leave open for the people most likely to be left behind, older adults who can't use apps, and it does it with a plain phone call and decisions anyone can audit.

**Best Use of the Gemini API.** Gemini turns free speech in English or Spanish (text, or audio from the simulator) into a structured `CallReading` with an answer, companions, mobility, medical equipment, pets and a responder note, defined by a Pydantic schema whose field descriptions are Gemini's instructions (`app/classify.py`, `app/models.py`). It's wrapped in a timeout, a concurrency cap and a tested keyword fallback, so the AI makes every call smarter without ever being a single point of failure.

**Best Use of GitHub Copilot.** We brought in GitHub Copilot CLI for the second half of the build, after the core was working, for explanation, testing, code review and docs, and logged every real interaction in [COPILOT.md](COPILOT.md):
- **Learn:** it traced how a stale Twilio webhook is kept from overwriting a newer answer, with line references.
- **Test:** it wrote an extra classifier suite (`tests/test_classify_extra.py`) that found a real bug: negated injuries like "No me caí" were read as medical emergencies.
- **Solve:** after we fixed that bug, it promoted those xfails to regression tests. A Copilot code review of the engine found a stale-attempt collision after reset and two reset and autopilot races, which we then fixed, with new engine tests (commit `1054de6`).
- **Document:** it wrote the module and `score()` docstrings in `app/priority.py` that explain the priority formula, with a worked example (Walter scores 100 × 2.1 = 210) (commit `94673f5`).

Copilot's own commits carry its co-author trailer, so its contributions can be checked in the git history.
