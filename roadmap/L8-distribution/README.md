# L8 · Distribution

**Goal:** Anyone can install tau from PyPI and follow the docs to run it privately ([ADR 0006](../../docs/adr/0006-private-first-topology.md) §8): `uv tool install tau-core --with tau-tui`, then `tau init` and `tau doctor`; step-by-step guides on a docs site that needs nothing personal.

**Done when:** A version tag publishes the packages to PyPI from CI with trusted publishing and the documented install works from the published wheels, and the docs site builds strictly in CI and is live on Cloudflare Pages at `docs.tau.<domain>`.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 078 | [PyPI release path: trusted publishing on tags, version policy, install verified from wheels](078-pypi-release-path.md) | HITL | – |
| 079 | [Docs site: MkDocs Material built strictly in CI and deployed to Cloudflare Pages at `docs.tau.<domain>`](079-docs-site.md) | HITL | – |
| 169 | [One installer and `tau setup`: pick the features, install and configure them](169-one-installer-and-tau-setup.md) | AFK | – |
| 172 | [Telegram pairing without looking up a chat id](172-telegram-pairing.md) | AFK | 169 |
| 173 | [Remote access in setup: Tailscale and the phone](173-remote-access-step.md) | AFK | 169 |
| 175 | [Docs and site for the installer and the app](175-installer-docs-and-site.md) | AFK | 169, 170 |
| 190 | [Public downloads for the tau app and its updates](190-public-app-downloads.md) | AFK | 170 |

Live status: `python3 roadmap/board.py --layer L8`
