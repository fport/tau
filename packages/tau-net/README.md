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
tau net init --name "Alice's tau"
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
name = "Alice's tau"              # display name on the card
auto_reply = true
max_hops = 6
max_auto_replies_per_hour = 20
public_note = "net.md"            # under persona/; replaces user.md in network turns
store = "file"                    # file | spine (cloud mode)
poll_timeout_seconds = 25
```

## Commands

```sh
tau net status                    # identity, spine health, card, contacts, store
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
```

Output follows the UI language (`[ui] language`, `TAU_LANG`, `tau --lang`); errors are one
English line on stderr with exit code 1.

## The hub service

`tau hub run` starts the `net` service when the package is installed. It long-polls
`GET /hub/updates` on the spine (outbound only, so the hub still opens no port), handles each
envelope, then acknowledges it and stores the cursor, so a crash re-handles rather than
loses. Without `TAU_SPINE_URL`, `TAU_SPINE_TOKEN` or an identity it stays idle and reports
`net: {configured: false}` in `/status`. Network errors back off up to 60 s. On start it
publishes the card when the spine has none or a different one. A contact request is logged
and emitted as a `contact_request` agent event on `NetNode.events`.

State lives in `TAU_DATA_DIR/net/` (`contacts.json`, `sessions.json`, `seen.json`,
`log.jsonl`, `cursor`) or, with `store = "spine"`, in the spine's state API (`net.*` keys).

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

`tau_net.testing` has `FakeSpine` (the spine of protocol v1 in memory: inbox checks, hub API
with a real long poll, cloud-mode state and files; `route()` adds more) and `FakeNetwork` (a
transport that routes by host to several fake spines), so tests run two taus against each
other with no socket.

## Development

```sh
uv run pytest -q packages/tau-net
uv run ruff check packages/tau-net
uv build --package tau-net
```

MIT licensed.
