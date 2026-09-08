# Privacy boundary

SteerOnce is designed for a single user on a trusted local machine. It makes no additional model or network calls and has no telemetry endpoint. The Codex model already processing the current turn distills the working preference because it already has the conversation context. SteerOnce does not fine-tune or modify model weights.

## Stored in SQLite

- UTC timestamps;
- one of six correction categories;
- confidence, review status, and detector version;
- opaque event keys derived from local metadata, not message text;
- local transcript paths and line numbers for legacy opt-in review;
- inactive and user-approved abstract working preferences;
- preference scope (`global` or `project`) and a coarse trigger;
- one-way hashes of local working directories for project scope;
- aggregate per-session turn and rule-load counters.

The database and its parent directory are created with user-only permissions where the operating system supports them.

## Never copied into SQLite

- user prompts or assistant responses;
- source code or tool output;
- secrets or personal information from messages;
- embeddings;
- deterministic fingerprints of message text.

The `UserPromptSubmit` hook returns only an opaque event key as hidden turn context. When the current Codex model determines that the message is an explicit correction, it produces a behavior-only abstraction and shows that abstraction to the user. A machine-readable copy is placed in an HTML comment in the assistant response. The local `Stop` hook validates the current event key and stores only the abstraction, category, scope, and trigger. No prompt text is passed to the hook or copied into SQLite.

The HTML marker is part of the original Codex transcript even when the rendered interface hides it. It contains the same abstract preference shown to the user, not the user's prompt. A candidate remains inactive until the user explicitly approves it. Project scope stores a hash of the working directory, not the path itself.

`show <id>` is the explicit exception to zero-content processing for legacy candidates: it reads up to 2,000 characters directly from the original local Codex transcript for review. The preview is printed to the terminal and is not saved by SteerOnce. New semantic candidates have no source path or preview.

Unreviewed candidates created by the retired phrase detector remain recoverable in SQLite but are excluded from default lists and metrics. `list --include-legacy` exposes them explicitly.

## What this does not protect against

SteerOnce does not change what the active Codex model can see; it already receives the user's current message. The model can still produce a poor abstraction or accidentally include identifying detail, which is why preferences are shown for review before activation. SteerOnce does not protect data from an attacker who can already read your Codex transcripts, terminal output, or user account. Legacy local transcript paths can themselves reveal usernames or project names. Delete the SQLite database to remove SteerOnce's retained metadata; this does not delete the original Codex transcripts.
