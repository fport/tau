# Move the hub to a Raspberry Pi

The hub is the one machine that runs the agent, the hub services and, later, the mesh router. A MacBook is a fine first hub and a poor permanent one: it sleeps, it leaves the house, it gets its lid closed. A Raspberry Pi 5 on a shelf, plugged in, on the tailnet, is the natural end state. This page says what "moving the hub" means, what you can do by hand today, and what the roadmap will automate.

!!! info "Planned (roadmap issue 048): self-replication"
    The intended way to move is to tell tau: *"move the hub to the RPi5"*. tau provisions the Pi over SSH (uv, the packages, the systemd unit, later `zenohd`), copies its configuration and data, hands over the hub role and demotes the Mac to a **node** with its `mac.*` tools. Every step is tier 2 and asks for approval; the handover loses no queued messages; a rollback path back to the Mac exists. None of that is built; issue 048 waits for the hardware and for the mesh layer (issue 032). The manual steps below are what that automation will do.

## What moving the hub means

There is never more than one active hub. Moving it means:

1. **Configuration** (`TAU_HOME`): `tau.toml`, `.env`, `persona/user.md`, `tools/`. Copied over SSH; `.env` and `user.md` are secrets and life data, so never through a third party.
2. **Data** (`TAU_DATA_DIR`): sessions, hub state, later settings, memory and the knowledge base. Copied, or restored from an [encrypted backup](backups.md).
3. **The service**: `tau hub` under systemd on the Pi, `tau hub uninstall` on the Mac.
4. **The doors**: Tailscale, sshd hardening, and the Cloudflare Tunnel or Tailscale Serve, moved to the Pi so `tau.<your-domain>` points at the new hub.
5. **The role**: the Mac keeps running tau, but as a node (`TAU_ROLE=node`), offering its capabilities to the hub over the mesh (layer 5).

The same code runs on both machines; only `TAU_ROLE` differs.

## By hand, today

### 1. Prepare the Pi

Raspberry Pi OS (64-bit) or Ubuntu Server. Then:

```sh
sudo apt update && sudo apt install -y git tmux mosh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Harden sshd the way the [phone guide](phone-tailscale-termius.md) does (keys only, `AllowUsers` restricted to the tailnet) and add your Termius key. Once tau is installed (the next step), `tau setup run remote` checks all of it and shows the one command that does it, `setup-all.sh`, which runs `setup-linux.sh` on the Pi.

### 2. Install tau

```sh
uv tool install tau-core --with tau-tui --with tau-net --with tau-sub
```

Or from a checkout: `git clone https://github.com/fport/tau.git ~/tau && cd ~/tau && uv sync --all-packages --group dev`.

### 3. Move configuration and data

From the Mac, over the tailnet:

```sh
rsync -a --mkpath "$HOME/.tau/" pi-hub.tailXXXXXX.ts.net:.tau/
rsync -a --mkpath "$HOME/.local/share/tau/" pi-hub.tailXXXXXX.ts.net:.local/share/tau/
```

Or restore from the encrypted bundle as the [backup guide](backups.md) shows. Then on the Pi:

```sh
tau doctor
```

Fix what it flags: usually the model key (`ANTHROPIC_API_KEY`, or your provider's) in `.env`. The budgets need nothing on the Pi: they live in `tau.toml`, and the spend ledger `spend.sqlite3` came over with the data directory, so the current period's spend carries on. Point `TAU_OLLAMA_URL` at the Mac's tailnet address (`http://my-mac.tailXXXXXX.ts.net:11434`) so the `local` role still reaches Ollama there, and let Ollama on the Mac listen on its tailnet address only ([Models and budgets](models-and-budgets.md#set-up-ollama)).

### 4. Start the service

```sh
cd ~/tau
mkdir -p ~/.config/systemd/user
uv run tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
systemctl --user daemon-reload
systemctl --user enable --now tau-hub
loginctl enable-linger "$USER"
tau hub status
```

Details, logs and the restart rules are in [Run tau as a service](hub-service.md).

### 5. Stop the old hub

On the Mac:

```sh
tau hub stop
tau hub uninstall
```

Two hubs at once is a configuration error the mesh will refuse once it exists; today nothing stops you, so be tidy.

### 6. Move the doors

- **Tunnel:** run `cloudflared tunnel create` on the Pi, or copy `~/.cloudflared/<UUID>.json` and `config.yml` over the tailnet and stop `cloudflared` on the Mac. The DNS route follows the tunnel, not the machine.
- **Tailscale Serve:** `tailscale serve reset` on the Mac, `tailscale serve --bg <port>` on the Pi.
- **Termius:** point the host at the Pi's MagicDNS name, keep `tau-attach` as the startup snippet (install it on the Pi: a two-line script that does `tmux new -A -s tau`).

## What is different on a Pi

| Topic | On the Pi |
|---|---|
| Sleep | none; the keep-awake agent and TauBar's sleep modes are Mac-only concerns |
| Service manager | systemd user unit with linger, not launchd |
| Models | nothing extra runs on the Pi: `brain` and `fast` call their provider directly as before, with the same budgets; the `local` role reaches Ollama on the Mac over the tailnet (`TAU_OLLAMA_URL`) and fails over to `fast` within a few seconds while the Mac sleeps or is away; a Pi 5 runs only small models itself |
| Voice | MLX Whisper is Apple-only; the Pi gets a CPU Whisper build (`tau-voice`, planned) |
| Mesh | `zenohd` runs on the hub, so on the Pi; the Mac joins as a node |
| Backups | the same `age` + R2 flow; the key moves with the password manager, not with the disk |

## Rollback

Keep the Mac's `~/.tau` and `~/.local/share/tau` until the Pi has run for a while. To go back: `tau hub stop` on the Pi, sync the data directory back to the Mac (`rsync` the other way, so nothing recorded on the Pi is lost), `tau hub install` on the Mac, move the doors again.
