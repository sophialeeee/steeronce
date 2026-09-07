---
name: steeronce
description: Turn explicit user corrections during AI-assisted work into local, user-approved SteerOnce rules without storing prompt text. Use when the user says the agent misunderstood intent, guessed without evidence, ignored supplied context, exceeded authorization, skipped verification, or produced a broken implementation.
---

# SteerOnce

The installed `UserPromptSubmit` hook records a local candidate when the user explicitly corrects the agent. Do not record it again from the skill. Respond to the correction first; never interrupt the user's work to promote a rule.

To inspect already approved personal rules, run the bundled script from this skill's resolved installation directory:

```bash
python3 <this-skill-directory>/scripts/steeronce.py rules
```

If the hook is unavailable and the user explicitly asks to save a confirmed correction, run:

```bash
python3 <this-skill-directory>/scripts/steeronce.py record --category <category>
```

Choose exactly one category:

- `intent_mismatch`: misunderstood the requested outcome.
- `unsupported_assumption`: guessed instead of using source truth.
- `ignored_context`: failed to use information already supplied.
- `scope_overreach`: acted beyond the user's authorization.
- `incomplete_verification`: claimed completion without required checks.
- `implementation_error`: produced behavior that failed.

Do not record a changed requirement, ordinary follow-up, disagreement of taste, or ambiguous feedback. Do not pass conversation text, code, filenames, secrets, personal information, or other evidence to the command. The event is metadata-only and local.

Recording a correction does not authorize editing `AGENTS.md`, `CLAUDE.md`, memories, or other instructions. Suggest a durable rule only after the same confirmed category recurs, and obtain user approval before saving it. Confirmed rules are loaded by the `SessionStart` hook.
