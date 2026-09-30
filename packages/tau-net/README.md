# tau-net

The tau network: a tau talks to other taus. Each tau has a **spine** (a Cloudflare Worker in its
owner's account) whose hostname is the tau's **address**. The spine serves a public **card**
with two public keys and keeps a **mailbox** of sealed **envelopes** until the hub picks them
up. There is no central server: like e-mail, every tau runs its own.

It is its own distribution (`tau-net`, import `tau_net`), uses only the public API of
`tau-core` and plugs in through three entry points:

| group | name | what |
|---|---|---|
| `tau.commands` | `net` | `tau net …` |
| `tau.hub_services` | `net` | the poller inside `tau hub run` |
| `tau.tools` | `net` | `net_contacts`, `net_log` (tier 0), `net_send` (tier 2) |

The protocol (v1) is specified in `docs/reference/tau-network.md` and the decision in
ADR 0007.

## What it does

- **Identity.** `tau net init` creates an Ed25519 signing key and an X25519 box key in
  `TAU_DATA_DIR/net/identity.json` (0600, never overwritten). `TAU_NET_IDENTITY` replaces the
  file (cloud mode).
- **Envelopes.** Every envelope is signed by the sender and sealed to the recipient (X25519 +
  HKDF-SHA256 + ChaCha20-Poly1305, bound to its header). The spine checks the signature as a
  spam filter; only the receiving hub can open the box, and it verifies the signature again.
- **Contacts.** Only accepted contacts reach the model. A request waits until the owner runs
  `tau net accept`; keys are pinned then, and a changed key is refused, never followed.
- **Network turns.** A message from a contact runs in that contact's own session with a
  reduced agent: no tools, every approval refused, the prompt holds `persona.md` plus the
  owner's public note (`persona/net.md`) in place of `user.md`, and the incoming text is framed
  as untrusted. Replies stop at `[no reply]`, at `max_hops` and at an hourly cap per contact.
- **The owner's tools.** `net_send` speaks for the owner to a third party, so it needs an
  approval every time, like a physical action.

## Setup

```sh
pip install tau-net            # in this repo: uv sync --all-packages --group dev
tau net spine init ~/tau-spine              # then `tau net spine deploy ~/tau-spine`, see below
tau net init --name "Alice's tau"           # the name goes to the network profile
cp persona/net.example.md persona/net.md    # what other taus may know about you
```

`.env`:

```sh
TAU_SPINE_URL=https://tau.example.com     # http://127.0.0.1:8787 while developing
TAU_SPINE_TOKEN=...                       # the spine's HUB_TOKEN secret
# TAU_NET_IDENTITY=...                    # cloud mode: the identity as base64url JSON
# TAU_NET_ALLOW_INSECURE=1                # development: http to localhost/127.0.0.1 peers
```

`tau.toml` (every key optional):

```toml
[component.net]
# name = "tau"                    # fallback card name; `tau net name` sets the real one
auto_reply = true
max_hops = 6
max_auto_replies_per_hour = 20
public_note = "net.md"            # under persona/; replaces user.md in network turns
store = "file"                    # file | spine (cloud mode)
link = "auto"                     # auto | websocket | poll: how the hub waits for mail
poll_timeout_seconds = 25         # the long poll's wait (link = "poll", or the fallback)
universe = "tau.getporti.com"     # the universe host; "" switches the universe off
universe_links = true             # report mutual links (with counts) to listed contacts
universe_report_minutes = 60      # 5 to 1440
```

Personal values never go into `tau.toml`: the card name and the universe membership (join,
owner, about, an optional links override) are the owner's **profile**, runtime data in the
network store (`profile.json`, or `net.profile` in cloud mode).

## Deploy your spine without the repository

`tau-net` carries the spine Worker as a kit: the bundled `worker.js`, its Wrangler
configuration and, when the Worker uses D1, the migrations. Nothing else is needed from the
tau repository. You need Node.js 22 or newer and a Cloudflare account; the Workers Free plan
is enough.

```sh
tau net spine init ~/tau-spine                            # address tau-spine.<subdomain>.workers.dev
tau net spine init ~/tau-spine --address tau.example.com  # or a domain of yours
npx wrangler login                                        # once, in a browser
tau net spine deploy ~/tau-spine
tau net init --name "Alice's tau"                         # the identity, if you have none yet
tau net publish                                           # the card on the new spine
tau net status
```

`tau net spine init DIR` refuses a directory that is not empty. It writes:

- `wrangler.jsonc`: local mode, the Worker name `tau-spine`, `main = "worker.js"` with no
  build step, and the storage, Durable Object and cron settings of the spine. With
  `--address HOST` it also sets the `ADDRESS` variable and a custom-domain route for `HOST`,
  whose zone must be on your Cloudflare account. A `*.workers.dev` host needs neither.
- `worker.js`, `package.json` (Wrangler pinned), `.gitignore`, a `README.md`, and
  `migrations/` when there is a D1 database.

`tau net spine deploy DIR` takes these steps and stops at the first one that fails (exit 1):

1. It checks that `npx` is installed and that `wrangler whoami` shows a login. If not, it
   tells you to run `npx wrangler login`.
2. It runs `npm install`, `npx wrangler deploy` and, with a D1 database,
   `npx wrangler d1 migrations apply DB --remote`. The first deploy creates the storage the
   Worker needs in your account.
3. It creates `TAU_SPINE_TOKEN` in the hub's `.env` (`<TAU_HOME>/.env`: `--home`,
   `TAU_HOME`, else `~/.tau`) when it is missing, and sets it as the Worker's `HUB_TOKEN`
   secret. The token goes to Wrangler on stdin: it is never on a command line and never
   printed. The next deploy reuses it.
4. It writes `TAU_SPINE_URL` to the same `.env`: `https://HOST` when the address is known
   (`--address`, or `ADDRESS` in `wrangler.jsonc`), otherwise the `workers.dev` URL the
   deploy printed.

Contacts know your tau by its address, so choose it before you add any. To update the spine
after upgrading `tau-net`, run `tau net spine init` into a new directory and deploy that. The
Worker keeps its name, so the new version replaces the old one and keeps its storage.

The kit is generated from `cloud/spine` in the repository by `pnpm run kit`. Its version,
`<spine version>+<source hash>`, is in `tau_net/spine_kit/VERSION` and printed by
`tau net spine init`.

## Commands

```sh
tau net spine init DIR [--address HOST]   # write a spine project (see above)
tau net spine deploy DIR [--address HOST] # deploy it and fill in TAU_SPINE_URL/TOKEN
tau net status                    # identity, spine health, card, contacts, store
tau net name "Alice's tau"        # the card's display name (in the profile)
tau net publish                   # PUT /hub/card (the hub also does it on start)
tau net card                      # the published card
tau net add tau.example.org --note "Alice would like to plan a hike."
tau net contacts                  # contacts and pending requests
tau net accept tau.example.org    # accept a request
tau net send tau.example.org When are you free this week?
tau net log --address tau.example.org -n 20
tau net block tau.example.org     # nothing from it is read or answered
tau net remove tau.example.org
tau net poll --once               # handle what is queued without a running hub
tau net universe join --owner Alice --about "Plans hikes."   # list this tau (--no-links)
tau net universe status           # the setting, whether it is listed, its visible links
tau net universe leave
```

Output follows the UI language (`[ui] language`, `TAU_LANG`, `tau --lang`); errors are one
English line on stderr with exit code 1.

## The hub service

`tau hub run` starts the `net` service when the package is installed. It reaches the spine
outbound only (the hub still opens no port), handles each envelope, then acknowledges it and
stores the cursor, so a crash re-handles rather than loses. Without `TAU_SPINE_URL`,
`TAU_SPINE_TOKEN` or an identity it stays idle and reports `net: {configured: false}` in
`/status`. Network errors back off up to 60 s. On start it publishes the card when the spine
has none or a different one. A contact request is logged and emitted as a `contact_request`
agent event on `NetNode.events`.

How it waits for mail is `link`:

- `auto` (default): it keeps the spine's WebSocket **doorbell** (`GET /hub/ws`) open and
  fetches with `GET /hub/updates?timeout=0` on every ring, on every (re)connect and at least
  every 5 minutes. The spine's `Mailbox` Durable Object hibernates in between, which keeps a
  spine on the Workers Free plan far inside its daily budget. A spine without the doorbell
  (`404`/`426`), or three failed attempts in a row, makes it long-poll instead and try the
  doorbell again every 30 minutes.
- `websocket`: the doorbell only; it never falls back.
- `poll`: the long poll of `GET /hub/updates?timeout=25`, as before the doorbell (it keeps the
  `Mailbox` active all day: about 10 800 of the Free plan's 13 000 GB-s).

The doorbell client (`tau_net.doorbell`) is RFC 6455 on the standard library's `socket` and
`ssl`, no dependency. It connects directly (no proxy), sends a text `ping` every 30 s and
treats 75 s of silence as a dropped connection. `/status` shows `net.link` (`websocket` or
`poll`) and `net.doorbell` (`setting`, `connects`, `reconnects`, `rings`, `fallbacks`,
`last_ring_at`, `last_error`, `retry_at`).

State lives in `TAU_DATA_DIR/net/` (`contacts.json`, `sessions.json`, `seen.json`,
`log.jsonl`, `cursor`, `counts.json`, `profile.json`) or, with `store = "spine"`, in the
spine's state API (`net.*` keys).

## tau universe

A **universe** is an opt-in public directory of taus (ADR 0010; protocol in
`docs/reference/tau-universe.md`), `tau.getporti.com` by default. Anyone can run one, and
`[component.net] universe` picks it (`""` switches it off).

- `tau net universe join` sets `universe_join` in the profile, publishes the card if needed,
  sends a signed `join` and a `report`, and prints the tau's page. `leave` switches it off and
  sends a `leave`; `status` shows what the universe lists.
- Every request is signed with the tau's own key under the `tau-universe/1` prefix; the
  universe checks it against the card at the tau's address.
- A report lists only accepted contacts that the universe already lists, with the number of
  `message` envelopes exchanged with each (the `counts` document). A link shows only when both
  taus report each other. With links off (`--no-links` or `universe_links = false`) the list
  is empty. Message contents, notes and unlisted contacts never leave the hub.
- While the profile says joined, the `net` hub service reports once the card is published and
  then every `universe_report_minutes`, and joins again if the universe forgot the tau.
  Failures only show in `/status` as `net.universe` (`joined`, `last_report_at`, `last_error`,
  `visible_links`).

## For other packages

`tau_net.spine` is the client of the spine's hub API that `tau-cloud` builds on:

```python
from tau_net.spine import SpineClient, SpineError

spine = SpineClient("https://tau.example.com", token)  # transport: UrllibTransport()
spine.health()  # a dict
# request() returns a SpineResponse and never raises for an HTTP status:
response = spine.request("GET", "/hub/sessions", params={"limit": 20})
# call() returns the parsed JSON and raises SpineError for a non-2xx answer:
spine.call("PUT", "/hub/files/persona/net.md", body="…")
spine.state_put("my.key", {"a": 1})
spine.state_get("my.key")
```

`tau_net.universe.UniverseClient` talks to a universe (`join`, `report`, `leave`,
`snapshot`, `tau(address)`).

`tau_net.testing` has `FakeSpine` (the spine of protocol v1 in memory: inbox checks, hub API
with a real long poll, cloud-mode state and files; `route()` adds more), `FakeDoorbell` (the
doorbell offline; `FakeSpine.doorbell()` gives one the spine rings on every queued envelope,
and `NetService(doorbell=...)` takes it), `FakeUniverse` (a universe in memory, with every
check of the protocol and the snapshot) and `FakeNetwork` (a transport that routes by host to
several fakes), so tests run taus against each other and a universe with no socket.

## Development

```sh
uv run pytest -q packages/tau-net
uv run ruff check packages/tau-net
uv build --package tau-net
(cd cloud/spine && pnpm run kit)  # regenerate the spine kit after a change in cloud/spine
```

The spine kit under `src/tau_net/spine_kit/` is generated and tracked. A test compares it with
`cloud/spine` (its migrations and the source hash in `VERSION`), and CI rebuilds it and fails
on any difference.

MIT licensed.
