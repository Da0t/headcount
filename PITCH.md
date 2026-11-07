# Headcount pitch (2 minutes)

Spoken lines are in plain text. *Stage directions are in italics.* The spoken lines are about 275 words, roughly 1:50 at a normal pace. Keep demo pauses short, and if you're running long, cut the George beat first.

## Script

**0:00 · Maria**

Santa Ana winds. An evacuation order goes out for Tierrasanta, in San Diego. Maria Gonzalez is 81, on oxygen, has no car, and speaks Spanish. The alert reached her phone. Did she get out? Nobody knows.

**0:20 · The gap**

Alerts only go one way. Responders end up knocking on the doors of people who already left, while the people who can't leave sit and wait. It calls every older adult in the zone until each one is accounted for.

**0:40 · Live demo**

*Press **Start** on the board. With Twilio on, teammates' phones ring in the room. With Twilio off (the current setup), a teammate answers Maria's call on the phone simulator at `/phone`.*

Every resident gets a call, in their language.

*A teammate answers as Maria, in Spanish: "No tengo carro y uso oxígeno."*

She said it in her own words. The row flips to **needs a ride**, with "uses oxygen" for the driver.

*With Twilio on, the family text lands on another teammate's phone: hold it up. With Twilio off, point at Maria's row, which reads "Texted Ana (daughter) (simulated)".*

Her daughter Ana just got a text.

*Point at George's row.*

George is hard of hearing, so he never gets a call. He gets a text and replies 1.

*Point at the map.*

Tomasina is 96 and bedridden, and she never picks up. Headcount doesn't guess. After three calls her pin turns red, and a wheelchair van routes from the fire base to her, then on to the Mesa Lantern shelter, which has backup power for her oxygen. Every place on this map is fictional.

*Ask VoiceOS out loud: "Who still needs help?" Let it answer.*

A responder in a truck can ask that without touching a screen.

**1:30 · The rule**

Gemini understands messy speech in two languages, in about a second. Plain, tested rules decide who gets help, so every call can be explained.

**1:40 · "I'll call it myself"**

*Dial the Headcount number from your own phone, on speaker.*

One more. I'll call it myself, as someone in danger.

*Answer its three questions out loud: are you safe, who's with you, where are you.*

It understood me, flagged what I need, and a simulated dispatch routes a vehicle to me. This is a demo: no real responders are contacted. In a real emergency, call 911.

**1:55 · Close**

*Point at the green banner. With 20 residents, the board ends at 7 out and safe, 6 need a ride, 2 need medical help, 2 are staying, 2 welfare checks, and 1 callback.*

"Every resident is accounted for or has a responder on the way." That's Headcount.

## Fallback demo (30 seconds), if the server or wifi fails

Open `/?mock=1` ahead of time in a second tab. Mock mode runs the whole campaign in the browser with fictional residents, with no server, no Twilio and no Gemini. The board shows a **MOCK DATA** tag, so say so out loud.

1. **0:00** *Switch to the mock tab and press Start.* "Same campaign, running in the browser. The wifi's down, but the logic isn't."
2. **0:10** *Point at Maria's row turning **needs a ride**.* "Maria answered in Spanish: no car, on oxygen. She's flagged for a ride, and her daughter is told."
3. **0:20** *Point at Walter's row.* "Walter never answered. After three calls, the board says send a person. It never guesses."
4. **0:30** *Point at the banner.* "Every resident is accounted for or has a responder on the way."

VoiceOS needs the real server, so skip it in mock mode. If you recorded a VoiceOS answer during rehearsal, play that instead.

## Judge Q&A prep

**Who runs it? (SAP)**
County emergency services, senior-services nonprofits, and assisted-living operators. They already keep lists of residents who need help evacuating. Headcount turns that list into calls.

**What does it save? (SAP)**
Responder hours. Door-knocking goes only to the people who need it (welfare checks, rides, medical), not to people who already left.

**What's the metric? (SAP)**
Minutes to account for every resident in a zone. The board tracks it live: total, unaccounted, done.

**Where does voice come in? (VoiceOS)**
Both ends. Voice in for residents who can't use apps: a plain phone call they answer by talking or pressing 1, 2, or 3. Voice out for responders through the MCP server: "who still needs help?", "what's Walter's status?", "start the calls" (which asks for confirmation first, since it places real calls).

**Why not let the AI decide?**
Auditability and trust. Gemini only turns speech into structured facts. Retries, welfare checks, priority, and who gets a text are plain Python with tests. If someone asks why a person went to Walter's door, the answer is "three unanswered calls", not "the model said so". Gemini takes about a second per answer. If it's slower than 8 seconds, errors, or is unsure, we fall back to keywords, then to a human callback.

**Privacy and consent?**
Opt-in resident lists from partner agencies. We store only what a responder needs: name, address, a few risk flags, and one emergency contact. Every resident in the demo is fictional unless mapped to a consenting teammate's phone. This is not an official alert system.

**What's next?**
More languages, TTY and relay support for deaf and hard-of-hearing residents, and a pilot with one senior-living community.
