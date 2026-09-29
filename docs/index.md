# tau

![tau: a neon tau logo inside a ring, centred between vertical light lines and nested neon triangles](brand/tau-hero.svg){ .tau-hero }

**A private-first personal "smart body".** tau is an agent you talk to from the terminal, from your phone and, later, from Telegram and by voice. It runs on one machine you own, the **hub**, and it touches the physical world only after you say yes.

## The private-first promise

Your conversations, the facts tau knows about you and its memory stay on the hub, on disk, under your user account. The only thing that ever reaches a third party is a client-side encrypted backup that nobody but you can open. There is no server between you and tau: nothing on the internet can approve an action on your behalf.

The reasoning is written down in [ADR 0006](adr/0006-private-first-topology.md); the plain-words version is the [threat model](architecture/threat-model.md).

## What works today

- **`tau chat`** and **`tau tui`**: a line-based REPL and a full Textual interface, with streamed replies, tool cards, session history and in-place approvals.
- **Tiers**: every tool declares whether it reads, writes digital state or acts on the world. The last kind always asks you first.
- **Sessions**: every conversation is recorded on disk, listed with `/sessions`, continued with `/resume`, summarized with `/compact`.
- **`tau hub`**: tau as a long-lived service under launchd or systemd, with a crash report on restart.
- **Components**: tools, providers, session backends, context sources and hub services plug in through entry points; `tau components` lists them.
- **Phone access**: Tailscale, hardened SSH, mosh and tmux, so the TUI survives a locked phone.

!!! info "Planned"
    Telegram, the web UI behind Cloudflare Access, voice, local memory and the encrypted R2 backup job are on the roadmap. Every page marks what is planned with a box like this one and names the roadmap issue, so you never mistake a plan for a feature.

## Three quick paths

<div class="grid cards" markdown>

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

    One hostname, `tau.<your-domain>`, through an outbound Cloudflare Tunnel and behind Cloudflare Access. Or Tailscale Serve when you have no domain.

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

The terminal, phone and hub rows run today. The browser, Telegram and backup rows are planned; each has its own guide that says exactly what exists.

## Where to go next

| I want to… | Read |
|---|---|
| understand every command | [CLI reference](reference/cli.md) |
| tune roles, windows and components | [tau.toml reference](reference/tau-toml.md) |
| know what tau may do without asking | [Tiers and approvals](reference/tiers.md) |
| write my own tool or provider | [Write a plugin](contributing/plugins.md) |
| see what is decided and what is open | [Decisions](ARCHITECTURE.md) · [Roadmap](contributing/roadmap.md) |
