# Parking lot

Deliberately-deferred work that is **declared** (often behind a contract/stub)
but not built yet. Each entry says why it's parked and what would unpark it.
This is not a backlog of everything — only things we chose to stub now so the
shape exists, plus the trigger for picking them up.

## Automated authentication strategies (T4.2a)

The auth seam (`app/auth/`, `AuthStrategy`) ships only the **interim manual-OTP**
strategy: a human enters the OTP/2FA code once per run. OTP/2FA is **configured,
never cracked.** The automated variants are declared behind the same contract and
raise `NotImplementedError` pointing here:

| Variant | Intended approach | Why parked | Unpark when |
|---|---|---|---|
| `totp` | Generate the code from a shared secret via `pyotp`. | Needs the target to expose/seed a TOTP secret to the tester; only some targets use TOTP. | The challenge log shows `totp`/authenticator challenges dominate. |
| `email_otp` | Read the code from a dedicated test inbox (IMAP/API). | Needs a provisioned test mailbox + parsing per template. | Email OTP is the common challenge and a test inbox is available. |
| `sms_otp` | Read the code via a programmable-number provider (e.g. Twilio). | Costs money + a real number per account; provider integration. | SMS OTP dominates and a number provider is approved. |

**How we'll choose first:** the `auth_challenge_log` table accumulates, per real
login attempt, which challenge appeared (none/otp/2fa), the channel if
observable, and the outcome — **with no secrets** (redacted account label only).
We build the automated strategy whose challenge type actually shows up most. See
ADR-0016.

## Crawler depth (T4.2)

The runtime frontend crawler loads pages and captures their calls, but does not
yet submit forms or click through multi-step flows. Driving interactions would
observe more endpoints. Unpark when endpoint coverage from passive loads plateaus.
