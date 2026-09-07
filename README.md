# CorrectionKit

English | [简体中文](README.zh-CN.md)

**How often do you have to correct Codex?**

CorrectionKit is a tiny, local-first correction counter for Codex. A native hook notices explicit corrections such as “don't guess” or “that's not what I meant,” stores only a category and opaque event metadata, and shows whether your correction burden changes after you approve a rule.

No account. No server. No background model. No dependencies. No prompt text or text fingerprint in the database.

```text
you correct Codex
       ↓
local phrase match → candidate → human review → optional rule
                                              ↓
                               later-session correction rate
```

## Install

Prerequisites: Codex CLI or the ChatGPT desktop app with Codex, plus Python 3.9 or newer.

From GitHub:

```bash
codex plugin marketplace add sophialeeee/correction-kit --ref main
codex plugin add correction-kit@correction-kit
```

Restart the ChatGPT desktop app or start a new Codex session. Then open `/hooks`, inspect the two CorrectionKit hooks, and trust them. Codex intentionally skips new or changed non-managed hooks until you approve their exact definition.

Optional terminal command:

```bash
python3 -m pip install .
correction-kit doctor
```

## What you get

The `UserPromptSubmit` hook counts every submitted turn and classifies explicit corrections using deterministic Chinese and English phrases. The `SessionStart` hook injects only user-approved abstract rules; the current request always wins.

```bash
correction-kit list
correction-kit show 1
correction-kit confirm 1 --rule "Use supplied API definitions before inferring fields."
correction-kit dismiss 2
correction-kit report
correction-kit report --json
correction-kit rules
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

CorrectionKit is not another agent-memory framework. It does one job: make correction burden visible with the smallest trustworthy local mechanism.

| | CorrectionKit |
|---|---|
| Runtime | One Python standard-library file |
| Capture | Automatic Codex lifecycle hook |
| Stored conversation text | None |
| Stored text fingerprint | None |
| Rule activation | Human approval only |
| Network calls | None |
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

The hook starts counting after installation. To scan existing Codex JSONL sessions locally:

```bash
correction-kit scan ~/.codex/sessions
```

`show <id>` reads a short preview from the original local transcript only when explicitly requested. It never copies that preview into CorrectionKit's database.

## Limits

- v0.1 recognizes a small deterministic phrase list, so candidates need review.
- The before/after report is directional; task mix and small samples matter.
- The plugin currently supports Codex only.
- Approved rules are instructions, not guaranteed behavior changes.

The useful next contributions are new language phrases backed by real false-negative examples, privacy-preserving adapters for other coding agents, and better recurrence measurement—not a bigger framework.

## Troubleshooting

- No candidates appear: open `/hooks`, review the plugin hook, and trust it. Then start a new session.
- A candidate is wrong: run `correction-kit dismiss <id>`. Deterministic matching intentionally requires human review.
- Rules do not load: confirm that the event has a non-empty approved rule, then start a new session; `correction-kit rules` shows what is eligible.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/correction-kit
```

The database defaults to `~/.local/share/correction-kit/corrections.db`; pass `--db PATH` for an isolated run.

## Contributing

Open an issue with the false positive or missed correction category before expanding the phrase list. Do not include private transcript text, source code, or secrets. Pull requests should include one focused test.

## License

[MIT](LICENSE)
