# 117 · Remote unlock through Telegram: per-client grants for SSH/mosh sessions and `tau ask`

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: tau-guard, tau-core, tau-tui
Blocked by: 113

## What to build

With the guard on, a `tau tui` or `tau chat` over SSH or mosh from the phone, and `tau ask` from an iOS Shortcut, share the Mac's unlock: they work only while the owner is verified at the Mac. That takes away the owner's main remote workflow. This issue gives remote clients their own way in: a **grant** the owner approves on Telegram. Each grant is tied to one client, checked by the hub, and has its own lifetime, so the Mac's idle and screen locks do not end it. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 6, 17 and 19).

A grant is a hub-issued credential, never a claim. The environment variable `SSH_CONNECTION` only decides which button a channel offers and what label the owner sees on Telegram. It never changes policy, because anyone at the Mac can set it (T7).

### Grants

- **Request.** On a locked TUI or terminal prompt, the channel offers "Ask on Telegram" next to the face unlock; it is the default when `SSH_CONNECTION` is set. The request is `POST /guard/grant` with `{channel, client_id, label}`, answered with `202 {request, seq}`. The label (for example `tui over ssh from 100.x.y.z`) is shown to the owner and trusted for nothing.
- **Owner decision.** The hub sends a message to the allowlisted Telegram chats, through `TelegramService` found in-hub, or through the owner-notice seam once 123 lands.
  - The message shows the label, the short client id and the time.
  - Its buttons are "Allow 30 min", "Allow <grant_max_hours> h" and "Deny".
  - Only a callback from an allowlisted chat counts. An unanswered request expires after 5 minutes.
- **Issue.** On Allow, the hub mints a grant secret (32 random bytes) and keeps only its hash, with the `client_id`, the expiry and the idle limit, in memory. A hub restart revokes every grant. The secret reaches the requester only through its own protected, proof-checked `GET /guard/status` long poll for that request.
- **Use.** `GuardTurn` gains `grant: str | None = None`, an additive change in tau-core. `HubGuard` keeps the secret for the process and sends it with every admit.
  - The hub admits a turn when the grant is valid for that `client_id`, whatever the Mac's HID idle or screen state.
  - A grant has its own idle clock: `grant_idle_minutes` (default 15), counted since the last admitted turn of that client. `grant_max_hours` (default 2, range 0.25–8) caps its life.
- **Revocation.** `/guard lock` from any channel (triggers `command` and `telegram`), a failed step-up, sleep, a hub stop or a restart revokes every grant. `idle` and `screen_lock` on the Mac lock the Mac's own unlock and leave grants alone.
- **Tier 2 on a granted client.** The step-up never uses the camera, because the owner is away. It is a Telegram confirmation naming the tool and the effect, with a 2-minute timeout. It can only turn `APPROVED` into `REJECTED`, like every step-up.
- **`tau ask`.** Run in a remote shell, `tau guard grant --for ask [--hours N]` requests a standing grant for `tau ask` (N up to `ask_grant_max_hours`, default 24, range 1–168). The owner approves it on Telegram. The secret is written to `TAU_DATA_DIR/guard/grants/ask` (0600, in the 0700 `guard/` directory), and `tau ask` presents it when present. A process that can read that file already has a shell in the owner's account, which is out of scope. The file still never leaves the hub (backups exclude `guard/`). Tier 2 stays refused in `tau ask` whatever the grant (073).
- **Audit.** `grant_request`, `grant` and `grant_revoke` join the audit events, with the label, the client id, the chat's allowlist index (never a chat id) and the expiry.

### Channels

- The TUI header shows "remote grant until HH:MM" while one is active. The terminal prints it after an unlock.
- `tau guard status` lists active grants: label, short client id, expiry, idle. `tau guard revoke [<client id>|--all]` revokes them.

## Acceptance criteria

- [ ] `POST /guard/grant` creates a request and Telegram shows the label with Allow and Deny buttons (fake Telegram); a callback from a chat outside the allowlist changes nothing; an unanswered request expires after 5 minutes
- [ ] After Allow, only the requesting client receives the secret, through its own request; the hub stores only a hash; a second client presenting the same `client_id` without the secret is refused
- [ ] A granted client is admitted while the Mac is locked by `idle` or `screen_lock`, and refused after `grant_idle_minutes` without a turn, after `grant_max_hours`, and after `/guard lock`, a failed step-up or a hub restart (fake clock)
- [ ] Setting `SSH_CONNECTION` changes only the offered button and the label: with it set and no grant, admission is still refused (test)
- [ ] Tier 2 on a granted client asks for a Telegram confirmation and never opens the camera; a timeout or "Deny" rejects; no path produces `APPROVED` from a grant (gate test with `FakeGuard` and a fake Telegram)
- [ ] `tau guard grant --for ask` writes a 0600 grant file after approval; `tau ask` with it is admitted until expiry and refuses tier 2 as before; without it `tau ask` exits 2 with the guard notice
- [ ] Grant events are in `audit.jsonl` without any chat id; `tau guard status` lists and `tau guard revoke` removes grants
- [ ] All new chrome (TUI, terminal, Telegram messages and buttons) goes through i18n keys in `en` and `tr`

## Blocked by

- [113 · Guarded channels](113-guarded-channels.md)

## Comments

- 2026-09-30: filed with ADR 0008. Until this lands, `tau guard setup` and the guide say that remote TUI, chat and `tau ask` are locked while the owner is away from the Mac.
