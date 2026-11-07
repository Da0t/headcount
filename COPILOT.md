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
| 13:35 PT | `app/engine.py`, stale Twilio callbacks | Explain how a late webhook from an old call is prevented from overwriting a newer answer. | Traced the per-call attempt token and the guards on call-state updates. | Added the explanation under Learn; no application code changed. |
| 13:45 PT | `tests/test_classify_extra.py` | Add non-duplicate keyword classification and extraction cases, including difficult English and Spanish wording. | Added phrase, negation, mixed-signal, curly-apostrophe, uppercase, and extraction tests; marked negated English and Spanish injury cases xfail because they currently classify as medical. | Kept the regression cases as xfail and omitted cases already covered in `tests/test_classify.py`. |
| 14:05 PT | `tests/test_classify_extra.py`, `app/classify.py` | Promote the negated-injury xfails after the classifier fix. | Removed the xfail markers so the Spanish and English negated-injury cases run as regular regression tests. | Kept both cases as normal tests against the fix in `app/classify.py`. |

## Learn
*Where Copilot helped us understand something new: an API, a library, an unfamiliar error.*

- `_dial` increments and captures the call attempt (`app/engine.py:122, 126–127`); `no_answer` (`164–167`), `answered` (`181–184`), and `respond` (`193–199`) reject events whose attempt is not current or whose call is no longer live. Thus late status, voice, or gather callbacks cannot change a newer call's state or answer. `_dial` also saves the returned Twilio SID only if that attempt is still current and live (`140–144`). The Twilio handlers pass the attempt through at `app/main.py:189–200, 238–242`.

## Solve
*Where Copilot helped write or fix code. Link the file and say what part was Copilot's.*

- The xfail tests found that negated injuries ("No me caí", "haven't fallen or been hurt") were misclassified as NEEDS_MEDICAL by the keyword fallback. The team fixed `app/classify.py`, and I converted the xfails into regular regression tests.

## Test
*Where Copilot helped write or extend tests, or found an edge case we missed.*

- Added `tests/test_classify_extra.py` for tricky English and Spanish wording, negations, mixed signals, curly apostrophes, uppercase input, and companion, pet, and medical-equipment extraction. The negated English and Spanish injury cases were converted from xfails into regular regression tests after the classifier fix; existing cases were not repeated.

## Document
*Where Copilot helped write docs, docstrings, comments, or this README.*

-

## What we learned about working with Copilot

*Fill in at the end: where it saved time, where we had to correct it, and how we checked its output. (Our rule: Gemini and Copilot can help, but plain, tested code decides who gets help.)*

-
