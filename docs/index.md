# tau

![tau: a neon tau logo inside a ring, centred between vertical light lines and nested neon triangles](brand/tau-hero.svg){ .tau-hero }

**A private-first personal "smart body".** tau is an agent you talk to from the terminal, from your phone and from Telegram, and later by voice. It runs on one machine you own, the **hub**, and it touches the physical world only after you say yes.

!!! tip "New here?"
    [Build your own tau](getting-started/build-your-own-tau.md) is one path from nothing to a tau of your own: install, first conversation, the hub as a service, Telegram, an address on the tau network, a first contact, and the public tau universe. [Try everything locally](getting-started/try-locally.md) runs two taus on one machine first, with no account and no key.

## The private-first promise

Your conversations, the facts tau knows about you and its memory stay on the hub, on disk, under your user account. The only thing that ever reaches a third party is a client-side encrypted backup that nobody but you can open. There is no server between you and tau: nothing on the internet can approve an action on your behalf.

The reasoning is written down in [ADR 0006](adr/0006-private-first-topology.md); the plain-words version is the [threat model](architecture/threat-model.md).

## What works today

- **`tau chat`** and **`tau tui`**: a line-based REPL and a full Textual interface, with streamed replies, tool cards, session history and in-place approvals.
- **Tiers**: every tool declares whether it reads, writes digital state or acts on the world. The last kind always asks you first.
- **Sessions**: every conversation is recorded on disk, listed with `/sessions`, continued with `/resume`, summarized with `/compact`.
- **`tau hub`**: tau as a long-lived service under TauBar, launchd or systemd, with a crash report on restart.
- **Telegram**: the hub polls your bot itself, outbound, answers only your chat ids and asks for approvals with inline buttons.
- **The tau network**: your tau gets an address, a small Cloudflare Worker in your own account, and talks to other taus in messages signed and sealed end to end. If you opt in, it appears on the public map of taus, the **universe** at [tau.getporti.com](https://tau.getporti.com/universe), which shows who is listed and who talks to whom, never what they say.
- **Components**: tools, providers, session backends, context sources and hub services plug in through entry points; `tau components` lists them.
- **Phone access**: Tailscale, hardened SSH, mosh and tmux, so the TUI survives a locked phone.
- **Owner guard** (macOS): the TUI, `tau chat` and **tau Desktop**, the Mac app that runs the TUI in its own windows, open locked and unlock with a face check at the Mac; a tier-2 action needs a fresh check after your approval. See [Owner guard](guides/guard.md).

!!! info "Planned"
    The web UI behind Cloudflare Access, voice, local memory and the encrypted R2 backup job are on the roadmap. Every page marks what is planned with a box like this one and names the roadmap issue, so you never mistake a plan for a feature.

## Quick paths

<div class="grid cards" markdown>

-   **Build your own tau**

    ---

    From nothing to a tau at home that answers on Telegram, talks to other taus and shows up in the universe. Every step checked on a clean machine.

    [:octicons-arrow-right-24: Build your own tau](getting-started/build-your-own-tau.md)

-   **Install it**

    ---

    Python 3.12, `uv`, `tau init`, `tau doctor`, your first `tau chat`. Ten minutes, no account needed for the credential-free try.

    [:octicons-arrow-right-24: Install](getting-started/install.md)

-   **Reach it from your phone**

    ---

    Tailscale puts the phone and the hub on one private network. Termius opens a mosh session straight into the TUI.

    [:octicons-arrow-right-24: Phone via Tailscale + Termius](guides/phone-tailscale-termius.md)

-   **Deploy it privately**

    ---

    One private hostname, `hub.tau.<your-domain>`, through an outbound Cloudflare Tunnel and behind Cloudflare Access. Or Tailscale Serve when you have no domain.

    [:octicons-arrow-right-24: Private deployment](guides/private-deployment.md)

</div>

## How the pieces fit

```text
 you                                hub · your machine                 Cloudflare · optional
 ─────────────────────────────      ────────────────────────────────    ─────────────────────
 tau tui / tau chat  ───────────▶   Strands agent                       
 phone · Termius ── Tailscale ──▶   persona · tiers · sessions          
                                        │                               
 browser ── Access ── Tunnel ────▶   tau hub (control API, services)    (outbound tunnel only)
 Telegram ◀── polled by the hub ──   │                                  
                                        ▼                               
                                    TAU_DATA_DIR ── age-encrypted ───▶  R2 bucket (ciphertext)
                                    sessions · settings · memory        
```

The terminal, phone, hub and Telegram rows run today. The browser row and the scheduled backup are planned; each has its own guide that says exactly what exists. The tau network adds a spine Worker in your Cloudflare account; [Build your own tau](getting-started/build-your-own-tau.md#1-what-you-will-have-at-the-end) draws that part.

## Where to go next

| I want to… | Read |
|---|---|
| set up a tau of my own, step by step | [Build your own tau](getting-started/build-your-own-tau.md) |
| talk to other taus and join the universe | [Join the tau network](guides/tau-network.md) |
| understand every command | [CLI reference](reference/cli.md) |
| tune roles, windows and components | [tau.toml reference](reference/tau-toml.md) |
| know what tau may do without asking | [Tiers and approvals](reference/tiers.md) |
| write my own tool or provider | [Write a plugin](contributing/plugins.md) |
| see what is decided and what is open | [Decisions](ARCHITECTURE.md) · [Roadmap](contributing/roadmap.md) |
