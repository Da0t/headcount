/*
 * Headcount data layer. The only file that talks to the server.
 *
 * A replacement frontend needs nothing else: create a client, poll getState(), and re-render.
 *
 *   <script src="/static/headcount-api.js"></script>
 *   const api = HeadcountAPI.create({ mock: location.search.includes("mock=1") });
 *   const stop = HeadcountAPI.poll(api.getState, 1000, { onData: render, onError: showOffline });
 *
 * Every method returns a Promise. Failures reject with HeadcountAPI.ApiError
 * ({status, detail, message}); status 0 means the server could not be reached.
 *
 * mock: true runs a client-side copy of the demo campaign (same seed cast, same engine rules,
 * same response shapes), so the UI can be built and rehearsed with no backend.
 * Full contract: docs/FRONTEND_CONTRACT.md
 *
 * ---------------------------------------------------------------- response shapes
 *
 * @typedef {"PENDING"|"CALLING"|"IN_CALL"|"RETRY_WAIT"|"OUT"|"NEEDS_RIDE"|"NEEDS_MEDICAL"|"STAYING"|"NEEDS_CALLBACK"|"WELFARE_CHECK"} Status
 *   Unaccounted: PENDING, CALLING, IN_CALL, RETRY_WAIT. Everything else is a final answer.
 *
 * @typedef {Object} Reading            What one resident said, structured (null until they answer).
 * @property {"OUT"|"NEEDS_RIDE"|"NEEDS_MEDICAL"|"STAYING"|"UNCLEAR"} answer
 * @property {number}   people_with_them  other people with them who also need to get out
 * @property {boolean}  mobility_help
 * @property {string[]} medical_equipment e.g. ["oxygen"]
 * @property {string[]} pets              e.g. ["dog", "4 horses"]
 * @property {string}   where_they_are
 * @property {string}   quote             their words, in their language
 * @property {string}   responder_note    one English line a responder can act on
 * @property {string}   engine            who understood them: "Gemini (model)", "keywords (...)", "keypad"
 *
 * @typedef {Object} Resident
 * @property {number}  id
 * @property {string}  name
 * @property {string}  first
 * @property {number}  age
 * @property {string}  address
 * @property {"en"|"es"} lang
 * @property {Status}  status
 * @property {number}  attempts          calls placed so far (compare with State.max_attempts)
 * @property {""|"sim"|"twilio"} channel
 * @property {number}  score             priority score, higher = send help sooner
 * @property {string[]} why              reasons for the score, e.g. ["age 87", "bedridden"]
 * @property {Reading|null} reading
 * @property {string}  family            family-text status, e.g. "Texted Ana (daughter)"; "" if none yet
 * @property {number}  updated           unix seconds of last change
 * @property {boolean} real_phone        true if this resident is called on a real phone via Twilio
 * @property {"voice"|"text"} contact_mode  "text": checked in by SMS instead of a call (deaf / hard of hearing)
 * @property {Assist|null} assist        where to take them and how (may be missing on older servers)
 * @property {number} lat                fictional demo coordinates of their address
 * @property {number} lng
 *
 * @typedef {Object} Assist
 * @property {string|null} transport     "wheelchair van" | "ambulance" | "standard car" | "large-animal trailer" | null
 * @property {string|null} shelter       fictional demo shelter name, or null if already out
 * @property {string[]} shelter_why      why that shelter
 * @property {string[]} needs            what responders should bring or know
 * @property {number|null} shelter_lat    shelter location for the route line (null when no shelter)
 * @property {number|null} shelter_lng
 *
 * @typedef {Object} Event
 * @property {number} t                  unix seconds
 * @property {number|null} rid
 * @property {string|null} name
 * @property {"info"|"start"|"speech"|"good"|"warn"|"alert"|"family"|"error"} kind
 * @property {string} msg
 *
 * @typedef {Object} State              GET /api/state
 * @property {string}  zone
 * @property {number}  total
 * @property {number}  unaccounted
 * @property {boolean} done              campaign started and nobody unaccounted
 * @property {number|null} started_at    unix seconds, null before Start
 * @property {number}  max_attempts
 * @property {boolean} twilio            Twilio client configured
 * @property {boolean} gemini            Gemini key configured
 * @property {boolean} autopilot
 * @property {Object<string, number>} counts   status -> count (missing = 0)
 * @property {Resident[]} residents      ALREADY SORTED, highest priority first. Never re-sort.
 * @property {Event[]} events            chronological, oldest first (server keeps the last 200)
 * @property {boolean} [mock]            true only in mock mode
 *
 * @typedef {Object} Ringing            GET /api/sim/ringing (one entry per simulated live call)
 * @property {number} id
 * @property {string} name
 * @property {string} first
 * @property {"en"|"es"} lang
 * @property {"CALLING"|"IN_CALL"} status   only CALLING should show an Answer button
 * @property {number} attempt
 * @property {string} prompt             what Headcount says when they pick up (the SMS text for text mode)
 * @property {"voice"|"text"} contact_mode
 *
 * @typedef {Object} SayResult          POST /api/sim/{id}/say
 * @property {string}  say               Headcount's reply, speak it
 * @property {boolean} keep_listening    true: stay in the call and let them answer again
 * @property {Reading} reading           how the answer was understood
 */
(function (root) {
  "use strict";

  class ApiError extends Error {
    constructor(status, detail) {
      super(detail || ("HTTP " + status));
      this.name = "ApiError";
      this.status = status;   // 0 = network error / server unreachable
      this.detail = detail || "";
    }
  }

  // ------------------------------------------------------------------ live client

  async function request(method, path, body) {
    let res;
    try {
      res = await fetch(path, { method, body, headers: { Accept: "application/json" }, cache: "no-store" });
    } catch (e) {
      throw new ApiError(0, "Server unreachable");
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty or non-JSON body */ }
    if (!res.ok) {
      let detail = data && data.detail;
      if (detail && typeof detail !== "string") detail = JSON.stringify(detail);
      throw new ApiError(res.status, detail || (res.status + " " + res.statusText));
    }
    return data;
  }
  const q = encodeURIComponent;

  function liveClient() {
    return {
      mock: false,
      /** @returns {Promise<State>} */
      getState: () => request("GET", "/api/state"),
      /**
       * Start the campaign. While one is still running this is a no-op that returns already_running: true;
       * after it is done (or after reset) it starts fresh.
       * @returns {Promise<{ok: true, already_running?: true}>}
       */
      start: () => request("POST", "/api/start"),
      /** @returns {Promise<{ok: true}>} */
      reset: () => request("POST", "/api/reset"),
      /** @returns {Promise<{autopilot: boolean}>} */
      setAutopilot: (on) => request("POST", "/api/autopilot?on=" + (on ? "true" : "false")),
      /**
       * GET /api/health, or null on an older server without it.
       * gemini: a GEMINI_API_KEY is set. twilio: credentials, from number and PUBLIC_BASE_URL are set and the
       * client started (real calls possible). model: the Gemini model name. autopilot: live engine value.
       * @returns {Promise<{ok: boolean, gemini: boolean, twilio: boolean, model: string, autopilot: boolean}|null>}
       */
      health: async () => {
        try { return await request("GET", "/api/health"); }
        catch (e) { if (e.status === 404 || e.status === 405) return null; throw e; }
      },
      /**
       * One resident, for the profile panel: the State row plus assist, contact_mode, call_sid, attempt (webhook token),
       * demo, last_call_status ({status: "initiated"|"queued"|"ringing"|"in-progress"|"completed"|"busy"|"no-answer"|
       * "failed"|"canceled", attempt, t, call_sid} or null) and events (this resident only, oldest first).
       * Returns null on an older server without the endpoint.
       */
      /**
       * GET /api/map: {token, center: [lng, lat], zoom, zone: GeoJSON Polygon, base: {name, lng, lat},
       * shelters: [{name, short, lng, lat, wheelchair_accessible, oxygen_power, medical_staff, pets_allowed,
       * large_animals, fictional}]}. token "" means show the no-map fallback. null on an older server.
       */
      getMap: async () => {
        try { return await request("GET", "/api/map"); }
        catch (e) { if (e.status === 404 || e.status === 405) return null; throw e; }
      },
      getResident: async (rid) => {
        try { return await request("GET", "/api/residents/" + q(rid)); }
        catch (e) { if (e.status === 405 || (e.status === 404 && !/resident/i.test(e.detail))) return null; throw e; }
      },
      /**
       * Call one resident now (restarts just them: calls 1..3 with retries and a welfare check).
       * A REAL phone (real_phone: true) needs confirm=true, which sends X-Headcount-Confirm: yes; without it the
       * server answers 409 "Confirm to place a real call". @returns {Promise<{ok: true, real_phone: boolean}>}
       */
      callResident: async (rid, confirm) => {
        let res;
        try {
          res = await fetch("/api/residents/" + q(rid) + "/call", { method: "POST", cache: "no-store",
            headers: Object.assign({ Accept: "application/json" }, confirm ? { "X-Headcount-Confirm": "yes" } : {}) });
        } catch (e) { throw new ApiError(0, "Server unreachable"); }
        let data = null;
        try { data = await res.json(); } catch (e) { /* empty */ }
        if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText);
        return data;
      },
      /** @returns {Promise<Ringing[]>} */
      simRinging: () => request("GET", "/api/sim/ringing"),
      /** Pick up. Rejects with status 409 if the call is no longer ringing. @returns {Promise<{say: string}>} */
      simAnswer: (rid, attempt) => request("POST", "/api/sim/" + q(rid) + "/answer?attempt=" + q(attempt)),
      /** Decline a ringing call, or hang up a live one (reason "hung up"). @returns {Promise<{ok: true}>} */
      simDecline: (rid, attempt, reason) =>
        request("POST", "/api/sim/" + q(rid) + "/decline?attempt=" + q(attempt) + "&reason=" + q(reason || "declined")),
      /**
       * Answer in words: {text: "ya salimos"} or a recording {audio: Blob, filename?: "answer.webm"}.
       * Audio needs the live server and a Gemini key (the server returns a 4xx detail otherwise).
       * @returns {Promise<SayResult>}
       */
      simSay: (rid, attempt, input) => {
        const fd = new FormData();
        if (input && input.audio) fd.append("audio", input.audio, input.filename || "answer.webm");
        else fd.append("text", (input && input.text) || "");
        return request("POST", "/api/sim/" + q(rid) + "/say?attempt=" + q(attempt), fd);
      },
    };
  }

  // ------------------------------------------------------------------ mock backend
  // A client-side copy of app/seed.py, app/priority.py, app/scripts.py and the engine rules.

  function mockClient(opts) {
    const ZONE = "Tierrasanta, San Diego (demo zone)";
    const MAX_ATTEMPTS = 3, STAGGER = 0.9, GAP = 6;
    // phoneDemo: one call at a time and no ring-out, so a person has time to play the resident.
    const PHONE_DEMO = !!opts.phoneDemo;
    const RING = PHONE_DEMO ? Infinity : 7;
    const WEIGHT = { WELFARE_CHECK: 100, NEEDS_MEDICAL: 95, NEEDS_RIDE: 75, NEEDS_CALLBACK: 65, STAYING: 55,
      CALLING: 40, IN_CALL: 40, RETRY_WAIT: 40, PENDING: 35, OUT: 0 };
    const LIVE = new Set(["CALLING", "IN_CALL"]);
    const UNACC = new Set(["PENDING", "CALLING", "IN_CALL", "RETRY_WAIT"]);
    const EVLABEL = { OUT: "Out", NEEDS_RIDE: "Needs a ride", NEEDS_MEDICAL: "Needs medical help", STAYING: "Staying" };
    const EVKIND = { OUT: "good", NEEDS_RIDE: "warn", STAYING: "warn", NEEDS_MEDICAL: "alert" };
    const PROMPT = {
      en: "Hello {first}, this is Headcount, the evacuation check for your neighborhood. There is an evacuation order for your area. Please tell me, in your own words, are you out, or do you need help? You can also press 1 if you are out, 2 if you need a ride, or 3 if you need medical help.",
      es: "Hola {first}, le habla Headcount, la verificación de evacuación de su vecindario. Hay una orden de evacuación para su zona. Por favor dígame, con sus propias palabras, ¿ya salió o necesita ayuda? También puede oprimir 1 si ya salió, 2 si necesita transporte, o 3 si necesita ayuda médica.",
    };
    const TEXT_PROMPT = {
      en: "Headcount, the evacuation check for your neighborhood: there is an evacuation order for your area, {first}. Reply 1 if you are out, 2 if you need a ride, 3 if you need medical help, or reply in your own words. If anyone is in danger right now, text or call 911.",
      es: "Headcount, la verificación de evacuación de su vecindario: hay una orden de evacuación para su zona, {first}. Responda 1 si ya salió, 2 si necesita transporte, 3 si necesita ayuda médica, o responda con sus palabras. Si alguien está en peligro ahora mismo, envíe un texto o llame al 911.",
    };
    const promptFor = (r) => ((r.contact_mode === "text" ? TEXT_PROMPT : PROMPT)[r.lang === "es" ? "es" : "en"]).replace("{first}", r.name.split(" ")[0]);
    const TEXT_ASK_AGAIN = {
      en: "Headcount: sorry, we didn't understand. Reply 1 if you are out, 2 if you need a ride, 3 for medical help.",
      es: "Headcount: perdón, no entendimos. Responda 1 si ya salió, 2 si necesita transporte, 3 si necesita ayuda médica.",
    };
    const ASK_AGAIN = {
      en: "Sorry, I didn't catch that. Are you out, or do you need help? Press 1 if you are out, 2 for a ride, 3 for medical help.",
      es: "Perdón, no le entendí. ¿Ya salió o necesita ayuda? Oprima 1 si ya salió, 2 para transporte, 3 para ayuda médica.",
    };
    const DANGER = { en: " If anyone is in danger right now, hang up and call 911.", es: " Si alguien está en peligro ahora mismo, cuelgue y llame al 911." };
    const CONFIRM = {
      OUT: { en: "Thank you. I've marked you as safely out. We'll let your family know. Stay safe.",
        es: "Gracias. Lo marqué como fuera de peligro. Le avisaremos a su familia. Cuídese." },
      NEEDS_RIDE: { en: "Thank you. I've marked that you need a ride, and a responder will come to you." + DANGER.en,
        es: "Gracias. Anoté que necesita transporte y un equipo de rescate irá por usted." + DANGER.es },
      NEEDS_MEDICAL: { en: "Thank you. I've marked that you need medical help, and responders are being told right now." + DANGER.en,
        es: "Gracias. Anoté que necesita ayuda médica y estamos avisando a los equipos de rescate ahora mismo." + DANGER.es },
      STAYING: { en: "I understand you are staying. I've let responders know. If you change your mind, please leave as soon as you can.",
        es: "Entiendo que se va a quedar. Ya les avisé a los equipos de rescate. Si cambia de opinión, por favor salga lo antes posible." },
    };
    const CALLBACK = {
      en: "Thank you. A person from our team will call you back shortly. If you are in danger, call 911.",
      es: "Gracias. Una persona de nuestro equipo le llamará pronto. Si está en peligro, llame al 911.",
    };
    const FAMILY = {
      OUT: "{first} is accounted for and says they are out. Their words: \"{quote}\"",
      NEEDS_RIDE: "{first} answered and needs a ride out. A responder has been told.",
      NEEDS_MEDICAL: "{first} answered and needs medical help. Responders have been told.",
      STAYING: "{first} answered and says they are staying home. Responders have been told.",
      NEEDS_CALLBACK: "{first} answered but we could not understand. A person will call them back.",
      WELFARE_CHECK: "We could not reach {first} after {n} calls, a responder is being sent.",
    };
    function R(answer, quote, note, extra) {
      return Object.assign({ answer, people_with_them: 0, mobility_help: false, medical_equipment: [], pets: [],
        where_they_are: "", quote, responder_note: note, engine: "Gemini (mock)" }, extra || {});
    }
    // Generated from app/seed.py (20 fictional residents) and a keyword-only run of the real engine.
    // Each script step: "no_answer" | "decline" | [readings...] (what the engine understood, in order).
    const SEED = [
      {"id": 1, "name": "Maria Gonzalez", "age": 81, "address": "1420 Lantern Hollow Rd", "lang": "es", "oxygen": true, "mobility": false, "bedridden": false, "lives_alone": true, "hearing": false, "contact_name": "Ana", "contact_relation": "daughter", "contact_mode": "voice", "assist": {"transport": "standard car", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["backup power for oxygen concentrators"], "needs": ["oxygen: bring portable tanks, shelter needs backup power"]}, "script": ["no_answer", [{"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": false, "medical_equipment": ["oxygen"], "pets": [], "where_they_are": "", "quote": "Sí, aquí estoy. No tengo carro y uso oxígeno. Necesito que me ayuden a salir.", "responder_note": "Needs a ride out. Uses oxygen.", "engine": "Gemini (mock)"}]], "lng": -117.10449, "lat": 32.82819},
      {"id": 2, "name": "Walter Briggs", "age": 87, "address": "3 Quailsong Way", "lang": "en", "oxygen": false, "mobility": false, "bedridden": true, "lives_alone": true, "hearing": false, "contact_name": "Linda", "contact_relation": "niece", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["wheelchair accessible"], "needs": ["bedridden: needs a stretcher or lift"]}, "script": ["no_answer", "no_answer", "no_answer"], "lng": -117.09817, "lat": 32.81613},
      {"id": 3, "name": "Dorothy Chen", "age": 76, "address": "2210 Sagebrush Bluff Ct", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Kevin", "contact_relation": "son", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out: at my son's place in El Cajon"], "needs": []}, "script": [[{"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "at my son's place in El Cajon", "quote": "We're out, we're at my son's place in El Cajon.", "responder_note": "Says they are out. Now at my son's place in El Cajon.", "engine": "Gemini (mock)"}]], "lng": -117.09199, "lat": 32.83162},
      {"id": 4, "name": "Frank Russo", "age": 84, "address": "915 Copperleaf Ln", "lang": "en", "oxygen": false, "mobility": true, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Tony", "contact_relation": "son", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Quail Ridge Community Shelter (demo)", "shelter_why": ["wheelchair accessible", "pets allowed"], "needs": ["wheelchair or walker: accessible vehicle", "pets: dog", "1 more person(s) with them"]}, "script": [[{"answer": "NEEDS_RIDE", "people_with_them": 1, "mobility_help": true, "medical_equipment": [], "pets": ["dog"], "where_they_are": "", "quote": "My wife's in a wheelchair and I can't drive anymore. We need help getting out. We have a dog too.", "responder_note": "Needs a ride out. Mobility help needed. 1 other person with them. Animals: dog.", "engine": "Gemini (mock)"}]], "lng": -117.11235, "lat": 32.82203},
      {"id": 5, "name": "James Whitaker", "age": 79, "address": "18 Hummingbird Mesa Dr", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": true, "contact_name": "", "contact_relation": "", "contact_mode": "voice", "assist": {"transport": null, "shelter": "Canyon Lark Equestrian Grounds (demo)", "shelter_why": ["takes large animals"], "needs": ["staying: plan ready in case they change their mind", "large animals: 4 horses (large-animal trailer)", "hard of hearing: use text or face-to-face, not a loudspeaker"]}, "script": ["decline", [{"answer": "STAYING", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": ["4 horses"], "where_they_are": "", "quote": "I'm not leaving. I've got four horses here.", "responder_note": "Refusing to leave. Animals: 4 horses.", "engine": "Gemini (mock)"}]], "lng": -117.08584, "lat": 32.81702},
      {"id": 6, "name": "Rosa Medina", "age": 90, "address": "640 Lark Canyon Pl", "lang": "es", "oxygen": false, "mobility": true, "bedridden": false, "lives_alone": true, "hearing": false, "contact_name": "Carmen", "contact_relation": "granddaughter", "contact_mode": "voice", "assist": {"transport": "ambulance", "shelter": "Sage Hollow Medical Shelter (demo)", "shelter_why": ["wheelchair accessible", "medical staff on site"], "needs": ["medical help: ambulance crew", "wheelchair or walker: accessible vehicle"]}, "script": [[{"answer": "NEEDS_MEDICAL", "people_with_them": 0, "mobility_help": true, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "Me caí en la cocina y no me puedo levantar.", "responder_note": "Needs medical help. Mobility help needed.", "engine": "Gemini (mock)"}]], "lng": -117.10358, "lat": 32.8382},
      {"id": 7, "name": "George Patel", "age": 72, "address": "77 Saltgrass Ridge Rd", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": true, "contact_name": "Priya", "contact_relation": "daughter", "contact_mode": "text", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out"], "needs": ["hard of hearing: use text or face-to-face, not a loudspeaker"]}, "script": [[{"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "1", "responder_note": "Pressed 1: says they are out.", "engine": "keypad"}]], "lng": -117.10149, "lat": 32.82001},
      {"id": 8, "name": "Betty Lawson", "age": 85, "address": "302 Driftstone Way", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": true, "hearing": false, "contact_name": "Susan", "contact_relation": "daughter", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out: at the shelter at the high school"], "needs": []}, "script": [[{"answer": "UNCLEAR", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "Hmm? Who is this?", "responder_note": "", "engine": "Gemini (mock)"}, {"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "at the shelter at the high school", "quote": "Oh, the fire. Yes, I already left. I'm at the shelter at the high school.", "responder_note": "Says they are out. Now at the shelter at the high school.", "engine": "Gemini (mock)"}]], "lng": -117.09201, "lat": 32.82613},
      {"id": 9, "name": "Luis Herrera", "age": 68, "address": "1105 Juniper Echo Ct", "lang": "es", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Marco", "contact_relation": "son", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out"], "needs": []}, "script": ["no_answer", [{"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "Ya salimos todos, estamos bien.", "responder_note": "Says they are out.", "engine": "Gemini (mock)"}]], "lng": -117.10776, "lat": 32.82701},
      {"id": 10, "name": "Edna Morales", "age": 93, "address": "48 Lantern Hollow Rd", "lang": "en", "oxygen": true, "mobility": false, "bedridden": true, "lives_alone": true, "hearing": false, "contact_name": "Ruth", "contact_relation": "neighbor", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["wheelchair accessible", "backup power for oxygen concentrators"], "needs": ["bedridden: needs a stretcher or lift", "oxygen: bring portable tanks, shelter needs backup power"]}, "script": ["no_answer", [{"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": true, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "My caregiver didn't come today. I can't get out of bed by myself.", "responder_note": "Needs a ride out. Mobility help needed.", "engine": "Gemini (mock)"}]], "lng": -117.09412, "lat": 32.8153},
      {"id": 11, "name": "Nicolette Vale", "age": 69, "address": "1842 Sagebrush Bluff Ct", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Mira", "contact_relation": "niece", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out"], "needs": ["pets: cat", "1 more person(s) with them"]}, "script": ["no_answer", [{"answer": "OUT", "people_with_them": 1, "mobility_help": false, "medical_equipment": [], "pets": ["cat"], "where_they_are": "", "quote": "We're out at my niece's place in El Cajon. My husband and I brought our cats.", "responder_note": "Says they are out. 1 other person with them. Animals: cat.", "engine": "Gemini (mock)"}]], "lng": -117.09494, "lat": 32.83478},
      {"id": 12, "name": "Solana Reyes", "age": 78, "address": "2361 Lantern Hollow Rd", "lang": "es", "oxygen": true, "mobility": true, "bedridden": false, "lives_alone": true, "hearing": false, "contact_name": "Dalia", "contact_relation": "daughter", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["wheelchair accessible", "backup power for oxygen concentrators", "no demo shelter also has: pets allowed"], "needs": ["wheelchair or walker: accessible vehicle", "oxygen: bring portable tanks, shelter needs backup power", "pets: dog"]}, "script": ["no_answer", [{"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": true, "medical_equipment": ["oxygen"], "pets": ["dog"], "where_they_are": "", "quote": "No tengo carro y uso oxígeno y andadera. Tengo un perro. Necesito que me ayuden a salir.", "responder_note": "Needs a ride out. Mobility help needed. Uses oxygen. Animals: dog.", "engine": "Gemini (mock)"}]], "lng": -117.1125, "lat": 32.81748},
      {"id": 13, "name": "Mateo Lumbre", "age": 91, "address": "821 Sagebrush Bluff Ct", "lang": "es", "oxygen": true, "mobility": true, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Rafa", "contact_relation": "grandson", "contact_mode": "voice", "assist": {"transport": "ambulance", "shelter": "Sage Hollow Medical Shelter (demo)", "shelter_why": ["wheelchair accessible", "backup power for oxygen concentrators", "medical staff on site"], "needs": ["medical help: ambulance crew", "wheelchair or walker: accessible vehicle", "oxygen: bring portable tanks, shelter needs backup power", "equipment: dialysis"]}, "script": [[{"answer": "NEEDS_MEDICAL", "people_with_them": 0, "mobility_help": false, "medical_equipment": ["dialysis"], "pets": [], "where_they_are": "", "quote": "Me caí y necesito una ambulancia. También hago diálisis.", "responder_note": "Needs medical help. Uses dialysis.", "engine": "Gemini (mock)"}]], "lng": -117.08177, "lat": 32.82084},
      {"id": 14, "name": "Juniper Finch", "age": 74, "address": "1297 Quailsong Way", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": true, "contact_name": "Cedar", "contact_relation": "spouse", "contact_mode": "voice", "assist": {"transport": null, "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["backup power for oxygen concentrators"], "needs": ["staying: plan ready in case they change their mind", "equipment: cpap (needs power)", "hard of hearing: use text or face-to-face, not a loudspeaker"]}, "script": [[{"answer": "STAYING", "people_with_them": 0, "mobility_help": false, "medical_equipment": ["cpap"], "pets": [], "where_they_are": "", "quote": "I'm staying here. My CPAP is here and the chickens need feeding.", "responder_note": "Refusing to leave. Uses cpap.", "engine": "Gemini (mock)"}]], "lng": -117.10211, "lat": 32.82768},
      {"id": 15, "name": "Tomasina Del Sol", "age": 96, "address": "2760 Lark Canyon Pl", "lang": "es", "oxygen": true, "mobility": false, "bedridden": true, "lives_alone": true, "hearing": false, "contact_name": "", "contact_relation": "", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["wheelchair accessible", "backup power for oxygen concentrators"], "needs": ["bedridden: needs a stretcher or lift", "oxygen: bring portable tanks, shelter needs backup power"]}, "script": ["no_answer", "no_answer", "no_answer"], "lng": -117.09996, "lat": 32.81785},
      {"id": 16, "name": "Peregrine Moss", "age": 66, "address": "44 Hummingbird Mesa Dr", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Wren", "contact_relation": "granddaughter", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out"], "needs": []}, "script": [[{"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "We're safe at the shelter with my granddaughter.", "responder_note": "Says they are out.", "engine": "Gemini (mock)"}]], "lng": -117.09175, "lat": 32.82909},
      {"id": 17, "name": "Amalia Cielo", "age": 83, "address": "1905 Copperleaf Ln", "lang": "es", "oxygen": false, "mobility": true, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Belen", "contact_relation": "daughter", "contact_mode": "voice", "assist": {"transport": "wheelchair van", "shelter": "Quail Ridge Community Shelter (demo)", "shelter_why": ["wheelchair accessible", "pets allowed"], "needs": ["wheelchair or walker: accessible vehicle", "pets: 2 cats"]}, "script": ["no_answer", [{"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": true, "medical_equipment": [], "pets": ["2 cats"], "where_they_are": "", "quote": "No puedo caminar y uso silla de ruedas. Tengo dos gatos.", "responder_note": "Needs a ride out. Mobility help needed. Animals: 2 cats.", "engine": "Gemini (mock)"}]], "lng": -117.11051, "lat": 32.8244},
      {"id": 18, "name": "Orion Bellweather", "age": 88, "address": "903 Saltgrass Ridge Rd", "lang": "en", "oxygen": false, "mobility": true, "bedridden": false, "lives_alone": false, "hearing": true, "contact_name": "Pip", "contact_relation": "grandchild", "contact_mode": "text", "assist": {"transport": "wheelchair van", "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["wheelchair accessible"], "needs": ["wheelchair or walker: accessible vehicle", "hard of hearing: use text or face-to-face, not a loudspeaker"]}, "script": [[{"answer": "NEEDS_RIDE", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "2", "responder_note": "Pressed 2: needs a ride out.", "engine": "keypad"}]], "lng": -117.08939, "lat": 32.81603},
      {"id": 19, "name": "Maribel Quill", "age": 71, "address": "52 Lantern Hollow Rd", "lang": "en", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Sol", "contact_relation": "sister", "contact_mode": "voice", "assist": {"transport": null, "shelter": "Mesa Lantern Shelter (demo)", "shelter_why": ["general shelter, no special needs known"], "needs": []}, "script": [[{"answer": "UNCLEAR", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "Maybe later.", "responder_note": "", "engine": "Gemini (mock)"}, {"answer": "UNCLEAR", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": [], "where_they_are": "", "quote": "I'm not sure.", "responder_note": "Answer unclear.", "engine": "Gemini (mock)"}]], "lng": -117.09972, "lat": 32.83699},
      {"id": 20, "name": "Tavio Bramble", "age": 82, "address": "1337 Juniper Echo Ct", "lang": "es", "oxygen": false, "mobility": false, "bedridden": false, "lives_alone": false, "hearing": false, "contact_name": "Lio", "contact_relation": "son", "contact_mode": "voice", "assist": {"transport": null, "shelter": null, "shelter_why": ["already out"], "needs": ["large animals: horses (large-animal trailer)"]}, "script": [[{"answer": "OUT", "people_with_them": 0, "mobility_help": false, "medical_equipment": [], "pets": ["horses"], "where_they_are": "", "quote": "Ya salimos y estamos a salvo en casa de mi hijo en El Cajon. El caballo está con nosotros.", "responder_note": "Says they are out. Animals: horses.", "engine": "Gemini (mock)"}]], "lng": -117.1103, "lat": 32.81271},
    ];
    // GET /api/map as the server builds it (fictional shelters and base); token "" means "draw the fallback map"
    const MAP = {"token": "", "center": [-117.099, 32.824], "zoom": 13, "zone": {"type": "Polygon", "coordinates": [[[-117.0752, 32.824], [-117.07566, 32.82755], [-117.07701, 32.83096], [-117.07921, 32.83411], [-117.08217, 32.83687], [-117.08578, 32.83913], [-117.08989, 32.84081], [-117.09436, 32.84185], [-117.099, 32.8422], [-117.10364, 32.84185], [-117.10811, 32.84081], [-117.11222, 32.83913], [-117.11583, 32.83687], [-117.11879, 32.83411], [-117.12099, 32.83096], [-117.12234, 32.82755], [-117.1228, 32.824], [-117.12234, 32.82045], [-117.12099, 32.81704], [-117.11879, 32.81389], [-117.11583, 32.81113], [-117.11222, 32.80887], [-117.10811, 32.80719], [-117.10364, 32.80615], [-117.099, 32.8058], [-117.09436, 32.80615], [-117.08989, 32.80719], [-117.08578, 32.80887], [-117.08217, 32.81113], [-117.07921, 32.81389], [-117.07701, 32.81704], [-117.07566, 32.82045], [-117.0752, 32.824]]]}, "base": {"name": "Station 0 (demo)", "lat": 32.8252, "lng": -117.0972}, "shelters": [{"name": "Mesa Lantern Shelter (demo)", "short": "Mesa Lantern", "lng": -117.1035, "lat": 32.8262, "wheelchair_accessible": true, "oxygen_power": true, "medical_staff": false, "pets_allowed": false, "large_animals": false, "fictional": true}, {"name": "Quail Ridge Community Shelter (demo)", "short": "Quail Ridge", "lng": -117.0905, "lat": 32.8298, "wheelchair_accessible": true, "oxygen_power": false, "medical_staff": false, "pets_allowed": true, "large_animals": false, "fictional": true}, {"name": "Sage Hollow Medical Shelter (demo)", "short": "Sage Hollow", "lng": -117.1115, "lat": 32.8178, "wheelchair_accessible": true, "oxygen_power": true, "medical_staff": true, "pets_allowed": false, "large_animals": false, "fictional": true}, {"name": "Canyon Lark Equestrian Grounds (demo)", "short": "Canyon Lark", "lng": -117.08, "lat": 32.8335, "wheelchair_accessible": false, "oxygen_power": false, "medical_staff": false, "pets_allowed": true, "large_animals": true, "fictional": true}]};
    const shelterAt = (name) => MAP.shelters.find((x) => x.name === name) || null;
    let residents = [], events = [], startedAt = null, timers = [], gen = 0;
    let autopilot = !PHONE_DEMO;
    const now = () => Date.now() / 1000;
    const rand = (a, b) => a + Math.random() * (b - a);
    const first = (r) => r.name.split(" ")[0];
    const byId = (id) => residents.find((r) => r.id === Number(id));
    const copy = (x) => JSON.parse(JSON.stringify(x));
    const delay = () => new Promise((res) => setTimeout(res, 120));   // feel like a network call

    function fresh() {
      residents = SEED.map((s) => Object.assign({ lang: "en" }, s, { status: "PENDING", attempts: 0, unclear: 0,
        reading: null, family: "", channel: "", updated: now() }));
    }
    function later(sec, fn) {
      if (!isFinite(sec)) return;
      const g = gen;
      timers.push(setTimeout(() => { if (g === gen) fn(); }, sec * 1000));
    }
    function log(r, msg, kind) { events.push({ t: now(), rid: r ? r.id : null, name: r ? r.name : null, kind, msg }); }
    function touch(r, status) { if (status) r.status = status; r.updated = now(); }

    function score(r) {
      const rd = r.reading; let mult = 1; const why = [];
      if (r.age >= 85) { mult += 0.4; why.push("age " + r.age); }
      else if (r.age >= 75) { mult += 0.25; why.push("age " + r.age); }
      const oxyCall = !!(rd && rd.medical_equipment.some((e) => e.toLowerCase().includes("oxygen")));
      if (r.oxygen || oxyCall) { mult += 0.4; why.push("oxygen"); }
      if (r.bedridden) { mult += 0.5; why.push("bedridden"); }
      else if (r.mobility || (rd && rd.mobility_help)) { mult += 0.3; why.push("mobility"); }
      if (r.lives_alone) { mult += 0.2; why.push("lives alone"); }
      if (r.hearing) { mult += 0.15; why.push("hard of hearing"); }
      const extra = rd ? Math.min(rd.people_with_them, 3) : 0;
      if (extra > 0) { mult += 0.1 * extra; why.push("+" + extra + " with them"); }
      return [Math.round(WEIGHT[r.status] * mult), why];
    }

    function textFamily(r) {
      if (!r.contact_name) return;
      const who = r.contact_relation ? r.contact_name + " (" + r.contact_relation + ")" : r.contact_name;
      const body = "Headcount demo: " + FAMILY[r.status].replace("{first}", first(r))
        .replace("{quote}", r.reading ? r.reading.quote : "").replace("{n}", r.attempts);
      r.family = "Texted " + who + " (simulated)";
      log(r, "Texted " + who + " (simulated): " + body, "family");
    }

    // a final outcome for this attempt; in phoneDemo, ring the next resident
    function settled() {
      if (!PHONE_DEMO) return;
      if (residents.some((r) => LIVE.has(r.status))) return;
      const next = residents.find((r) => r.status === "PENDING");
      if (next) later(2.5, () => dial(next));
    }

    function dial(r) {
      if (r.status !== "PENDING" && r.status !== "RETRY_WAIT") return;
      r.attempts += 1; const attempt = r.attempts;
      r.channel = "sim"; r.unclear = 0; touch(r, "CALLING");
      log(r, "Calling (simulated, attempt " + attempt + ").", "info");
      later(RING, () => { if (r.status === "CALLING") noAnswer(r, attempt, "no answer"); });
      const step = r.script[attempt - 1];
      if (autopilot && step && step !== "no_answer") later(rand(2, 4), () => auto(r, attempt, step));
    }
    function noAnswer(r, attempt, reason) {
      if (attempt !== r.attempts || !LIVE.has(r.status)) return;
      if (r.attempts >= MAX_ATTEMPTS) {
        touch(r, "WELFARE_CHECK");
        log(r, "No answer after " + r.attempts + " calls. Welfare check: send a person to " + r.address + ".", "alert");
        textFamily(r);
      } else {
        touch(r, "RETRY_WAIT");
        log(r, "Call " + attempt + " missed (" + reason + "). Retrying in " + GAP + "s.", "warn");
        later(GAP, () => dial(r));
      }
      settled();
    }
    function pickUp(r, attempt) {
      touch(r, "IN_CALL"); log(r, "Picked up (attempt " + attempt + ").", "info");
      later(90, () => { if (r.status === "IN_CALL") noAnswer(r, attempt, "call ended without an answer"); });
    }
    function auto(r, attempt, step) {
      if (attempt !== r.attempts || r.status !== "CALLING") return;
      if (step === "decline") { noAnswer(r, attempt, "declined"); return; }
      pickUp(r, attempt);
      let t = 0;
      step.forEach((reading) => {
        t += rand(1.5, 2.5);
        later(t, () => { if (attempt === r.attempts && r.status === "IN_CALL") respond(r, reading); });
      });
    }
    // returns [say, keep_listening], like engine.respond()
    function respond(r, reading) {
      const lang = r.lang === "es" ? "es" : "en";
      log(r, "Heard: “" + (reading.quote || "(nothing)") + "” (" + (reading.engine || "unknown") + ")", "speech");
      if (reading.answer === "UNCLEAR") {
        r.unclear += 1;
        if (r.unclear >= 2) {
          r.reading = reading; touch(r, "NEEDS_CALLBACK");
          log(r, "Could not understand twice. A person needs to call back.", "warn");
          textFamily(r); settled();
          return [CALLBACK[lang], false];
        }
        r.updated = now();
        return [(r.contact_mode === "text" ? TEXT_ASK_AGAIN : ASK_AGAIN)[lang], true];
      }
      r.reading = reading; touch(r, reading.answer);
      log(r, (EVLABEL[reading.answer] + ". " + (reading.responder_note || reading.quote)).trim(), EVKIND[reading.answer]);
      textFamily(r); settled();
      return [CONFIRM[reading.answer][lang], false];
    }
    // tiny keyword reader for typed answers on the phone page (the live server uses Gemini)
    function readText(text) {
      const t = String(text || "").trim(), low = t.toLowerCase();
      const keypad = { 1: ["OUT", "Pressed 1: says they are out."], 2: ["NEEDS_RIDE", "Pressed 2: needs a ride."],
        3: ["NEEDS_MEDICAL", "Pressed 3: needs medical help."] };
      if (keypad[t]) return R(keypad[t][0], t, keypad[t][1], { engine: "keypad" });
      const rules = [
        ["NEEDS_MEDICAL", /\b(fell|fallen|hurt|injur|bleed|can'?t breathe|ambulance)|me ca[ií]|herid|no puedo respirar|ambulancia/, "Needs medical help."],
        ["NEEDS_RIDE", /\b(ride|no car|can'?t drive|wheelchair|can'?t walk|pick me up)|no tengo carro|transporte|silla de ruedas|no puedo caminar/, "Needs a ride out."],
        ["STAYING", /\b(not leaving|staying|won'?t leave)|me quedo|no me voy/, "Refuses to leave."],
        ["OUT", /\b(out|left|safe|shelter|evacuated)\b|salimos|ya sal[ií]|estamos bien|a salvo|refugio/, "Says they are out."],
      ];
      for (const [answer, re, note] of rules) if (re.test(low)) return R(answer, t, note, { engine: "keywords (mock)" });
      return R("UNCLEAR", t, "", { engine: "keywords (mock)" });
    }
    function liveSim(rid, attempt) {
      const r = byId(rid);
      if (!r || r.channel !== "sim" || r.attempts !== Number(attempt) || !LIVE.has(r.status)) return null;
      return r;
    }

    function reset() { gen += 1; timers.forEach(clearTimeout); timers = []; fresh(); events = []; startedAt = null; }
    function start() {
      reset(); startedAt = now();
      log(null, "Evacuation order received. Calling " + residents.length + " residents.", "start");
      if (PHONE_DEMO) dial(residents[2]);   // Dorothy first; the rest ring one at a time (George and Orion text)
      else residents.forEach((r, i) => later(i * STAGGER, () => dial(r)));
    }
    function snapshot() {
      const counts = {}; let unacc = 0;
      const rows = residents.map((r) => {
        const [s, why] = score(r);
        counts[r.status] = (counts[r.status] || 0) + 1;
        if (UNACC.has(r.status)) unacc += 1;
        return { id: r.id, name: r.name, first: first(r), age: r.age, address: r.address, lang: r.lang,
          status: r.status, attempts: r.attempts, channel: r.channel, score: s, why, reading: r.reading,
          family: r.family, updated: r.updated, real_phone: false, contact_mode: r.contact_mode || "voice",
          lat: r.lat, lng: r.lng,
          assist: r.assist ? Object.assign({}, r.assist, {
            shelter_lat: shelterAt(r.assist.shelter) ? shelterAt(r.assist.shelter).lat : null,
            shelter_lng: shelterAt(r.assist.shelter) ? shelterAt(r.assist.shelter).lng : null }) : null };
      });
      rows.sort((a, b) => (b.score - a.score) || a.name.localeCompare(b.name));
      return { zone: ZONE, total: rows.length, unaccounted: unacc, done: startedAt !== null && unacc === 0,
        started_at: startedAt, max_attempts: MAX_ATTEMPTS, twilio: false, gemini: true, autopilot, mock: true,
        counts, residents: rows, events: events.slice(-200) };
    }

    fresh();
    if (PHONE_DEMO) start();

    return {
      mock: true,
      getState: async () => { await delay(); return copy(snapshot()); },
      start: async () => {
        await delay();
        if (startedAt !== null && residents.some((r) => UNACC.has(r.status))) return { ok: true, already_running: true };
        start(); return { ok: true };
      },
      reset: async () => { await delay(); reset(); return { ok: true }; },
      setAutopilot: async (on) => { await delay(); autopilot = !!on; return { autopilot }; },
      health: async () => ({ ok: true, gemini: true, twilio: false, model: "mock", autopilot, mock: true, demo_rid: null }),
      getMap: async () => copy(MAP),
      getResident: async (rid) => {
        await delay();
        const r = byId(rid);
        if (!r) throw new ApiError(404, "no resident " + rid);
        const row = snapshot().residents.find((x) => x.id === r.id);
        const st = { CALLING: "ringing", IN_CALL: "in-progress" }[r.status] || (r.attempts ? "completed" : null);
        return copy(Object.assign(row, { call_sid: "", attempt: r.attempts, demo: false,
          last_call_status: st ? { status: st, attempt: r.attempts, t: r.updated, call_sid: "" } : null,
          events: events.filter((e) => e.rid === r.id) }));
      },
      callResident: async (rid) => {
        await delay();
        const r = byId(rid);
        if (!r) throw new ApiError(404, "no resident " + rid);
        if (startedAt === null) startedAt = now();
        Object.assign(r, { status: "PENDING", attempts: 0, unclear: 0, reading: null, family: "", channel: "", updated: now() });
        log(r, "Demo: single call requested (simulated)", "start");
        dial(r);
        return { ok: true, real_phone: false };
      },
      simRinging: async () => {
        await delay();
        if (PHONE_DEMO && startedAt !== null && !residents.some((r) => UNACC.has(r.status))) start();   // loop the demo
        return residents.filter((r) => r.channel === "sim" && LIVE.has(r.status)).map((r) => ({
          id: r.id, name: r.name, first: first(r), lang: r.lang, status: r.status, attempt: r.attempts,
          prompt: promptFor(r), contact_mode: r.contact_mode || "voice" }));
      },
      simAnswer: async (rid, attempt) => {
        await delay();
        const r = liveSim(rid, attempt);
        if (!r || r.status !== "CALLING") throw new ApiError(409, "That call is no longer ringing.");
        pickUp(r, r.attempts);
        return { say: promptFor(r) };
      },
      simDecline: async (rid, attempt, reason) => {
        await delay();
        const r = liveSim(rid, attempt);
        if (r) noAnswer(r, r.attempts, reason || "declined");
        return { ok: true };
      },
      simSay: async (rid, attempt, input) => {
        await delay();
        if (input && input.audio) throw new ApiError(400, "Voice needs the live server and a Gemini key. In mock mode, type an answer instead.");
        const r = liveSim(rid, attempt);
        const lang = r && r.lang === "es" ? "es" : "en";
        const reading = readText(input && input.text);
        if (!r) return { say: CALLBACK[lang], keep_listening: false, reading };
        if (r.status === "CALLING") pickUp(r, r.attempts);
        const [say, keep] = respond(r, reading);
        return { say, keep_listening: keep, reading };
      },
    };
  }

  // ------------------------------------------------------------------ polling

  /**
   * Call fn every `ms` milliseconds without overlapping requests.
   * onData(result) on success; onError(error, consecutiveFailures) on failure. Returns {stop, now}.
   */
  function poll(fn, ms, handlers) {
    let timer = null, stopped = false, failures = 0, running = false;
    async function tick() {
      clearTimeout(timer);
      if (stopped || running) return;
      running = true;
      try {
        const data = await fn();
        failures = 0;
        if (!stopped && handlers.onData) handlers.onData(data);
      } catch (e) {
        failures += 1;
        if (!stopped && handlers.onError) handlers.onError(e, failures);
      } finally {
        running = false;
        if (!stopped) timer = setTimeout(tick, ms);
      }
    }
    tick();
    return { stop() { stopped = true; clearTimeout(timer); }, now: tick };
  }

  root.HeadcountAPI = {
    ApiError,
    poll,
    /** create({mock: boolean, phoneDemo?: boolean}) -> client. phoneDemo only matters in mock mode. */
    create(opts) {
      opts = opts || {};
      return opts.mock ? mockClient(opts) : liveClient();
    },
  };
})(window);
