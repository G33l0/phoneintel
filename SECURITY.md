# PHONEINTEL — Security model

This documents how the app resists cracking, coin/cost manipulation, and abuse. It is written
to be honest about what client-side protection can and cannot do.

## The one principle that matters: never trust the client

A shipped Android APK can always be reverse-engineered given enough effort. This is especially
true for a Kivy / python-for-android app, which ships compiled Python bytecode that is easier to
decompile than obfuscated native code. **No obfuscation makes an app "unbreakable" or "safe from
AI."** Anyone claiming that is selling something.

So PHONEINTEL does not rely on client secrecy for its security. It relies on the server being the
sole authority for everything that matters:

- **Coins / balances / spending** are owned and enforced by the server. The device never holds an
  authoritative balance. Every coin-spending action (a lookup, enabling hosting, receiving a
  message batch) is a request the server authorizes and meters atomically, server-side, against
  the account's real balance. A fully cracked or modified client cannot grant itself coins,
  because it has no authority to — it can only ask, and the server says yes or no.
- **Pricing and profit margins** (`admin_config.py`: `provider_cost_*`, `margin_*_percent`,
  `billable = cost * (1 + margin/100)`) are **operator/super-admin configuration applied on the
  server**. The copy of `admin_config` that ships in the app is only ever used server-side or for
  display of server-provided values; the device is never the source of truth for a price. Editing
  a local database on a rooted device changes nothing the server charges.
- **Verification / LOA** is an operator action. The app cannot mark a number verified. Inbound
  messages are gated through an ownership + verified-state join, so no code path returns a message
  to an account that does not own a verified number.
- **No secrets in the APK.** Users never enter or see a Telnyx/Twilio API key. Provider
  credentials and the signing of inbound-SMS webhooks live in the operator's environment, never in
  the client. There is nothing in the APK worth extracting to impersonate the operator.

If every one of those is enforced server-side, the client can be decompiled, patched, and
replayed and still cannot manipulate coins, prices, verification, or another user's messages.

## Account identity

- Onboarding mints a cryptographically-random **18-digit** account ID (`identity.py`); no email or
  phone is collected.
- The raw ID is the user's credential. Only a **salted SHA-256 hash** is persisted; a data leak
  never exposes a usable ID. Comparisons are constant-time.
- 18 digits is ~60 bits. That is fine against offline attack of the stored hash, but an online
  attacker could try to guess active IDs. **The server must therefore rate-limit and lock out**
  authentication attempts per IP/device, require TLS, and (recommended) bind a session to a
  device token after first use so a guessed ID alone is not enough.

## Ownership verification (business-line SMS hosting)

- A user requests hosting for a line their business owns.
- The **super-admin validates the Letter of Authorization (LOA)** — the same proof the carrier
  (Telnyx) requires to host/text-enable a number — and records the LOA reference and operator id.
  Only then is the number verified. This is a trusted-operator model: integrity depends on the
  admin actually validating the LOA, which is the industry-standard control for SMS hosting.
- The app has no self-verify path. A number is owned by one account at a time and cannot be taken
  over. Releasing a number hard-deletes it and its stored messages.

## Client hardening (defense in depth, not a security boundary)

These raise the cost of tampering; they are not relied upon:

- Ship compiled bytecode, not source (python-for-android default); release builds run the Gradle/R8
  shrinker on the Java bootstrap.
- No API keys, pricing authority, coin balances, or verification authority embedded in the client.
- All SQL is parameterized; inputs are validated and normalized before use.
- Private app storage for the account ID (`0600`), and Android backups disabled for the app.

## Server / admin-portal checklist (where the real controls live)

When the admin portal and backend are built, they must:

1. Authenticate every request; never accept a client-asserted balance, price, or verified status.
2. Meter and decrement coins atomically on the server, inside a transaction, per authorized action.
3. Keep provider credentials and margins server-side; expose only computed, read-only values to
   clients.
4. Verify inbound-SMS webhooks with the provider's signature before storing a message.
5. Rate-limit account-ID authentication and all spend endpoints; lock out abuse.
6. Record an audit trail (LOA reference, operator id, verification time are already captured).
7. Run the admin portal over TLS with strong admin authentication (MFA) and least-privilege roles.

## Reporting

Security issues should be reported privately to the repository owner rather than opened as public
issues.
