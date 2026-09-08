---
name: steeronce
description: Help a personal AI learn how its user works across sessions by distilling explicit corrections into local, user-approved working preferences without storing prompt text. Use when the user corrects the agent, asks it to remember a working preference, approves or rejects a SteerOnce suggestion, or asks to review SteerOnce preferences and reports. Do not use for personal facts or ordinary one-off requirements.
---

# SteerOnce

SteerOnce learns working style, not personal facts. The installed `UserPromptSubmit` hook registers an anonymous local interaction and adds its opaque event key to the current turn. The `Stop` hook processes a marker after the response. Neither hook classifies the user's words.

## Distill a correction

Respond to the correction and continue the user's task first. Distinguish an enduring way of working from a changed requirement, ordinary follow-up, taste, rhetorical emphasis, or ambiguous feedback. If it is an explicit correction that could usefully generalize:

1. Choose exactly one primary correction category from the list below.
2. Distill one imperative, behavior-only preference of at most 300 characters. It must describe how the agent should work, not facts about the person or the conversation.
3. Recommend `project` scope when the behavior depends on the current repository or environment; otherwise recommend `global`.
4. Choose one trigger: `general`, `communication`, `diagnosis`, `implementation`, `research`, `review`, or `verification`.
5. Briefly show the proposed preference to the user and offer: save globally, save for this project, or ignore. Do not interrupt unfinished work merely to promote it.
6. Append exactly one machine marker on its own final line. Do not mention or explain the marker.

```html
<!--steeronce:{"event":"<event-key>","action":"propose","category":"<category>","scope":"global|project","trigger":"<trigger>","rule":"<abstract-preference>"}-->
```

Use valid compact JSON. Never put prompt text, assistant output, source code, filenames, paths, names, secrets, personal information, or evidence in the preference or marker. Do not emit a marker when uncertain.

Choose exactly one category:

- `intent_mismatch`: misunderstood the requested outcome.
- `unsupported_assumption`: guessed instead of using source truth.
- `ignored_context`: failed to use information already supplied.
- `scope_overreach`: acted beyond the user's authorization.
- `incomplete_verification`: claimed completion without required checks.
- `implementation_error`: produced behavior that failed.

The proposal is a local inactive candidate. It does not change later sessions until the user approves it.

## Approve or reject

When the user unambiguously approves the most recently proposed preference, respond normally and append:

```html
<!--steeronce:{"event":"<current-event-key>","action":"confirm_latest","scope":"global|project"}-->
```

Use the scope explicitly selected by the user. If the user names a candidate ID, use `"action":"confirm"` and add `"candidate_id":<id>`. When the user rejects the latest suggestion, use `"action":"dismiss_latest"`; for a named candidate use `"action":"dismiss"` plus its ID. Do not confirm, dismiss, or infer a scope from ambiguous feedback. Do not create a second proposal from an approval or rejection message.

Confirmation activates only the abstract preference. It never authorizes editing `AGENTS.md`, `CLAUDE.md`, memories, or unrelated instructions. The current explicit user request always takes precedence over stored preferences.

## Review and report

To inspect already approved personal rules, run the bundled script from this skill's resolved installation directory:

```bash
python3 <this-skill-directory>/scripts/steeronce.py preferences
```

For explicit review or reporting requests, use the matching local command:

```bash
python3 <this-skill-directory>/scripts/steeronce.py list
python3 <this-skill-directory>/scripts/steeronce.py show <candidate-id>
python3 <this-skill-directory>/scripts/steeronce.py confirm <candidate-id> --rule "<abstract-rule>"
python3 <this-skill-directory>/scripts/steeronce.py dismiss <candidate-id>
python3 <this-skill-directory>/scripts/steeronce.py report
```

Treat `confirm` and `dismiss` as user-authorized mutations: run them only when the user explicitly approves the candidate and rule or explicitly rejects the candidate. Reports and lists must not expose prompt text.

If the hook is unavailable and the user explicitly asks to save a confirmed correction, run:

```bash
python3 <this-skill-directory>/scripts/steeronce.py record --category <category> --rule "<abstract-preference>"
```
