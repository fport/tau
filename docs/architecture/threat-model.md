# Threat model

This is the readable version of [ADR 0006](../adr/0006-private-first-topology.md), with the owner guard of [ADR 0008](../adr/0008-owner-guard.md): what tau protects, who it protects it from, the decisions that follow, and a table of what an attacker gets from each piece they might compromise. Read it before you expose anything; the [private deployment guide](../guides/private-deployment.md) is the practical companion.

## What is protected

| Asset | Where it lives | Why it matters |
|---|---|---|
| Life data: `persona/user.md`, sessions, memory, the knowledge base | the hub, under `TAU_HOME` and `TAU_DATA_DIR` | facts about you, every conversation, everything tau remembers |
| Credentials: `.env`, the tunnel credentials file, the backup key | the hub; the backup key also in your password manager | model providers, Cloudflare, Telegram; the backups themselves |
| The hub machine | your desk | shell and file tools later; the sessions on disk now |
| Home devices and the robot | your home, reached through nodes | tier-2 tools: the physical world |
| Your face template | the hub, `TAU_DATA_DIR/guard/`, AES-GCM encrypted with a key in the macOS Keychain | biometric data; it must never leave the Mac, and a copy of the data folder must not reveal it |

## Who attacks, and how

1. **Through a public endpoint.** Anything reachable from the internet gets scanned and probed. tau's answer is to have exactly one such endpoint, behind identity, with no inbound port on the hub.
2. **Through text.** A Telegram message, a fetched web page, a tool result: anything that reaches the model can try to talk it into misusing a tool (prompt injection). tau's answer is that the model never approves anything, writes are tier 2 or sandboxed, fetches are allowlisted, and reflexes do not use a model at all.
3. **Through data at rest elsewhere.** A third party's store can be breached, subpoenaed or misconfigured. tau's answer is to keep life data on the hub and to send only ciphertext away.
4. **At your Mac.** Someone at your unlocked Mac opens the TUI and reads your sessions, or approves a tier-2 action with one key; a local program or a web page calls the hub's control API. tau's answer is the [owner guard](../guides/guard.md): guarded channels stay locked until your face is verified at the Mac, a tier-2 call needs a face step-up after your approval, and every control route but `/health` and `/status` needs a request signed with the hub's token. The guard protects tau's own windows, not your account: anyone with a shell in your account is out of its scope, and a 2D webcam check does not stop a real-time deepfake or a good video.

**Out of scope:** model inference. Prompts go straight from the hub to the configured provider (Anthropic, OpenAI or Google Gemini, with the owner's key; [ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)); nothing sits in between. The spend ledger on the hub (`TAU_DATA_DIR/spend.sqlite3`) records tokens and dollars per call, never text. The mitigation is data minimization (the system prompt carries `user.md` and the conversation, nothing else) and the `local` role, which keeps a prompt on the owner's Mac (Ollama).

## The decisions

| # | Decision | In one sentence |
|---|---|---|
| 1 | One public surface, identity at the edge | `hub.tau.<your-domain>` → Cloudflare Access → Cloudflare Tunnel (outbound from the hub) → the web UI. Tailscale Serve when there is no domain. No inbound port, ever. |
| 2 | Telegram without a middleman | The hub polls `getUpdates` itself; no webhook, no Worker; a `chat_id` allowlist on the hub. |
| 3 | Life data lives on the hub | Sessions, settings, memory, KB and routines under `TAU_DATA_DIR`; vector search local; Cloudflare holds only `age`-encrypted backups in a private R2 bucket. |
| 4 | Settings are local data | A hot-reloaded file under `TAU_DATA_DIR`; never synced to a third party. |
| 5 | Approvals only from trusted channels | The TUI, TauBar, the web UI behind Access with a per-device key, and Telegram polled directly. No intermediary exists, so none can approve. |
| 6 | Tools assume hostile input | Shell, file and write tools tier 2 or sandboxed; fetch tools allowlisted; tau-written tools wait in `tools/_pending/`; the mesh and sshd stay tailnet-only. |
| 7 | Voice is a separate package | Microphone, STT and TTS on the hub; nothing leaves before a wake phrase; voice from the phone goes through the web UI's microphone to the hub. |
| 8 | Installable by anyone | PyPI packages, `tau init`, `tau doctor`, this docs site; nothing personal needed to install or read. |
| 9 | The owner at the Mac | On a guarded hub the TUI, `tau chat` and tau Desktop open locked and unlock with a face check and a head-turn challenge; reflex locks on idle, screen lock, sleep and max age; a step-up after every tier-2 approval; Telegram and network turns are identified by chat id and contact keys instead; the template never leaves the Mac. |

## What an attacker gets if X is compromised

Read each row as: *if this one thing falls, and nothing else does*.

| Compromised | They get | They do not get | What limits it |
|---|---|---|---|
| **The Telegram bot token** | your messages to the bot and the ability to reply as tau | the hub, its files, an approval | the allowlist is checked on the hub; buttons are callbacks from your chat, which the token holder cannot forge. Rotate the token with BotFather. |
| **Your Cloudflare account** | control of the Access policy, so the front door of the web UI; the R2 bucket | readable data: R2 holds only ciphertext; an approval from the browser, which will need the per-device key on top of Access (issue 074) | two-factor on the account; the tunnel credential stays on the hub; the backup key is never in Cloudflare |
| **The R2 bucket alone** | `age`-encrypted bundles | anything readable | the key lives on the hub and in your password manager |
| **A bug in the web UI, reached past Access** | the agent as you: conversations, `user.md` through the model, tool calls at tiers 0 and 1 | a tier-2 action without the per-device key; the shell (tier 2 or sandboxed) | Access + the optional device rule in front; tiers behind. This is the row that justifies the device rule. |
| **The hub machine** | everything: life data, `.env`, the tunnel, the devices | – | full-disk encryption, key-only sshd from the tailnet, `0600` files; the backup and its key let you rebuild |
| **Your Tailscale account** | a device on your tailnet: it can reach sshd (keys only, so no login), the mesh (layer 5), and a Tailscale Serve web UI (no Access in front of it) | a login without your SSH key; an approval without the device key | key-only sshd; prefer Tunnel + Access over Serve when you have a domain; remove unknown devices in the admin console |
| **The phone** | an attached tmux session with the TUI, until the SSH key and the Tailscale device are revoked; the Telegram app; an Access session cookie | the backup key; the hub's shell beyond the tmux session's user | revoke the key in `authorized_keys` and the device in Tailscale; log the phone out of Telegram; short Access session durations |
| **The model provider** | prompts and replies: `user.md`, the conversation, tool descriptions | files, the hub, approvals | data minimization; the `local` role (Ollama on the Mac) |
| **Injected text** (a poisoned page, a hostile Telegram message from an allowlisted chat) | a model that wants to do something wrong | a tier-2 action without you; a write outside the sandbox | tiers; the model never approves; reflexes without a model |
| **Your unlocked Mac, while you are away** (a housemate, a visitor) | with the guard: nothing through tau's windows until a face check passes; a TUI you left unlocked, until idle (10 min), a presence recheck (3 min idle) or the screen lock | your sessions, an approval, the template | the owner guard; your Mac's screen lock; `/guard lock` from Telegram |
| **A local program or a web page** | `GET /health` and the open `/status` (state words, no timestamps) | any other control route: `/spend`, `/guard/*`, a lock or an unlock | signed requests with the hub's control token and a response proof; no `Origin` accepted; the guard's routes can only ask the hub to look |
| **A copy of `TAU_DATA_DIR` or a backup** | whatever that copy holds, but no face: the template is encrypted with a key in the Keychain, and `guard/` is left out of backups | the template, your face | AES-GCM with the key only in the Keychain |

## Why not the alternatives

- **A public Worker with Access on the API.** Access protects the front door, but the Worker would still hold the approval path and the data; a bug or a leaked token there reaches your home.
- **Everything through Tailscale only.** Most private, but you want a browser UI from any device and an install other people can follow. Tunnel + Access gives that without opening the hub; Tailscale Serve stays as the no-domain default.
- **Cloud vector search (Vectorize, AI Search).** They cannot search encrypted data, so using them means storing life data in clear. A personal corpus is small; local search is fast enough.

## What this costs you

- A backup discipline: scheduled encrypted backups and a restore you have tested ([Backups](../guides/backups.md)).
- An always-on hub, eventually a Raspberry Pi ([Move the hub](../guides/raspberry-pi.md)); until then a Mac kept awake on AC.
- No "tau is offline" auto-reply on Telegram while the hub is down (Telegram keeps updates for about a day; the hub catches up).
- Near-zero cloud cost: Tunnel, Access and R2 all have free tiers that cover one person.
