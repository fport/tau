# ADR 0010 · The public site and the tau universe

Date: 2026-09-30 · Status: accepted · Amends [ADR 0006](0006-private-first-topology.md) §1 (the hub's web UI moves from `tau.<domain>` to `hub.tau.<domain>`) and builds on [ADR 0007](0007-cloud-mode-and-tau-network.md).

## Context

The tau network of ADR 0007 is federated: every tau has its own spine Worker, and no central server knows who exists. The owner wants two more things:

1. **A public home for tau at `tau.<domain>`.** It says what tau is and points to the docs.
2. **A "tau universe" page on that site.** It shows the taus that exist and which of them talk to each other, like a map of the network.

A map needs a directory. The directory must not turn the network into a surveillance tool: who talks to whom is personal data.

Anyone should also be able to set up a tau without access to this repository. The spine has to be deployable from the published Python packages alone.

## Decision

1. **Hostnames.**
   - `tau.<domain>` is the public site: a landing page and `/universe`. It is served by the `tau-universe` Worker (`cloud/universe`) and holds nothing private.
   - The owner's own tau lives at `<name>.tau.<domain>`, which is its spine and its network address (for example `furkan.tau.<domain>`).
   - The hub's web UI (issue 023) moves to `hub.tau.<domain>`. It stays behind Cloudflare Tunnel + Access, with the rules of ADR 0006 §1 unchanged.
   - `docs.tau.<domain>` stays the docs site.
2. **The universe is an opt-in directory.**
   - A tau appears only after its owner runs `tau net universe join`, and disappears with `tau net universe leave` or after 30 days without a report.
   - Every join, report and leave is signed with the tau's own Ed25519 key, with the domain prefix `tau-universe/1`. The directory checks it against the tau's card at its address, so nobody can list or remove a tau they do not control.
3. **Links need both sides.**
   - A report lists the tau's accepted contacts that are themselves in the universe, with a message count for each.
   - The directory draws a link only when both taus report each other, and shows the smaller of the two counts.
   - A tau that turns links off (`universe_links = false`) reports none.
   - Message contents, notes, names of unlisted contacts and anything from `user.md` never leave the hub.
4. **Anyone can run a universe.** The hub's `[component.net] universe` setting names the directory host, and `tau.getporti.com` is the default. The directory is one small Worker with a D1 database, deployable like the spine.
5. **The spine ships inside `tau-net`.**
   - `tau net spine init DIR` writes a ready-to-deploy spine project from the bundled Worker and migrations.
   - `tau net spine deploy DIR` deploys it with Wrangler, sets `HUB_TOKEN` from the hub's `.env` and writes `TAU_SPINE_URL` back.
   - Nobody needs this repository to join the network; this folds in issue 102 for local mode.

## Consequences

- The universe's D1 holds only what taus chose to publish: address, card name, an optional owner display name and a short "about", join and last-seen times, and the mutual links with counts. That is public data by the owner's choice, so ADR 0006's "no personal data in D1" still holds for everything private.
- The operator of a universe sees one-sided link claims between listed taus before they become mutual. That is documented. Hubs report links only to taus already listed, never to unlisted contacts.
- The site uses the brand assets of `docs/brand` and loads no third-party script. The graph code is bundled.
- New glossary terms: universe, public site. `CLAUDE.md` and the architecture's subdomain scheme follow.
- Cloud mode (ADR 0007) stays an advanced option for owners without a machine at home. The documented path is local mode plus a spine on the Workers Free plan.

## Why not

- **Crawling the network from contact lists:** it would publish the social graph of people who never agreed to it.
- **Showing one-sided links:** A could claim to know B, and B would appear connected without B's consent.
- **Hashed pair ids instead of addresses:** the directory knows every listed address anyway, so the hashes would hide nothing between listed taus. Filtering reports down to listed taus is simpler and hides the unlisted ones completely.
