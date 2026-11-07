# Headcount architecture

Headcount is a demo dispatch board for checking whether fictional residents in
an evacuation zone are safe and what help they need. The demo zone is
Tierrasanta, San Diego. Names, addresses, map points, the base, and shelters
are fictional demo data, not real evacuation guidance.

## Outbound call lifecycle

The outbound flow starts when a responder starts a campaign on the board:

```text
Responder
   |
   v
POST /api/start
   |
   v
Engine.start() resets runtime state and schedules resident calls
   |
   v
Engine._dial()                  Calls are staggered by configuration
   |
   +---- Twilio + mapped phone ----> real call or check-in text
   |                                  |
   |                                  v
   |                         Twilio webhook to /twilio/*
   |
   +---- otherwise ----------------> simulated call or text
                                      |
                                      v
                            resident answers or misses
                                      |
                                      v
                    classify answer -> Engine.respond()
                                      |
                                      v
              resident status, event log, and /api/state
```

`POST /api/start` does not restart a campaign that is already running. A
campaign reset makes residents pending and schedules calls with the configured
stagger. A single resident can instead be started through
`POST /api/residents/{rid}/call`; a real phone requires the explicit
`X-Headcount-Confirm: yes` header.

For each resident, the engine increments an attempt token and sets the status
to `CALLING`. If Twilio is configured and the resident has a phone number,
voice-mode residents receive a call and text-mode residents receive a check-in
SMS. Otherwise the engine uses the simulator. The phone simulator can accept
the call, and autopilot can play a resident's scripted response for the demo.

For a voice call, Twilio requests `/twilio/voice/{rid}` and then posts the
speech or keypad result to `/twilio/gather/{rid}`. For a simulated call, the
phone UI uses `/api/sim/ringing`, `/api/sim/{rid}/answer`, and
`/api/sim/{rid}/say`. Text replies use the SMS path. Speech is converted to a
structured reading, then the engine updates the resident, records an event,
and may notify the listed family contact. Attempt tokens prevent a late event
from an older call from changing the current attempt.

If there is no answer, or a call is declined, the engine waits for the
configured retry gap and schedules another try until `max_attempts` is reached
(three by default). After the final miss, it sets `WELFARE_CHECK` and logs that
a person should go to the resident's door. It does not automatically send a
responder. A clear answer ends that call with one of the answered statuses.
After two unclear answers, the resident becomes `NEEDS_CALLBACK` for a person
to call back.

## Inbound call: three structured steps

An inbound call asks three questions, then sends the combined information
through the same answer handling used for outbound calls:

1. **Safety and help:** asks whether the caller is safe or needs help. They can
   speak freely, or press 1 for safe, 2 for a ride, or 3 for medical help.
2. **People and pets:** asks who is with them and whether they have pets.
3. **Location:** asks for their address or nearest cross street.

Speech from the three steps is joined for classification. A keypad choice from
step 1 determines the answer when present, while speech supplies additional
details. The third answer is saved as where they are. If the combined answer
is unclear, the flow restarts its questions once; the engine's second unclear
result becomes `NEEDS_CALLBACK`.

**Free browser simulation:** `/phone` starts the flow with
`POST /api/sim/incoming`, then submits answers to `/api/sim/inbound/{rid}`.
The caller can be a selected resident, the configured demo resident, or a new
simulated caller. This path does not use a phone number or Twilio.

**Real Twilio path:** configure the Twilio number's incoming-call webhook to
POST to `/twilio/incoming`. Headcount matches the `From` number to a resident
by its last ten digits. An unmatched number is added to the board as a caller
with an unknown address and a location at the demo-zone center. Twilio then
posts each answer to `/twilio/inbound/{rid}`. The incoming webhooks are
signature-checked when Twilio validation is enabled.

If the caller ends the call before a clear answer, the inbound watchdog marks
the resident `NEEDS_CALLBACK` and logs that a person should call back. It does
not automatically redial a real phone. A ride or medical result adds a
simulated-routing notice to the call and event log. No real responders,
hospitals, or emergency services are contacted.

## Resident statuses

`app/models.py` defines the statuses and the structured answer values.
`app/engine.py` moves residents through them:

| Status | Meaning in the flow |
| --- | --- |
| `PENDING` | Not yet called in the current campaign. |
| `CALLING` | An outbound call or check-in is being attempted. |
| `IN_CALL` | The resident answered or an inbound call is in progress. |
| `RETRY_WAIT` | An outbound attempt was missed; another attempt is scheduled. |
| `OUT` | The resident says they are already out or safe elsewhere. |
| `NEEDS_RIDE` | The resident needs a ride to leave. |
| `NEEDS_MEDICAL` | The resident reports an urgent medical need. |
| `STAYING` | The resident says they will stay. |
| `NEEDS_CALLBACK` | The answer remained unclear, or an inbound call ended before a clear answer. |
| `WELFARE_CHECK` | Outbound attempts were exhausted without reaching the resident. |

`PENDING`, `CALLING`, `IN_CALL`, and `RETRY_WAIT` are unaccounted statuses.
The board shows counts and resident details from the engine snapshot.

## AI and plain rules

Gemini is used to understand speech and return structured facts such as the
answer, companions, mobility help, equipment, pets, location, and a responder
note. For spoken audio it can also produce a transcript. Gemini does not decide
who gets help. Text classification falls back to English and Spanish keyword
rules if Gemini is unavailable, times out, or errors. Keypad answers are
converted directly to readings without Gemini.

Ordinary Python rules in `app/engine.py` handle attempts, retry timing,
callbacks, welfare checks, campaign status, and family notifications.
`app/priority.py` calculates a visible score from status urgency and resident
vulnerabilities. `app/accessibility.py` uses profile and call details to
recommend transport and choose a demo shelter. Transport rules can recommend
an ambulance for medical help, a wheelchair van for mobility needs, a
large-animal trailer, or a standard car for a ride request. Shelter capabilities
cover wheelchair access, oxygen backup power, medical staff, pets, and large
animals. Selection matches the most required capabilities, preferring fewer
extra capabilities when there is a tie. These rules recommend assistance;
they do not dispatch people.

## Map data flow

`GET /api/map` returns map configuration: the demo center, zoom, zone polygon,
fictional Station 0 base, shelter coordinates and capabilities, and the public
Mapbox token or an empty string. The zone polygon is calculated to cover the
resident and shelter points. All coordinates and places are fictional demo
data in Tierrasanta, San Diego.

`GET /api/state` returns the engine snapshot. Each resident row includes its
`lat` and `lng`, and the route adds an `assist` plan from
`app/accessibility.py`. That plan includes selected shelter coordinates as
`shelter_lat` and `shelter_lng`, or null coordinates when no shelter applies.
The board uses the map configuration together with these per-resident fields.
The map is illustrative and is not navigation guidance.

## File map

- `app/main.py`: FastAPI routes for the board API, simulator, and Twilio webhooks.
- `app/engine.py`: campaign state, call attempts, responses, retries, and events.
- `app/classify.py`: Gemini speech understanding, keyword fallback, and keypad readings.
- `app/models.py`: resident, answer, and status data structures.
- `app/priority.py`: responder-facing urgency score and reasons.
- `app/accessibility.py`: rule-based transport needs and fictional shelter choices.
- `app/twilio_voice.py`: Twilio voice prompts, inbound questions, SMS, and webhook validation.
- `app/seed.py`: fictional Tierrasanta demo residents and zone coordinates.
- `app/static/board.html`: dispatch board and map.
- `app/static/phone.html`: browser phone simulator.
- `mcp_server.py`: VoiceOS tools that use the same HTTP API.
- `tests/`: tests for the engine, classifier, API, Twilio flow, and assistance rules.
