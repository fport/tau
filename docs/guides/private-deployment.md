# Private deployment (Cloudflare Tunnel + Access)

This guide prepares the front door for tau's browser interface: one hostname, reachable from any device, with your identity checked at the edge and no inbound port on the hub. It has two options. **A** needs no domain and uses Tailscale Serve; **B** uses your own domain through Cloudflare Tunnel and Cloudflare Access. The threat model comes first, because every step below follows from it.

!!! info "Planned (roadmap issue 074): the web UI"
    The page you will put behind this door, `tau-web`, does not exist yet. Its first slice is the existing TUI served in the browser through `textual-serve`; a proper web app follows when voice from the phone needs the browser microphone (issue 080). Until then, this guide has you verify the door with a placeholder page so the tunnel, DNS and Access policy are known-good the day the web UI lands. Nothing in tau listens for outside traffic today: the hub's control API binds to `127.0.0.1` only and answers 403 to any non-loopback `Host` header.

## The threat model in plain words

What you protect: the facts tau knows about you, your conversations and memory (life data); your credentials; the machine tau runs on; and the devices tau can touch. Who attacks: someone who finds a public endpoint, someone who gets text in front of the agent (a Telegram message, a fetched web page, a tool result) and talks it into misusing a tool, and someone who reads data at rest in a third party's store.

The decisions that follow, all from [ADR 0006](../adr/0006-private-first-topology.md):

1. **One public surface, identity at the edge.** Exactly one hostname serves the hub's web UI. It reaches the hub through an *outbound* tunnel, so the hub opens no inbound port, ever. An Access policy in front of it means unauthenticated requests never reach the tunnel.
2. **No intermediary can approve.** A tier-2 approval is accepted only from the TUI, TauBar, the web UI behind Access with a per-device key, and Telegram polled directly. There is no relay server, so there is nothing to compromise between you and the hub.
3. **Life data stays on the hub.** Cloudflare receives only client-side encrypted backups. Access sees your email, not your data.
4. **Every inbound text is untrusted.** Shell, file and other write tools are tier 2 or sandboxed; web-fetching tools use an allowlist.

The [threat model page](../architecture/threat-model.md) has the table of what an attacker gets from each compromised piece.

## What stays local

| Stays on the hub | Reaches Cloudflare |
|---|---|
| `persona/user.md`, `.env` | your email, as the Access identity |
| sessions, settings, memory, knowledge base | request metadata for `hub.tau.<your-domain>` (Access logs) |
| the approval decision and the per-device key | an `age`-encrypted backup bundle in a private R2 bucket, if you set up [backups](backups.md) |
| the tunnel credentials file (`~/.cloudflared/<UUID>.json`) | the tunnel's existence and its DNS record |

## Option A: Tailscale Serve (no domain)

Tailscale Serve exposes a local port to your tailnet over HTTPS, with a certificate Tailscale issues for the machine's MagicDNS name. No public DNS, no Cloudflare account, and only devices signed in to your tailnet can reach it. It is the default when you have no domain, and the [phone guide](phone-tailscale-termius.md) already put the hub and your phone on the same tailnet.

1. In the Tailscale admin console, enable **MagicDNS** and **HTTPS certificates** for the tailnet (Serve requires both).
2. Start a placeholder page on the hub, standing in for the web UI:

    ```sh
    mkdir -p /tmp/tau-door && echo '<h1>tau door</h1>' > /tmp/tau-door/index.html
    cd /tmp/tau-door && python3 -m http.server 8000 --bind 127.0.0.1
    ```

3. Serve that port on the tailnet, in the background:

    ```sh
    tailscale serve --bg 8000
    tailscale serve status
    ```

    The status line reads `https://my-mac.tailXXXXXX.ts.net` with `proxy http://127.0.0.1:8000` under it.

4. Open that URL on the phone (Tailscale on). You should see the placeholder.
5. Turn it off again until the web UI exists:

    ```sh
    tailscale serve reset
    ```

!!! note
    Serve is tailnet-only. Do **not** use `tailscale funnel`, which publishes the port to the whole internet without any identity check in front of it.

## Option B: Cloudflare Tunnel + Access at `hub.tau.<your-domain>`

You need a domain whose DNS is on Cloudflare (a free zone is enough) and a Cloudflare account with Zero Trust enabled (the free plan covers up to 50 users). Moving a domain's nameservers to Cloudflare is [roadmap issue 022](https://github.com/fport/tau/blob/main/roadmap/L3-cloud/022-move-dns-to-cloudflare.md); do it first and verify your mail records by hand.

!!! info "Planned (roadmap issue 076): `tau setup tunnel`"
    A helper will script the safe parts of this section (tunnel creation, the config file, the DNS route, the service install) and print the Access steps it cannot do for you. Until then, the steps are manual and generic; the Cloudflare dashboard changes its labels now and then, so read them as "the screen that does this".

### B.1 Install `cloudflared`

=== "macOS"

    ```sh
    brew install cloudflared
    ```

=== "Linux (Raspberry Pi OS, Debian, Ubuntu)"

    ```sh
    sudo mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
    sudo apt-get update && sudo apt-get install cloudflared
    ```

    For an arm64 Pi without the repository: the `.deb` at `https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb`.

### B.2 Create the tunnel

```sh
cloudflared tunnel login                 # opens the browser; pick the zone of <your-domain>
cloudflared tunnel create tau            # prints the tunnel UUID and writes ~/.cloudflared/<UUID>.json
cloudflared tunnel list
```

The JSON file is the tunnel's credential. It stays on the hub with `0600` permissions and is never copied anywhere.

### B.3 Write the config

`~/.cloudflared/config.yml` (or `/etc/cloudflared/config.yml` for a system service):

```yaml
tunnel: <UUID>
credentials-file: /Users/<you>/.cloudflared/<UUID>.json

ingress:
  - hostname: hub.tau.<your-domain>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

The last rule is required: anything that is not `hub.tau.<your-domain>` gets a 404 from `cloudflared` itself. Validate the file:

```sh
cloudflared tunnel ingress validate
```

Port 8000 is the placeholder from Option A; it becomes the web UI's port when `tau-web` exists.

### B.4 Route DNS and run

```sh
cloudflared tunnel route dns tau hub.tau.<your-domain>     # a proxied CNAME to <UUID>.cfargotunnel.com
cloudflared tunnel run tau
```

With the placeholder server running, `https://hub.tau.<your-domain>` now shows it, from anywhere. **Stop here and do B.5 before you leave it running**: at this point the hostname is public and unauthenticated.

### B.5 Put Access in front of it

In the Cloudflare dashboard, open **Zero Trust**.

1. **Login method.** **Integrations → Identity providers → Add new identity provider → One-time PIN.** No IdP to configure: Access emails you a code at login. (You can add Google, GitHub or another IdP later.)
2. **Application.** **Access controls → Applications → Create new application → Self-hosted and private**, then **Add public hostname** and enter `hub.tau` as the subdomain and `<your-domain>` as the domain. Give it a session duration you are comfortable with; 24 hours is a reasonable start on a phone you unlock anyway.
3. **Policy.** Add a policy with action **Allow** and one **Include** rule: selector **Emails**, value your email address. Nothing else. `Everyone` must not appear in an Allow policy for this application.
4. **Optional device rule.** To require an enrolled device as well, add a **Require** rule with the **Warp** or **Gateway** selector (it appears once the device posture checks are enabled) and install the Cloudflare One client on the phone. This turns "your email" into "your email on your device".
5. Save. Open `https://hub.tau.<your-domain>` in a private window: you get the Access login page, enter your email, paste the PIN from the mail, and only then the placeholder.

!!! warning "Verify the deny path too"
    Log in with a second email that is not in the policy. It must say the account does not have access. If it reaches the page, the policy is wrong; fix it before anything real sits behind it.

### B.6 Run `cloudflared` as a service

=== "macOS"

    ```sh
    cloudflared service install           # a user launch agent; config at ~/.cloudflared/config.yml
    ```

    `sudo cloudflared service install` instead installs a system daemon that reads `/etc/cloudflared/config.yml` and starts at boot; `sudo launchctl start com.cloudflare.cloudflared` starts it and the logs are under `/Library/Logs/com.cloudflare.cloudflared.*.log`.

=== "Linux"

    ```sh
    sudo cloudflared --config ~/.cloudflared/config.yml service install
    sudo systemctl enable --now cloudflared
    sudo systemctl status cloudflared
    ```

### B.7 Tear the placeholder down

Stop the `python3 -m http.server` placeholder. The hostname now answers 502 behind Access, which is exactly right until `tau-web` listens on that port.

## Keep these rules

- **Never open an inbound port** for tau, and never `tailscale funnel` it. The tunnel and Serve are both outbound from the hub.
- **One hostname.** The mesh, sshd and the hub's control API stay tailnet-only or loopback-only; they never go through the tunnel.
- **Access before exposure.** Create the policy before the first `tunnel run` that stays up, or stop the tunnel between B.4 and B.5.
- **Approvals need more than a login.** When the web UI arrives, a tier-2 approval from the browser will also need a per-device key on top of Access (ADR 0006, decision 5). A stolen Access session alone will not move anything.

## Planned around this guide

| Piece | Issue | What it adds |
|---|---|---|
| `tau-web` | 074 | the TUI in the browser through `textual-serve`, then a web app with a microphone |
| `tau setup tunnel` | 076 | scripts B.2, B.3, B.4 and B.6 and prints the Access steps |
| Domain on Cloudflare | 022 | the nameserver move, mail records verified |
| Tunnel + Access in front of the hub | 023 | the policy as configuration in the repository, not only dashboard clicks |
