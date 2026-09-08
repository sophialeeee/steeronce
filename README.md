# SteerOnce

English | [简体中文](README.zh-CN.md)

**Your AI should learn how you work.**

SteerOnce turns your corrections into private working preferences that follow Codex across sessions. The model already answering your turn distills how it should behave next time; you choose whether that preference applies globally, only to the current project, or not at all.

It is a transparent preference layer, not model fine-tuning: no account, server, extra model call, dependencies, prompt storage, embeddings, or text fingerprints.

```text
you correct Codex → model distills a working preference
                                  ↓
                  save globally / this project / ignore
                                  ↓
                 relevant preference loads next session
```

## Install

Prerequisites: Codex CLI or the ChatGPT desktop app with Codex, plus Python 3.9 or newer.

From GitHub:

```bash
codex plugin marketplace add sophialeeee/steeronce --ref main
codex plugin add steeronce@steeronce
```

Restart the ChatGPT desktop app or start a new Codex session. To review changed hooks, launch `codex` in a terminal, enter `/hooks`, inspect the three SteerOnce hooks, and trust their exact definitions.

Optional terminal command:

```bash
python3 -m pip install .
steeronce doctor
```

## What you get

The `UserPromptSubmit` hook gives each submitted turn an opaque local event key. The current Codex model uses the full conversation—not a keyword table—to distinguish a durable working preference from a one-off request. It shows the abstraction for review and emits a machine marker. The local `Stop` hook stores that abstraction as an inactive candidate. The `SessionStart` hook loads only approved global preferences and preferences matching the current project's hashed path. The current request always wins.

Example:

```text
You: I asked for a diagnosis, not an edit.
Codex: ...
SteerOnce suggestion:
“Diagnose first; do not edit files unless the user asks.”
Save globally / for this project / ignore?
```

```bash
steeronce list
steeronce show 1
steeronce confirm 1 --scope project
steeronce dismiss 2
steeronce report
steeronce report --json
steeronce preferences
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

SteerOnce does not try to remember every personal fact or transcript. It closes one auditable loop: correction, behavior-only abstraction, human-approved scope, relevant cross-session loading, and later measurement.

| | SteerOnce |
|---|---|
| Runtime | One Python standard-library file |
| Learning signal | Explicit corrections and approvals |
| Stored semantic content | Abstract working preference only |
| Project identity | One-way hash of the local working directory |
| Stored conversation text | None |
| Stored text fingerprint | None |
| Preference activation | Human approval only |
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

Preferences additionally carry a scope (`global` or `project`) and a trigger such as `diagnosis`, `implementation`, or `research`. Project preferences load only when the next session starts from the same working directory.

## Historical backfill

The hook starts semantic classification after installation. To count turns in existing Codex JSONL sessions locally:

```bash
steeronce scan ~/.codex/sessions
```

Historical scanning does not classify old text. `show <id>` remains available for legacy candidates: it reads a short preview from the original local transcript only when explicitly requested and never copies that preview into SteerOnce's database. New semantic candidates contain no transcript location or preview.

Unreviewed candidates created by the retired phrase detector remain in SQLite for recoverability but are excluded from the default list and report. Use `steeronce list --include-legacy` only if you want to inspect them.

## Limits

- Semantic distillation can still be wrong, so candidates require human review before becoming active preferences.
- Old sessions can be counted but cannot be semantically backfilled without sending their text through a model; SteerOnce deliberately does not do that.
- The before/after report is directional; task mix and small samples matter.
- The plugin currently supports Codex only.
- This changes model context, not model weights. Approved preferences improve guidance but cannot guarantee behavior.

The useful next contributions are privacy-preserving adapters for other coding agents, better review UX, and better recurrence measurement—not a bigger framework.

## Troubleshooting

- No candidates appear: launch `codex` in a terminal, enter `/hooks`, review and trust all three plugin hooks, then start a new session.
- A candidate is wrong: run `steeronce dismiss <id>`. Semantic classification intentionally requires human review.
- Preferences do not load: confirm that the candidate has a non-empty approved preference, then start a new session; `steeronce preferences` shows what is eligible.

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
