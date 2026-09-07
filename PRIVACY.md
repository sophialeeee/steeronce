# Privacy boundary

CorrectionKit is designed for a single user on a trusted local machine. It makes no network calls and has no telemetry endpoint.

## Stored in SQLite

- UTC timestamps;
- one of six correction categories;
- confidence, review status, and detector version;
- opaque event keys derived from local metadata, not message text;
- local transcript paths and line numbers for opt-in review;
- user-approved abstract rules;
- aggregate per-session turn and rule-load counters.

The database and its parent directory are created with user-only permissions where the operating system supports them.

## Never copied into SQLite

- user prompts or assistant responses;
- source code or tool output;
- secrets or personal information from messages;
- embeddings;
- deterministic fingerprints of message text.

`show <id>` is the explicit exception to zero-content processing: it reads up to 2,000 characters directly from the original local Codex transcript for review. The preview is printed to the terminal and is not saved by CorrectionKit.

## What this does not protect against

CorrectionKit does not protect data from an attacker who can already read your Codex transcripts, terminal output, or user account. Local transcript paths can themselves reveal usernames or project names. Delete the SQLite database to remove CorrectionKit's retained metadata; this does not delete the original Codex transcripts.
