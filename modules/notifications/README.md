# Notifications Module (`modules/notifications`)
<!-- version: 0.1.0 -->

Durable, provider-neutral notification broker and incident lifecycle management system for the `scripts` repository.

## Capabilities

- **Versioned Event Models (`EventEnvelopeV1`)**: Typed, validated notification envelopes with deterministic identity, strict timestamps, and opaque reference safety.
- **Durable SQLite Journal & Outbox**: ACID-compliant persistence using SQLite WAL mode, foreign keys, bounded busy timeouts, and automatic schema migrations.
- **Incident State Machine**: Complete tracking of `open`, `update`, `acknowledge`, `resolve`, and `reopen` states. Decouples operator acknowledgement from verified resolution.
- **Provider-Neutral Outbox**: Asynchronous delivery worker with exponential backoff, jitter, maximum retry limits, and dead-letter detection. Supports Telegram Bot API delivery (Phase 02) and `FakeProvider` for testing.
- **Secure Local Ingestion**: Python in-process publisher API and token-authenticated loopback HTTP service (`127.0.0.1:<port>`) with bounded timeouts ensuring zero blocking of safety-critical producers.
- **Telegram Android Delivery**: First-class Telegram Bot API adapter delivering alerts to Android over regular internet connectivity without VPN dependency. Enforces strict token redaction in URLs, traces, and error logs.
- **CLI (`scripts-notify`)**: Full-featured diagnostic and management interface supporting structured JSON output (`-j/--json`), file inputs (`-f/--file`), explicit mutation controls (`-a/--apply`), and Telegram enrollment commands.

## Command Line Usage

```bash
# Display general help
scripts-notify --help

# Publish an event from JSON string or file
scripts-notify publish -j '{"schema_version": 1, "event_id": "...", ...}'
scripts-notify publish -f event.json

# List active incidents
scripts-notify incidents list -j

# Acknowledge an incident
scripts-notify incidents acknowledge -i <incident-id> -a

# Inspect outbox delivery status
scripts-notify outbox list -j

# Enroll and test Telegram bot delivery
scripts-notify telegram enroll -t <BOT_TOKEN> -c <CHAT_ID> -a
scripts-notify telegram status
scripts-notify telegram test -a

# Health check & diagnostics
scripts-notify health -j
```
