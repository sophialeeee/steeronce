---
name: steeronce
description: Turn explicit user corrections during AI-assisted work into local, user-approved SteerOnce rules without storing prompt text. Use when the user says the agent misunderstood intent, guessed without evidence, ignored supplied context, exceeded authorization, skipped verification, or produced a broken implementation.
---

# SteerOnce

The installed `UserPromptSubmit` hook registers an anonymous local interaction and adds its opaque SteerOnce event key to the current turn. It does not classify the user's words. Use your understanding of the conversation to decide whether the user is explicitly correcting the agent's behavior or output.

Respond to the user's correction first. If it is an explicit correction, choose exactly one primary category and mark the event:

```bash
python3 <this-skill-directory>/scripts/steeronce.py mark <event-key> --category <category>
```

Do not mark a changed requirement, ordinary follow-up, disagreement of taste, rhetorical emphasis without a correction, or ambiguous feedback. If uncertain, do not mark it. Never pass conversation text, code, filenames, secrets, personal information, rule text, or other evidence to the command. Only the opaque event key and category are allowed.

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

Marking creates a local candidate; it does not approve or activate a rule. It also does not authorize editing `AGENTS.md`, `CLAUDE.md`, memories, or other instructions. When a correction clearly generalizes, suggest a short durable rule without exposing private context, and obtain user approval before saving it. Never interrupt the current task merely to promote a rule. Confirmed rules are loaded by the `SessionStart` hook.
