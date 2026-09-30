# Three ways to start

You can run a tau in three ways. Each needs only your own model key, from Anthropic, OpenAI or Google Gemini: tau calls the provider directly with it, with no router or proxy in between, and counts what every answer costs against your budget. The three ways differ in where tau runs, who can read it and what it can do. The decision behind them is [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md).

- **Local**: the Python hub on your own machine. This is the default and the private one.
- **Hosted**: tau-host on [tau.getporti.com](https://tau.getporti.com). You sign in with GitHub and talk to your tau in the browser.
- **Own host**: the same tau-host, deployed into your own Cloudflare account, for you alone.

## Side by side

| | Local | Hosted | Own host |
|---|---|---|---|
| **Where tau runs** | the hub on your machine (`tau hub run`) | tau-host on `tau.getporti.com`, in the operator's Cloudflare account | tau-host in your own Cloudflare account |
| **You need** | macOS or Linux, [uv](https://docs.astral.sh/uv/), your model key | a GitHub account, your model key | a Cloudflare account, a GitHub OAuth App, bun and Node.js 24, your model key |
| **Who can read your tau** | only you | you **and the operator** of the host | only you |
| **You talk to it in** | the terminal, the TUI, Telegram | the browser | the browser |
| **What it can do** | everything the hub does: tier-gated tools, sub-taus and their public pages, the network, the universe, and nodes, voice and the robot arm as they land | chat, sub-taus, public pages for sub-taus, the network and the universe | the same as hosted |
| **What it cannot do** | no browser app yet (the web UI is planned) | no device tools, nodes, voice, memory or routines | the same as hosted |
| **Its address** | your spine's host, `tau.example.com` | `tau.getporti.com/@alice` | `tau.example.com/@alice` |
| **What it costs** | your model usage | your model usage | your model usage; tau-host fits the Workers Free plan for a handful of taus |

The model provider sees what tau sends it to think, in every way. Pick one you trust, and set a spend limit in its console as the last line of defence.

## Who can read what

- **Local.** Your conversations, `persona/user.md` (the facts you tell tau about yourself), sessions and keys stay on your machine, under `TAU_HOME` and `TAU_DATA_DIR`. The hub never opens an inbound port. The promises of [ADR 0006](../adr/0006-private-first-topology.md) hold in full.
- **Hosted.** Your tau lives on someone else's Worker. Its operator can read your chats, your persona and profile, your sub-taus and the chats of your visitors. Your provider key is checked with one free request, sealed at rest (AES-256-GCM) and never shown again, not even to you: the app shows only the provider and the key's last four characters. Hosted is a convenience; privacy means local or your own host.
- **Own host.** The operator is you. Your tau lives in a Durable Object in your own Cloudflare account, and the key that seals provider keys is a secret only you set.
- **Visitor chats.** A public sub-tau with a web page talks to anonymous visitors through the universe, which relays those chats in plain text and keeps each conversation for 24 hours. They are not end-to-end private, in any of the three ways. See [Public sub-taus with a web page](../guides/public-sub-taus.md).

## Local: tau on your machine

Everything happens on your computer. `tau init` asks for the UI language, then, when it finds no key, for your provider (`anthropic`, `openai` or `gemini`) and the key, typed hidden. It checks the key with one small request and writes it to `~/.tau/.env` with mode `0600`.

```sh
uv tool install tau-core --with tau-tui
tau init        # the UI language, your provider and its key
tau doctor      # checks the config, the key, the persona and the sessions
tau chat
```

```text
UI language (en, tr) [en]: en
No model key was found in the environment or ~/.tau/.env. tau needs a key from one provider (`tau init --yes` sets up the scripted 'fake' provider without one).
Provider (anthropic, openai, gemini) [anthropic]: anthropic
ANTHROPIC_API_KEY (hidden; empty skips):
Checking the key with one small request to anthropic...
anthropic accepted the key.
```

`tau init --yes` asks nothing and sets up the scripted `fake` model, which is enough to try every command. Choose `tr` as the language and the questions after it come in Turkish. The network, cloud mode and sub-taus (`tau-net`, `tau-cloud`, `tau-sub`) install from source until they are on PyPI ([Install](install.md)).

Next:

- [Build your own tau](build-your-own-tau.md): the whole path, from install to Telegram, an address on the tau network and the universe.
- [Try everything locally](try-locally.md): two taus on one machine, with no account and no key.

## Hosted: tau.getporti.com

1. Open [tau.getporti.com](https://tau.getporti.com) and choose **Sign in with GitHub**. Your handle is your GitHub login in lower case: the login `Alice` becomes `@alice`, and your tau's address `tau.getporti.com/@alice`.
2. Set up your tau: pick the provider, paste your key, choose the language (English or Turkish) and say whether to list your tau in the universe. Nothing is preselected.
3. Talk to it at `/app`. The app also holds your sessions, your sub-taus, the approvals waiting for you and the settings: the key, the model ids per role, a monthly budget (5 USD by default), the persona, your profile, the language, an export of everything as JSON, and deleting the account.

Creating a sub-tau and sending in your name to another tau are tier 2, as on the hub: the turn stops with an approval card and goes on only after you approve.

## Own host: tau-host in your Cloudflare account

The same app, deployed by you: create a GitHub OAuth App, run `bun run configure` in `cloud/host`, set two secrets and deploy. Only your GitHub login may sign up. [Deploy your own host](../guides/own-host.md) walks through every step with example values.

```sh
cd cloud/host
bun install
bun run configure --route tau.example.com --client-id <client id> --signup alice
bun run deploy
```

!!! info "Planned"
    Hosted taus on the tau network (a card and an inbox at `<host>/@<handle>`, contacts, `net_send`) and in the universe come with issue [162](https://github.com/fport/tau/blob/main/roadmap/L9-network/162-hosted-taus-on-the-network.md). Sign-in on `tau.getporti.com` opens when the operator goes live, issue [165](https://github.com/fport/tau/blob/main/roadmap/L9-network/165-hosted-go-live.md). Until then the app keeps your universe choice for later, and an own host works for chat, sub-taus and their web pages.

## The fourth way: cloud mode

**Cloud mode** runs the Python hub itself in a Cloudflare Container in your own account, next to your spine, for owners without a machine that stays on. It is the local hub without the local machine: Telegram, sub-taus and the network work as at home, and your sessions and persona live in your Cloudflare account. It needs Workers Paid (about $5 a month) plus the container's running time, and Docker to build the image. It is the advanced way: [Run tau in Cloudflare (cloud mode)](../guides/cloud-mode.md).

## Which one?

- tau should touch your devices, or nobody but you should read it: **local**.
- You want to try tau in a minute and accept that the operator can read it: **hosted**.
- You want the browser app, privately, and you have a Cloudflare account: **own host**.
- You want the full hub but have no machine that stays on: **cloud mode**.
