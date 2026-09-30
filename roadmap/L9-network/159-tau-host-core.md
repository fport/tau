# 159 · tau-host: accounts, the brain in a Durable Object and the owner's app

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §2 and §5 (hosted half), everything except the network (162).

- Worker `tau-host` in `cloud/host` (pnpm, wrangler, vitest pool workers), config via `pnpm run configure` like the spine and the universe (`wrangler.example.jsonc` tracked, `wrangler.jsonc` gitignored).
- GitHub OAuth (state + PKCE), `SIGNUP` open or a login list, sessions, `Origin` checks, `DEV_LOGIN` for localhost only.
- `Accounts` and `Tau` Durable Objects (SQLite). Vault (`VAULT_KEY`, AES-GCM, HKDF per handle).
- Providers by `fetch`: Anthropic Messages, OpenAI Chat Completions, Gemini generateContent, with tool use; roles `brain`/`fast`; generated `models`, `prices` and default persona from tau-core templates (`pnpm run generate`, CI freshness check).
- The agent loop: persona + profile + session; tools `ask_sub` (tier 0) and `create_sub` (tier 2, approval card); budgets per ADR 0011.
- Sub-taus: create from a description (drafted by `brain`) or a template, edit, chat, flags `public`/`web`/`web_daily`/`starters`, reserved names refused.
- Owner's app `/app` in the site's new look (dark, sharp, neon red; see 161): chat with streaming, sessions, sub-taus, approvals, settings (key, models, budget, persona, profile, language en/tr), export JSON, delete account.
- Visitor API for web sub-taus, used by the universe relay (163) and by tau-host's own page `/@<handle>/<name>`: `POST /api/visit/<handle>/<name>` `{visitor, thread?, text}` → `{thread, reply}`; network-turn rules (no profile, no tools, no approvals), `web_daily` cap, 24 h thread TTL.
- `GET /api/host/whoami` for the universe (`{handle, github_id}` or 401).

## Acceptance criteria

- [x] `pnpm test` covers auth (mock GitHub), sessions, vault round-trip, each provider client against recorded fixtures, the loop with a fake provider, tier-2 pause/approve/deny/timeout with a fake approver, budget refusal, visitor caps
- [x] `pnpm dev` + `DEV_LOGIN=1`: sign in, paste a key, chat, create a sub-tau, make it web, talk to it at `/@<handle>/<name>` (checked with a fake provider)
- [x] `cloud/host/README.md`: configure, run locally, deploy (own host); no personal values
- [x] Nothing ever logs or returns a provider key; tier 2 is never auto-approved

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built:
  - **Worker** `cloud/host` (`tau-host`): `pnpm run configure [--route HOST] [--client-id ID] [--signup open|LOGINS]` writes `wrangler.jsonc` and a `.dev.vars` with a fresh `VAULT_KEY`; vars `GITHUB_CLIENT_ID`, `SIGNUP` (`open`, a login list, or empty = no new accounts; existing accounts always sign in), `PUBLIC_HOST` (empty = request host), `DEV_LOGIN`, `FAKE_PROVIDER`; secrets `GITHUB_CLIENT_SECRET`, `VAULT_KEY`. CI: `.github/workflows/host.yml` (check-generated, typecheck, test, build).
  - **Routes:** `/` landing (signed in → `/app`); `/app`, `/app/*` the app shell (signed out → `/auth/login?next=`); `/app/assets/*` static (asset store, `run_worker_first` excludes it); `GET /auth/login?next=`, `GET /auth/callback`, `POST /auth/logout`, `POST /auth/dev` (DEV_LOGIN, localhost only); the owner's API under `/api/host/*` (`whoami`, `state`, `onboard`, `settings`, `sessions[/<id>]`, `chat`, `approvals[/<id>]`, `subs[/<name>[/visits]]`, `draft`, `templates`, `export`, `account/delete`), all under `/api/host/` so a universe forwarding `/api/host/*` reaches them; `GET|POST /api/visit/<handle>/<name>`; `GET /@<handle>/<name>` the visitor page. `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*` answer 404 until 162.
  - **Contracts:** `GET /api/host/whoami` → `{handle, github_id}` or 401 `{error: "unauthorized"}` (dev accounts have negative ids). `POST /api/visit/<handle>/<name>` `{visitor: 8–64 of [A-Za-z0-9_-], thread?, text ≤ 2000}` → `{thread, reply: {id, text, ts}}` (`ts` in seconds); errors 400, 403 `bad_origin` (only when an `Origin` other than the host is sent), 404 `not_found` / `unknown_thread`, 409 `thread_full` (50 messages), 413, 429 `daily_cap` / `rate_limited` (10/min per `cf-connecting-ip`, only when the header is present), 402 `budget`, 502 provider errors or `no_reply`, 503 `unavailable`. `GET /api/visit/<handle>/<name>` → `{handle, name, about, starters}`. Chat and approval decisions stream NDJSON events (`start`, `text`, `tool`, `tool_result`, `approval`, `notice`, `done`, `error`).
  - **Objects:** `Accounts` is `getByName("accounts")`; `Tau` is `getByName(handle)` (`idFromName(handle)`); the Worker asks `Accounts.account(handle)` before touching a `Tau`, so probes never create objects. RPC methods return `{ok, value}` or `{ok: false, status, error, detail?}`; streaming ones return a `Response`.
  - **For 162:** add tables in `Tau` (identity sealed with `seal(env.VAULT_KEY, handle, "net_key", …)`), `net_send` as a tier-2 `HostTool` in `Tau.tools()`: the approver (`Tau.approver`) already stores a card and pauses the turn, `decide()` resumes it and the alarm expires it after 10 minutes. A delivered envelope can run like `Tau.visit()` (sub-tau persona + public note via `publicNoteSection`, no tools; the prompt helpers are in `src/agent/prompt.ts`). The onboarding's explicit universe choice is `settings.universe` (`true|false`).
  - **Look:** `client/host.css` uses the tokens `--bg`, `--bg-2`, `--line`, `--text`, `--muted`, `--accent`, `--accent-glow` (plus `--font`, `--mono`) with fallbacks; the build copies `cloud/shared/theme.css` to `/app/assets/theme.css` when it exists, else `client/theme-fallback.css`. Characters: `import { character } from "tau-character"`, which `scripts/build.mjs` resolves to `cloud/shared/character.ts` when it exists, else `client/character-placeholder.ts` (same signature).
  - **Checked:** `pnpm test` (105 tests in 9 files), `pnpm run typecheck`, `pnpm run check-generated`; `pnpm dev` with `DEV_LOGIN=1` and the fake provider: signed in, onboarded, chatted (streamed), `/create coach …` stopped at an approval card, approved (sub-tau created), made it public + web, talked to it at `/@alice/coach` and through the visitor API (daily cap hit as set), onboarding and a pending approval driven in headless Chrome, desktop and phone widths without horizontal scroll, English and Turkish. The fake provider needs no key; pasting, checking and sealing a real key is covered by tests against a mocked Anthropic endpoint, never a real provider.
  - **Not here:** the network (162); per-session history beyond the last 60 messages is kept but not sent to the model.

