# 159 · tau-host: accounts, the brain in a Durable Object and the owner's app

Status: ready-for-agent
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

- [ ] `pnpm test` covers auth (mock GitHub), sessions, vault round-trip, each provider client against recorded fixtures, the loop with a fake provider, tier-2 pause/approve/deny/timeout with a fake approver, budget refusal, visitor caps
- [ ] `pnpm dev` + `DEV_LOGIN=1`: sign in, paste a key, chat, create a sub-tau, make it web, talk to it at `/@<handle>/<name>` (checked with a fake provider)
- [ ] `cloud/host/README.md`: configure, run locally, deploy (own host); no personal values
- [ ] Nothing ever logs or returns a provider key; tier 2 is never auto-approved

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
