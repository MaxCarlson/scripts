# Telegram Android Delivery Setup & Enrollment Guide (Phase 02)

This document provides operator instructions for enrolling, verifying, and managing the Telegram delivery provider for the `scripts` repository notification system.

---

## 1. Security Architecture & Threat Model

### Cloud Chats vs End-to-End Encryption
Telegram bot chats are **cloud chats** stored on Telegram's infrastructure. They are **not** Secret Chats and are **not** end-to-end encrypted.
- **Never transmit**: Bearer tokens, passwords, SSH keys, session secrets, private file paths, or detailed Resource Coordinator safety evidence.
- **Transmitted content**: Concise, plain-text incident alerts (severity, headline, timestamp, incident ID, and an optional authenticated dashboard HTTPS link).
- **No Command Execution**: The Telegram bot is strictly a **one-way delivery transport**. It does not accept inbound recovery commands or interactive execution.

### Distinction from HealthchecksBot (Phase 04)
- **Alert Bot (Phase 02)**: Your private, operator-created Telegram bot sending notifications directly from the Windows workstation broker outbox.
- **HealthchecksBot (Phase 04)**: An independent external bot provided by Healthchecks.io that notifies you if the Windows workstation goes entirely offline or loses internet connectivity.

---

## 2. Operator Setup Workflow

### Step 1: Create your Private Alert Bot
1. Open the Telegram app on your phone or desktop.
2. Search for the verified official `@BotFather` bot.
3. Send `/newbot`.
4. Choose a friendly name (e.g. `Max Scripts Alert Bot`).
5. Choose a username ending in `bot` (e.g. `max_scripts_notify_bot`).
6. `@BotFather` will reply with your API token:
   ```text
   Use this token to access the HTTP API:
   123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789
   ```

### Step 2: Initialize Chat with your Bot
1. Search for your newly created bot in Telegram by its `@username`.
2. Open the conversation and click **START** (which sends `/start`).
3. The bot will not reply (since it is a one-way notification bot), but this authorizes the bot to message your account.

### Step 3: Discover your Chat ID
You need your numeric private chat ID:
- **Option A (Browser/curl)**:
  Open in a browser (or run via curl):
  ```text
  https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
  ```
  Look for `"chat":{"id":123456789,...}` in the JSON response.
- **Option B (Telegram Bot)**:
  Forward any message to `@userinfobot` in Telegram to see your numeric account ID.

### Step 4: Secure Local Enrollment
Enroll the bot token and chat ID using `scripts-notify`:

```powershell
# 1. Preview enrollment (dry-run, requires no changes)
scripts-notify telegram enroll -t "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789" -c "987654321"

# 2. Interactive enrollment (recommended: avoids saving token in shell history)
scripts-notify telegram enroll -c "987654321" -a

# 3. Explicit command-line enrollment with -a/--apply:
scripts-notify telegram enroll -t "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789" -c "987654321" -a
```

*Note: Flags support both short (`-t`, `-c`, `-a`) and long forms (`--token`, `--chat-id`, `--apply`).*

The credentials are saved to:
`%LOCALAPPDATA%\scripts\notifications\secrets\telegram.json`

On Windows, `icacls` restricts this file so only your user SID and `LocalSystem` can read it.

### Step 5: Verify Enrollment Status

```powershell
scripts-notify telegram status
```

Output:
```text
Telegram provider: Enrolled (Chat ID: 987654321, Token: 123456...789)
```

*(Notice the bot token is permanently redacted in all CLI outputs, logs, and diagnostics.)*

---

## 3. End-to-End Acceptance Test

### Cellular VPN-Disconnected Verification
To verify that notifications reach your Android device regardless of workstation LAN state:

1. On your Android phone, **disconnect WireGuard, Tailscale, or local Wi-Fi**.
2. Verify phone is operating over standard cellular data (LTE/5G).
3. Send a single test notification from the Windows workstation:

```powershell
scripts-notify telegram test --apply
```

4. Confirm that:
   - Your Android device sounds/vibrates with a notification from your Alert Bot.
   - The message headline matches:
     ```text
     [INFO] [SCRIPTS-NOTIFY] Test Notification

     This is a test notification verifying Telegram Bot delivery.
     Incident: inc-test
     Severity: INFO
     Timestamp: 2026-11-11T12:00:00Z
     ```

---

## 4. Operational Controls

### Rate Limits & Pacing
- The provider enforces a minimum 1.0-second spacing between messages to comply with Telegram's chat rate limits.
- If Telegram returns HTTP 429 (`Too Many Requests`), the provider reads `retry_after` from the response parameters and reschedules the outbox item with exponential backoff.

### Quiet Hours Policy
- The broker supports quiet hours (e.g. 22:00 to 07:00).
- During quiet hours, low- and normal-severity notifications (`info`, `warning`) are held in the outbox.
- `critical` alerts **always bypass quiet hours** and are dispatched immediately.

### Credential Revocation & Rollback
To revoke credentials and stop Telegram delivery:

```powershell
scripts-notify telegram revoke --apply
```

Or revoke the token remotely via `@BotFather` using `/revoke`.
