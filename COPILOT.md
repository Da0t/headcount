# How we used GitHub Copilot

This is a working log for the **Best Use of GitHub Copilot** track. The teammate using Copilot adds a row **as they work**, while it's fresh. Only real interactions go here: if Copilot didn't do it, it doesn't get written down.

How to add an entry:
1. Note the time (PT) and which file or task you were on.
2. Write what you asked Copilot (chat prompt, inline comment, or "accepted a completion").
3. Write what it produced, in a sentence.
4. Write what we kept, changed, or threw away, and why. Rejections count too: they show judgment.

## Log

| Time (PT) | File / task | What we asked Copilot | What it did | What we kept or changed |
|---|---|---|---|---|
| 13:13 PT | `app/engine.py`, stale Twilio callbacks | Explain how a late webhook from an old call is prevented from overwriting a newer answer. | Traced the per-call attempt token and the guards on call-state updates. | Added the explanation under Learn; no application code changed. |
| 13:15 PT | `tests/test_classify_extra.py` | Add non-duplicate keyword classification and extraction cases, including difficult English and Spanish wording. | Added phrase, negation, mixed-signal, curly-apostrophe, uppercase, and extraction tests; marked negated English and Spanish injury cases xfail because they currently classify as medical. | Kept the regression cases as xfail and omitted cases already covered in `tests/test_classify.py`. |
| 13:21 PT | `tests/test_classify_extra.py`, `app/classify.py` | Promote the negated-injury xfails after the classifier fix. | Removed the xfail markers so the Spanish and English negated-injury cases run as regular regression tests. | Kept both cases as normal tests against the fix in `app/classify.py`. |
| 13:25 PT | `app/engine.py`, async task scheduling review | Review task cancellation, stale attempts, reset, autopilot, and family texts for races. | Found a stale-attempt collision after reset, in-flight Twilio work that can outlive reset, and scheduled autopilot tasks that can continue after autopilot is switched off. | No application code changed; recorded findings with severity and line references under Solve. |
| 13:32 PT | `app/priority.py`, `COPILOT.md` | Explain the priority formula with a worked example and record the engine-review fixes. | Added module and function docstrings, updated Solve and Document, and logged this work. | Kept the change to documentation only; no application logic changed. |
| 13:50 PT | `app/seed.py`, campaign tests | Expand the fictional demo zone to 20 residents and update the campaign totals. | Added ten varied fictional residents covering every outcome with keyword-classifiable scripts, and updated the old total assertions. | Kept residents 1 to 10 unchanged; expected totals are 7 OUT, 6 NEEDS_RIDE, 2 NEEDS_MEDICAL, 2 STAYING, 2 WELFARE_CHECK, and 1 NEEDS_CALLBACK. |
| 14:30 PT | `docs/ARCHITECTURE.md`, `app/accessibility.py`, `app/main.py` | Document the verified outbound and inbound call flows, state statuses, AI and rules, map data, and file layout; clarify the accessibility and inbound-step docstrings. | Wrote a plain-language architecture guide and expanded the requested docstrings without changing application logic. | Kept the guide grounded in the routes and engine behavior; identified all place and shelter data as fictional Tierrasanta demo data. |
| 14:55 PT | `app/static/og-image.svg`, `app/static/board.html`, `app/static/phone.html`, `docs/BRAND.md` | Create the social share card and add sharing metadata to the board and phone simulator. | Added a 1200×630 branded SVG card, Open Graph and Twitter card tags, and brand documentation. | Kept the card to brand colors, reused the logo-mark paths, and stated that Tierrasanta demo residents are fictional. |

## Learn
*Where Copilot helped us understand something new: an API, a library, an unfamiliar error.*

- `_dial` increments and captures the call attempt (`app/engine.py:122, 126–127`); `no_answer` (`164–167`), `answered` (`181–184`), and `respond` (`193–199`) reject events whose attempt is not current or whose call is no longer live. Thus late status, voice, or gather callbacks cannot change a newer call's state or answer. `_dial` also saves the returned Twilio SID only if that attempt is still current and live (`140–144`). The Twilio handlers pass the attempt through at `app/main.py:189–200, 238–242`.

## Solve
*Where Copilot helped write or fix code. Link the file and say what part was Copilot's.*

- The xfail tests found that negated injuries ("No me caí", "haven't fallen or been hurt") were misclassified as NEEDS_MEDICAL by the keyword fallback. The team fixed `app/classify.py`, and I converted the xfails into regular regression tests.
- The engine review found a high-severity stale-callback risk: reset clears attempt counters, so an old callback can match a new live attempt (`app/engine.py:107-110, 122-128, 164-199`). It also found medium-severity reset and autopilot races: in-flight Twilio calls or texts can outlive reset, and an already-scheduled autopilot task does not check whether autopilot was switched off (`app/engine.py:135, 151-155, 230-255, 256-272`). No application code changed.
- The team fixed the three engine-review findings in commit `1054de6`: attempt reuse after reset, in-flight family text after reset, and autopilot not stopping. Regression tests cover the fixes.
- Expanded `app/seed.py` from 10 to 20 fictional demo residents with English and Spanish scripts, varied medical and mobility needs, companions, pets, a deaf text respondent, and examples for every outcome. The team corrected Maribel's language to English and the counted-pet expectation to "2 cats" during review. The expected final counts are 7 OUT, 6 NEEDS_RIDE, 2 NEEDS_MEDICAL, 2 STAYING, 2 WELFARE_CHECK, and 1 NEEDS_CALLBACK.

## Test
*Where Copilot helped write or extend tests, or found an edge case we missed.*

- Added `tests/test_classify_extra.py` for tricky English and Spanish wording, negations, mixed signals, curly apostrophes, uppercase input, and companion, pet, and medical-equipment extraction. The negated English and Spanish injury cases were converted from xfails into regular regression tests after the classifier fix; existing cases were not repeated.

## Document
*Where Copilot helped write docs, docstrings, comments, or this README.*

- Added the module and `score()` docstrings in `app/priority.py`, explaining the priority formula, its factors, and a worked example.
- Added `docs/ARCHITECTURE.md` (outbound and inbound lifecycle, status transitions, Gemini versus plain rules, map data flow, and file map) and clarified docstrings for accessibility assistance, shelter choice, and `_inbound_step`.
- Added `app/static/og-image.svg`, a 1200×630 social share card with the Headcount mark and wordmark, service tagline, and fictional Tierrasanta demo note; added Open Graph, Twitter card, and theme-color metadata to the heads of `board.html` and `phone.html`, and documented the card in `docs/BRAND.md`.

## What we learned about working with Copilot

*Our rule: Gemini and Copilot can help, but plain, tested code decides who gets help.*

- **Where it saved time:** finding problems we weren't looking for. Its extra classifier tests caught a real bug (negated injuries like "No me caí" read as medical emergencies), and its engine review found three real issues: attempt numbers reused after a reset, a family text finishing after a reset, and autopilot not stopping when switched off. Each was fixed by the team with a regression test.
- **How we kept it safe:** we ran Copilot CLI with file edits and git allowed but no other shell commands, and gave each task a list of the files it may touch. Copilot commits only its own work, with its own co-author trailer.
- **How we checked its output:** it couldn't run the tests itself, so we ran `pytest` after every Copilot change before pushing, and read its diffs. Its review findings were confirmed against the code before we fixed them.
- **Where we had to correct it:** we told it to use punctuation that matches our style guide, and once it stashed a teammate's uncommitted files during a pull (it restored them correctly, but we now pull with `--autostash`). We also entered wrong times for its first log rows and had it correct them from the commit history.
- **What we'd do differently:** bring it in earlier. We started using it after the core was built, and its review found bugs that would have been cheaper to catch on day one.
