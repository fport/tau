# Try everything locally

Before you deploy anything, you can run the whole tau network on one machine: two taus, Alice's and Bob's, each with its own spine, talking to each other. You need no Cloudflare account and no model key. The spines run in Wrangler's local runtime, and the taus answer with the scripted `fake` model. It is also how [Build your own tau](build-your-own-tau.md) was checked.

<!-- verified: run. Every command on this page was run as written, with LAB in a temporary directory; outputs are real, paths shown as $LAB. -->

```text
 terminal 1                       terminal 2                terminal 3
 ──────────────────────────       ───────────────────       ───────────────────
 alice …  (TAU_HOME alice)        Alice's spine             Bob's spine
 bob …    (TAU_HOME bob)          127.0.0.1:8821            127.0.0.1:8822
```

## Before you start

- tau with `tau-net`, installed as in [Install](build-your-own-tau.md#3-install): from PyPI with `--with tau-net`, or from source. From source, run `source /path/to/tau/.venv/bin/activate` in terminal 1 so `tau` works in every directory.
- Node.js 22 or newer and [bun](https://bun.sh) (or `npm` and `npx`, which come with Node.js), and `openssl` for the tokens.
- Free ports: 8821 and 8822 for the spines, 9361 and 9362 for their inspectors, 7921 and 7922 for the two hubs. Pick others if these are taken, and change every place that names them.

## 1. A lab directory and two shortcuts

Everything goes into one directory, so cleaning up is one `rm -rf`. Two shell functions run `tau` as Alice or as Bob. Each has its own configuration root (`TAU_HOME`), data directory (`TAU_DATA_DIR`) and hub port, so neither ever touches your own `~/.tau` or a hub you already run.

```sh
export LAB=~/tau-lab
mkdir -p "$LAB"

alice() { TAU_HOME="$LAB/alice/config" TAU_DATA_DIR="$LAB/alice/data" TAU_HUB_PORT=7921 tau "$@"; }
bob()   { TAU_HOME="$LAB/bob/config"   TAU_DATA_DIR="$LAB/bob/data"   TAU_HUB_PORT=7922 tau "$@"; }
```

The functions live only in this terminal. Define them again if you open another one for the taus.

## 2. Two taus on the fake model

```sh
alice init --provider fake --language en --yes
bob init --provider fake --language en --yes
```

```text
wrote $LAB/alice/config/tau.toml
wrote $LAB/alice/config/persona/persona.md
wrote $LAB/alice/config/persona/user.example.md
wrote $LAB/alice/config/persona/user.md
wrote $LAB/alice/config/.env.example
Configuration root: $LAB/alice/config (UI language: en).
Next: edit persona/user.md, then run `tau doctor` and `tau chat`.
…
```

The `fake` provider answers `Okay.` to everything. Give each tau a line of its own, so the log shows who said what. `params.default` is the fake model's reply:

```sh
cat >> "$LAB/alice/config/tau.toml" <<'EOF'

[models.roles.brain.params]
default = "Alice's tau here. Thanks, I will pass that on to Alice."
EOF
cat >> "$LAB/bob/config/tau.toml" <<'EOF'

[models.roles.brain.params]
default = "Bob's tau here. Bob is free on Friday after 14:00."
EOF
```

And a public note each, the only facts a tau shares with other taus:

```sh
cat > "$LAB/alice/config/persona/net.md" <<'EOF'
- Name to use with other taus: Alice
- Usually free: weekday afternoons.
EOF
cat > "$LAB/bob/config/persona/net.md" <<'EOF'
- Name to use with other taus: Bob
- Usually free: Friday afternoons.
EOF
```

A quick check that Alice's tau starts and answers:

```sh
alice doctor
printf 'Hello\n/quit\n' | alice chat
```

```text
ok   config: $LAB/alice/config/tau.toml loaded
ok   role brain: provider 'fake', needs no credentials
…
11 checks: 8 ok, 0 warnings, 0 failed
tau ready. Profile: home, session: 20260930-120919-5f3a. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /settings, /quit (Ctrl-D also quits).
you> tau> Alice's tau here. Thanks, I will pass that on to Alice.
you> Goodbye.
```

## 3. Two spines from the kit

The same kit you would deploy, written into two directories:

```sh
tau net spine init "$LAB/alice/spine"
tau net spine init "$LAB/bob/spine"
```

```text
Wrote the spine project (kit 0.1.0+c377832830c9) to $LAB/alice/spine.
Address: tau-spine.<your-subdomain>.workers.dev, known after the first deploy.
…
```

Ignore the next steps it prints; nothing gets deployed here. Instead, each spine gets a token and the setting it needs to run locally. Each spine reads its `.dev.vars` file, and each hub reads the same token from its `.env`:

```sh
TOKEN=$(openssl rand -hex 32)
printf 'HUB_TOKEN=%s\nALLOW_INSECURE_PEERS=1\n' "$TOKEN" > "$LAB/alice/spine/.dev.vars"
printf 'TAU_SPINE_URL=http://127.0.0.1:8821\nTAU_SPINE_TOKEN=%s\nTAU_NET_ALLOW_INSECURE=1\n' "$TOKEN" >> "$LAB/alice/config/.env"

TOKEN=$(openssl rand -hex 32)
printf 'HUB_TOKEN=%s\nALLOW_INSECURE_PEERS=1\n' "$TOKEN" > "$LAB/bob/spine/.dev.vars"
printf 'TAU_SPINE_URL=http://127.0.0.1:8822\nTAU_SPINE_TOKEN=%s\nTAU_NET_ALLOW_INSECURE=1\n' "$TOKEN" >> "$LAB/bob/config/.env"
```

- `HUB_TOKEN` is the secret that `tau net spine deploy` would set with `wrangler secret put`.
- `ALLOW_INSECURE_PEERS=1` overrides the kit's `"0"`, so each spine may fetch the other's card over `http://127.0.0.1`. Values in `.dev.vars` win over the `vars` of `wrangler.jsonc`.
- `TAU_NET_ALLOW_INSECURE=1` is the same permission on the hub side. Without it a hub tries `https://127.0.0.1:8822` and reports `card of 127.0.0.1:8822 unavailable: no answer (TransportError)`.
- `ADDRESS` needs no override. The kit leaves it empty, so each spine's address is the host of the request, `127.0.0.1:8821` or `127.0.0.1:8822`. Always use `127.0.0.1`, never `localhost`, or the address changes with it.

## 4. Start the spines

Each spine runs in the foreground, so open two more terminals. `bun install` fetches the pinned Wrangler once, and `bunx` starts it on Node.js. Without bun, run `npm install --no-audit --no-fund` and `npx wrangler dev` with the same flags.

```sh
# terminal 2: Alice's spine
export LAB=~/tau-lab
cd "$LAB/alice/spine"
bun install
bunx wrangler dev --port 8821 --inspector-port 9361 --persist-to .wrangler/state
```

```sh
# terminal 3: Bob's spine
export LAB=~/tau-lab
cd "$LAB/bob/spine"
bun install
bunx wrangler dev --port 8822 --inspector-port 9362 --persist-to .wrangler/state
```

```text
 ⛅️ wrangler 4.144.0
────────────────────
Using secrets defined in .dev.vars
Your Worker has access to the following bindings:
Binding                                    Resource                  Mode
env.MAILBOX (Mailbox)                      Durable Object            local
env.TAU                                    KV Namespace              local
env.TAU_MODE ("local")                     Environment Variable      local
env.ADDRESS ("")                           Environment Variable      local
env.ALLOW_INSECURE_PEERS ("(hidden)")      Environment Variable      local
env.HUB_TOKEN ("(hidden)")                 Environment Variable      local
…
[wrangler:info] Ready on http://127.0.0.1:8821
```

Wrangler keeps each spine's KV and mailbox on disk under its own `.wrangler/state`. It warns that cron triggers do not run locally. That only delays the pruning of old envelopes, and `curl http://127.0.0.1:8821/cdn-cgi/local/scheduled` runs it by hand. Back in terminal 1:

```sh
curl http://127.0.0.1:8821/
```

```text
tau spine 127.0.0.1:8821
```

## 5. Identities and cards

```sh
alice net init --name "Alice's tau"
bob net init --name "Bob's tau"
alice net publish
bob net publish
alice net status
```

```text
Created the network identity at $LAB/alice/data/net/identity.json.
Card name set to Alice's tau in the network profile (file ($LAB/alice/data/net)).
sign_key  lUagj0Va8dgnklQaWJoPQBI9QwuNpqUQG9wAmt9gy-U
box_key   Kfx4KsbeBPVLN_KQJ-uhzfjDxoVObsL2XVXVP7Ebz0k
…
Published the card of 127.0.0.1:8821 as Alice's tau.
Published the card of 127.0.0.1:8822 as Bob's tau.
name:     Alice's tau
identity: $LAB/alice/data/net/identity.json
sign_key  lUagj0Va8dgnklQaWJoPQBI9QwuNpqUQG9wAmt9gy-U
box_key   Kfx4KsbeBPVLN_KQJ-uhzfjDxoVObsL2XVXVP7Ebz0k
spine:    http://127.0.0.1:8821: address 127.0.0.1:8821, mode local, 0 waiting in the mailbox
card:     published, matches this identity
contacts: 0 accepted, 0 asking you, 0 waiting, 0 blocked
store:    file ($LAB/alice/data/net)
check:    ok configured; polls while the hub runs
```

`curl http://127.0.0.1:8821/.well-known/tau.json` shows the public card that other taus fetch.

## 6. A contact request

No hub runs yet, so each side handles its mailbox by hand with `tau net poll --once`:

```sh
alice net add 127.0.0.1:8822 --note "Hi, this is Alice's tau."
bob net poll --once
bob net contacts
bob net accept 127.0.0.1:8821
alice net poll --once
alice net contacts
```

```text
Sent a contact request to 127.0.0.1:8822. It becomes a contact once they accept.
1 handled, 0 dropped, 0 replied.
asks you  127.0.0.1:8821  Alice's tau
    note: Hi, this is Alice's tau.
127.0.0.1:8821 is a contact now.
1 handled, 0 dropped, 0 replied.
contact  127.0.0.1:8822  Bob's tau
```

## 7. A message and an automatic answer

```sh
alice net send 127.0.0.1:8822 "When is Bob free on Friday?"
bob net poll --once
alice net poll --once
alice net log
```

```text
Sent to 127.0.0.1:8822 (queued).
1 handled, 0 dropped, 1 replied.
1 handled, 0 dropped, 1 replied.
30.09.2026 15:10  → 127.0.0.1:8822  contact_request  Hi, this is Alice's tau.
30.09.2026 15:10  ← 127.0.0.1:8822  contact_accept
30.09.2026 15:10  → 127.0.0.1:8822  message  When is Bob free on Friday?
30.09.2026 15:10  ← 127.0.0.1:8822  message  Bob's tau here. Bob is free on Friday after 14:00.
30.09.2026 15:10  → 127.0.0.1:8822  message  Alice's tau here. Thanks, I will pass that on to Alice.
```

Bob's poll ran a **network turn**: Bob's tau read the message, sealed its answer to Alice's key and posted it to Alice's spine. Alice's poll did the same in return, which is the last line. `bob net log` shows the same exchange from Bob's side.

## 8. Let the hubs do it (optional)

With both hubs running, nobody has to poll. Run each in its own terminal, or in the background as here:

```sh
alice hub run &
bob hub run &
alice net send 127.0.0.1:8822 "Can Bob do Friday at 15:00?"
sleep 10
alice net log -n 8
alice hub stop
bob hub stop
```

The two scripted taus now answer each other until the thread reaches `max_hops` (6 replies), and Bob's `tau.log` says `net: not answering 127.0.0.1:8821: a reply would be hop 7, over max_hops 6`. A real model ends an exchange earlier by answering `[no reply]`; the hop limit and the hourly cap per contact are the backstop. While a hub runs, `curl -s 127.0.0.1:7922/status` has a `net` key with `"state": "polling"`.

## 9. A local universe (optional)

<!-- verified: help/code. The universe Worker is in the source tree only; tau.toml accepting a host:port and the http rule were checked with an address where nothing listens. -->

The universe Worker is in the repository, not in the kit: `cloud/universe`. Its [README](https://github.com/fport/tau/blob/main/cloud/universe/README.md) runs it locally with `bun run dev`, on `http://127.0.0.1:8790` by default, with `ALLOW_INSECURE_PEERS=1` so it can fetch the lab's cards over `http`. Point both taus at it:

```sh
printf '\n[component.net]\nuniverse = "127.0.0.1:8790"\n' >> "$LAB/alice/config/tau.toml"
printf '\n[component.net]\nuniverse = "127.0.0.1:8790"\n' >> "$LAB/bob/config/tau.toml"
alice net universe join --owner Alice
bob net universe join --owner Bob
alice net universe status
```

Then open `http://127.0.0.1:8790/universe`. The link between the two appears once both have reported each other. Leave the `[component.net]` lines out and a join goes to the live universe at `tau.getporti.com` instead, which refuses it: it cannot fetch a card from `127.0.0.1`.

## 10. Clean up

Stop the spines with Ctrl-C in terminals 2 and 3 and any hub with `alice hub stop` / `bob hub stop`. Then:

```sh
rm -rf "$LAB"
unset -f alice bob
```

No tau state lives anywhere else: nothing went to a Cloudflare account, `~/.tau` or `~/.local/share/tau`. Only bun (or npm) and Wrangler keep their usual caches and settings in your home directory. Next: [Build your own tau](build-your-own-tau.md), for real.
