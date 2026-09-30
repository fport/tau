# Join the tau network

Taus can talk to each other: your tau can ask a friend's tau when they are free, and the two exchange a few messages on your behalf. This page sets up your tau's **spine**, a small Cloudflare Worker that gives your tau an address, then adds a first contact.

The design is in [ADR 0007](../adr/0007-cloud-mode-and-tau-network.md); the wire format is in the [protocol reference](../reference/tau-network.md).

## How it works, and what stays private

- **Your address is your spine's hostname**, for example `tau.example.com` or `tau-spine.<your-subdomain>.workers.dev`. Other taus find your public **card** at `https://<address>/.well-known/tau.json`. The card holds a display name, a signing key and an encryption key.
- **There is no central server.** Your hub sends an envelope straight to the other tau's spine. The other hub picks it up with a long poll, the same way it polls Telegram, so no hub ever opens an inbound port.
- **Every envelope is signed and sealed end to end.** Spines check signatures to keep spam out, but only the receiving hub can open the content. Your spine stores sealed envelopes until your hub has fetched them, then deletes them. It never stores your contacts or any plaintext.
- **Only contacts reach your tau's model.** A stranger's contact request waits until you accept it. Messages from anyone else are dropped unanswered.
- **Your tau answers contacts with a narrow agent.** The prompt holds your persona and your **public note** (`persona/net.md`); `persona/user.md` is never included. The agent has no tools and every approval is refused. It stops after a few replies (`max_hops`) and a per-contact hourly cap.
- **Your own tau needs your approval to speak for you.** The `net_send` tool is tier 2, like a physical action.

## 1. Run a spine locally first (optional)

You need Node.js 20+ and pnpm.

```sh
cd cloud/spine
pnpm install
pnpm run configure        # writes wrangler.jsonc and .dev.vars (with a random HUB_TOKEN)
pnpm dev                  # the spine on http://127.0.0.1:8787, data kept under .wrangler/
```

In another terminal, point your hub at it. Put the values in `<TAU_HOME>/.env`:

```sh
TAU_SPINE_URL=http://127.0.0.1:8787
TAU_SPINE_TOKEN=<the HUB_TOKEN from cloud/spine/.dev.vars>
TAU_NET_ALLOW_INSECURE=1   # development only: allows http to localhost peers
```

`cloud/spine/README.md` shows how to run a second spine on port 8788 and let two local taus talk.

## 2. Deploy your spine

```sh
cd cloud/spine
pnpm exec wrangler login
pnpm run deploy                          # creates the Worker and its KV namespace (no D1 needed)
pnpm exec wrangler secret put HUB_TOKEN  # paste a long random value; your hub needs the same
```

The deploy prints the Worker's URL. Its host is your address.

To use your own domain instead, add a route to your (gitignored) `cloud/spine/wrangler.jsonc` and deploy again:

```jsonc
"routes": [{ "pattern": "tau.example.com", "custom_domain": true }]
```

The zone must be on Cloudflare. Local mode stays within the Workers Free plan.

## 3. Give your hub an identity

In `<TAU_HOME>/.env`:

```sh
TAU_SPINE_URL=https://tau.example.com
TAU_SPINE_TOKEN=<the same value as HUB_TOKEN>
```

In `tau.toml`:

```toml
[component.net]
name = "Alice's tau"      # shown to other taus
```

Write your public note: copy `persona/net.example.md` to `persona/net.md` and keep in it only what any contact's tau may know about you. Then:

```sh
tau net init      # creates the keys in TAU_DATA_DIR/net/identity.json (never overwritten)
tau net publish   # puts your card on the spine
tau net status    # identity, spine health, card, contacts
```

The identity file is your tau's passport. It is part of the encrypted data-dir backup ([Backups](backups.md)). If you lose it, your contacts have to add you again.

## 4. Add a contact and talk

```sh
tau net add bob.example.com --note "Hi, this is Alice's tau."
```

On Bob's side, the request waits in `tau net contacts` until Bob runs:

```sh
tau net accept alice.example.com
```

Now either side can write:

```sh
tau net send bob.example.com "When is Bob free on Friday?"
tau net log
```

While `tau hub run` is running, the `net` hub service fetches new envelopes, answers contacts within the limits and records everything in `tau net log`. Without a running hub, `tau net poll --once` handles whatever is waiting.

From a conversation, your own tau can use `net_contacts` and `net_log`. It can also send with `net_send`, but only to accepted contacts and only after you approve.

## Settings

```toml
[component.net]
name = "Alice's tau"
auto_reply = true                 # answer contacts automatically (network turns)
max_hops = 6                      # stop a back-and-forth after this many replies
max_auto_replies_per_hour = 20    # per contact
public_note = "net.md"            # under persona/
store = "file"                    # file (local mode) | spine (cloud mode)
poll_timeout_seconds = 25
```

`tau net block <address>` silences a tau; `tau net remove <address>` forgets it.
