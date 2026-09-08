# SteerOnce

English | [简体中文](README.zh-CN.md)

**Stop correcting your coding agent twice.**

SteerOnce turns corrections you approve into private, reusable rules for Codex. The Codex model already answering your turn understands whether you are correcting it; SteerOnce stores only its category and opaque event metadata, then loads your approved abstract rules in later sessions.

No account. No server. No extra model call. No dependencies. No prompt text or text fingerprint in the database.

```text
you correct Codex
       ↓
current Codex model → category → candidate → human review → optional rule
                                              ↓
                               later-session correction rate
```

## Install

Prerequisites: Codex CLI or the ChatGPT desktop app with Codex, plus Python 3.9 or newer.

From GitHub:

```bash
codex plugin marketplace add sophialeeee/steeronce --ref main
codex plugin add steeronce@steeronce
```

Restart the ChatGPT desktop app or start a new Codex session. To review changed hooks, launch `codex` in a terminal, enter `/hooks`, inspect the two SteerOnce hooks, and trust their exact definitions.

Optional terminal command:

```bash
python3 -m pip install .
steeronce doctor
```

## What you get

The `UserPromptSubmit` hook gives each submitted turn an opaque local event key. The current Codex model uses the full conversational meaning—not a keyword table—to mark explicit corrections. This reuses the model already handling the turn, so SteerOnce makes no second model or network request. The `SessionStart` hook injects only user-approved abstract rules; the current request always wins.

```bash
steeronce list
steeronce show 1
steeronce confirm 1 --rule "Use supplied API definitions before inferring fields."
steeronce dismiss 2
steeronce report
steeronce report --json
steeronce rules
```

Example report:

```text
assistant_turns=200
candidate_corrections=18
confirmed_corrections=12
confirmed_per_100_turns=6.00
unsupported_assumption=7
intent_mismatch=5
before_rules_candidate_per_100_turns=8.20
after_rules_candidate_per_100_turns=3.10
```

These are personal, observational metrics—not a model benchmark or proof that a rule caused the change.

## Why this is deliberately small

SteerOnce is not another agent-memory framework. It closes one loop: correction, human approval, reusable local rule, and later-session measurement.

| | SteerOnce |
|---|---|
| Runtime | One Python standard-library file |
| Capture | Codex hook plus current-turn semantic classification |
| Stored conversation text | None |
| Stored text fingerprint | None |
| Rule activation | Human approval only |
| Extra model/network calls | None |
| Output | Review queue, terminal report, aggregate JSON |

See [PRIVACY.md](PRIVACY.md) for the exact storage and threat boundary.

## Categories

- `intent_mismatch`: misunderstood the requested outcome.
- `unsupported_assumption`: guessed instead of using source truth.
- `ignored_context`: failed to use information already supplied.
- `scope_overreach`: acted beyond authorization.
- `incomplete_verification`: claimed completion without required checks.
- `implementation_error`: produced behavior that failed.

## Historical backfill

The hook starts semantic classification after installation. To count turns in existing Codex JSONL sessions locally:

```bash
steeronce scan ~/.codex/sessions
```

Historical scanning does not classify old text. `show <id>` remains available for legacy candidates: it reads a short preview from the original local transcript only when explicitly requested and never copies that preview into SteerOnce's database. New semantic candidates contain no transcript location or preview.

Unreviewed candidates created by the retired phrase detector remain in SQLite for recoverability but are excluded from the default list and report. Use `steeronce list --include-legacy` only if you want to inspect them.

## Limits

- Semantic classification can still be wrong, so candidates require human review before becoming rules.
- Old sessions can be counted but cannot be semantically backfilled without sending their text through a model; SteerOnce deliberately does not do that.
- The before/after report is directional; task mix and small samples matter.
- The plugin currently supports Codex only.
- Approved rules are instructions, not guaranteed behavior changes.

The useful next contributions are privacy-preserving adapters for other coding agents, better review UX, and better recurrence measurement—not a bigger framework.

## Troubleshooting

- No candidates appear: launch `codex` in a terminal, enter `/hooks`, review and trust the plugin hooks, then start a new session.
- A candidate is wrong: run `steeronce dismiss <id>`. Semantic classification intentionally requires human review.
- Rules do not load: confirm that the event has a non-empty approved rule, then start a new session; `steeronce rules` shows what is eligible.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/steeronce
```

The database defaults to `~/.local/share/steeronce/corrections.db`; pass `--db PATH` for an isolated run. On first use, an existing CorrectionKit database is copied forward without deleting the original.

## Contributing

Open an issue for a false positive, missed correction, or unclear category. Do not include private transcript text, source code, or secrets. Pull requests should include one focused test.

## License

[MIT](LICENSE)
