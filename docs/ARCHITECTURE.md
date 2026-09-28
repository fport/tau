# tau — Mimari Kararlar

> Kaynak: 2026-09-28 grill oturumu. Karar değişirse bu dosyayı güncelle, eski kararı "Değişenler" altına taşı.

tau, hayatı otomatikleştiren kişisel bir "akıllı body": Telegram'dan, terminalden ve sesle konuşulabilen; robot kol, kolye kamera, ev sensörleri ve ileride drone ile fiziksel dünyaya dokunan bir ajan platformu.

## İlkeler

1. **Beyin bulutta düşünür, refleksler yerelde çalışır.** Duruş uyarısı, ev kuralları, acil durdurma asla LLM'e veya Cloudflare'e bağlı olmaz.
2. **Aynı kod her makinede.** Fark sadece rol: `TAU_ROLE=hub|node`. Aynı anda tek aktif hub.
3. **Ayarlar veridir, kod değil.** D1 `settings` tablosu, hub'a hot-reload ile gelir; deploy gerektirmez.
4. **Fiziksel dünyaya ve kendi koduna dokunan her şey onaylıdır** (tier 2).
5. **Donanım yoksa kod da yok.** Elde olmayan cihaz için sadece mesh'te yer ayrılır.

## Kararlar

| Alan | Karar | Not |
|---|---|---|
| Çekirdek | Sıfırdan **Strands Agents** (Python 3.12+, `uv` workspace) | DevDuck sadece referans |
| Paketleme | **Bu repo merkez.** `packages/*` altındaki her paket bağımsız PyPI dağıtımı: `tau-<ad>`, import `tau_<ad>` (düz, namespace yok). Genişletme entry point'lerle (`tau.tools`, sonra `tau.nodes`, `tau.channels`) | `tau`, `tau-hub`, `tau-agent` PyPI'de dolu. Kendi yayın döngüsü gereken paket ayrı repoya taşınır, tau onu PyPI'den kullanır |
| Topoloji | Şimdi **MacBook = hub**; RPi5 gelince hub oraya geçer | Hub offline'ken tau düşünmez, relay kuyruklar |
| State | **Cloudflare**: D1, R2, Vectorize, AI Search — hepsi `tau-cloud` Worker arkasında | Hub D1 REST API'sine doğrudan gitmez |
| Dış kanal girişi | Telegram webhook → Worker → **Durable Object** ← hub'ın outbound WebSocket'i | `chat_id` allowlist; hub offline → kuyruk + "tau offline" cevabı |
| Mesh | **Kontrol = MCP** (streamable HTTP, Tailscale üstü) · **Veri = Zenoh** (olay, telemetri, liveliness ile keşif) | Tailscale'de multicast yok → node'lar `zenohd`'ye açık `connect` ile bağlanır |
| Mikrodenetleyiciler | **ESPHome** (ücretsiz firmware) → MQTT → `zenohd` MQTT plugin → `tau/…` keyspace | Home Assistant yok; gerekirse sonra MCP ile eklenir |
| Modeller | **LiteLLM Proxy** (Docker, image digest pinli) + Postgres; roller `brain` / `fast` / `local` | `brain`=Bedrock Sonnet (fallback Anthropic), `fast`=Bedrock Haiku, `local`=Mac'te Ollama |
| Maliyet koruması | Virtual key başına sert bütçe + AWS Budgets alarmı + Strands max tool iterasyonu | Bedrock Knowledge Bases (OpenSearch Serverless) kullanılmaz |
| Güvenlik | **Tier 0** okuma serbest · **Tier 1** dijital yazma serbest + log · **Tier 2** fiziksel eylem + tau'nun yazdığı tool → Telegram inline onay | Yeni tool'lar `tools/_pending/`'e düşer; kayıtlı rutinler onaydan muaf |
| Remote | macOS **OpenSSH** (key-only, `AllowUsers` ile sadece tailnet + localhost) + **tmux + mosh** + Termius; `CLOUDFLARE_API_TOKEN` ile wrangler | Şarjda uyumama TauBar gelene kadar `caffeinate -s` LaunchAgent'ı. Claude Code `Notification` hook → tau → Telegram "seni bekliyor" |
| TauBar | **Tauri v2 + React/TS**, tray-only; `keepawake` ile `PreventSystemSleep`; `pmset disablesleep` için dar sudoers kuralı | Uyku modları: Normal / **Şarjda uyuma (varsayılan)** / Kapak kapalıyken bile. Python mac-node sidecar olarak TCC iznini devralır |
| Knowledge Base | `kb/` markdown → R2 → **AI Search** (yönetilen) | Periyodik indeksleme |
| Hafıza | `memory` → D1 satırı + Workers AI embedding → **Vectorize** (kendi pipeline, anında upsert) | Ajan içinde **Self-RAG** döngüsü: getir → değerlendir → gerekirse yeniden sorgula |
| Session Recording | Strands `SessionManager` → Worker → D1; `/devam` ile resume, TUI'de replay | **Her şey kalıcı.** Ham telemetri/medya R2'de (NDJSON/Parquet), private bucket, imzalı kısa URL. Saklama süresi `settings`'te |
| AgentCore | **Sadece deney alanı** (`deploy/agentcore/`) | `build_agent(profile)` hub'a özgü varsayım içermez |
| Ambient | **Varsayılan kapalı**, kullanıcı açar; profiller `ev` / `seyahat` / `spor` | Tetik: Telegram `/ambient`, TauBar, ileride kolye. Açılış mesajı ve rutinler ambient'ten bağımsız çalışır |
| Self-replication | Yeni makineye kurulum (SSH, tier 2) · alt ajan/kopya · kalıcılık/self-heal | Tek ajanla başla; ~25 tool'u geçince agents-as-tools (`home`, `robot`, `dev`, `research`) |
| Kanallar | M1: Telegram metin + **TUI** (Textual) · M2: Telegram ses (Workers AI Whisper) + **tau MCP server** · M4: **Hey tau** (openWakeWord + MLX Whisper, tamamen lokal) | Wake word 3–4 heceli olmalı |
| Persona | **Jarvis tarzı**, Türkçe; `persona.md` + `user.md` + dinamik bağlam (saat, profil, node'lar, bütçe) | Kısalık kuralı: bildirim/seste en fazla 1–2 cümle; onay istekleri esprisiz |
| Secrets | Lokal `.env` (gitignored) · bulutta `wrangler secret` · TauBar için Keychain | Provisioning secret'ları SSH ile taşır |
| Domain | `getporti.<tld>` → nameserver'lar Cloudflare'e | Önce registrar'da DNSSEC kapat; MX/SPF/DKIM/DMARC'ı elle doğrula |
| Kolye | **XIAO ESP32S3 Sense** (WiFi kamera, pose Mac/RPi5'te) + **Nicla Vision** (cihaz üstü ML: IMU ile tekrar sayma, düşme) | Pose estimation Nicla'da yapılmaz |
| SO-101 | **strands-robots**, önce MuJoCo sim, `mode="real"` açık opt-in | Tetik: TauBar `screenIsUnlocked` → `tau/desk/presence` → rutin |

### Subdomain şeması

- `tau.getporti.<tld>` → dashboard
- `api.tau.getporti.<tld>` → relay, Telegram webhook, hafıza API'si (Cloudflare Access)
- `<proje>.getporti.<tld>` → Claude Code ile yapılıp `wrangler` ile deploy edilen projeler
- Domain taşınana kadar `*.workers.dev`

## Yol haritası (katman sırası)

Her katman bir öncekinin üstüne oturur ve tek başına işe yarar hale gelince bir sonrakine geçilir. Issue'lar [`roadmap/`](../roadmap/README.md) altında, katman başına bir klasör; durum için `python3 roadmap/board.py`.

| # | Katman | Kapsam |
|---|---|---|
| **0** | **Uzaktan erişim** | Tailscale + OpenSSH sertleştirme + tmux/mosh + Termius + şarjda uyumama → `infra/remote/` |
| **1** | **Ajan** | Strands çekirdeği (`build_agent`), persona, tier sistemi, TUI, launchd servisi. Model şimdilik doğrudan sağlayıcıdan; rol soyutlaması ilk günden var |
| **2** | **Modeller** | LiteLLM proxy, `brain`/`fast`/`local` rolleri, bütçeler, AWS Budgets |
| **3** | **Bulut** | Domain NS → Cloudflare, `tau-cloud` Worker, Telegram relay (DO) + **açılış durum mesajı**, D1/R2/Vectorize/AI Search, session recording |
| **4** | **Arayüz** | TauBar (uyku modları devralır), Telegram ses, tau MCP server, Claude Code hook, Hey tau |
| **5** | **Mesh** | `zenohd` + MCP node keşfi, hot-reload `tools/` + `_pending`, ESPHome/MQTT |
| **6** | **Robot** | SO-101 (sim → gerçek → masaya oturunca selam), kolye (XIAO → Nicla) |
| **7** | **Deney alanı** | AgentCore, otonom görev kuyruğu |
| — | **RPi5 gelince** | Self-replication ile hub geçişi (katmandan bağımsız) |
| — | **Sonra** | Drone |

## Önerilen repo yapısı

```
tau/
├── CLAUDE.md                 # ajan talimatları
├── CONTEXT.md                # terim sözlüğü
├── roadmap/                  # dosya tabanlı issue tracker + board.py
├── docs/                     # ARCHITECTURE.md, agents/, adr/
├── pyproject.toml            # uv workspace kökü
├── packages/                 # her biri bağımsız PyPI dağıtımı: tau-<ad> / import tau_<ad>
│   ├── tau-core/             # build_agent, persona, tier'lar, roller, session store, `tau` CLI, `tau hub`
│   ├── tau-tui/              # Textual
│   ├── tau-mesh/             # Zenoh + MCP keşfi
│   ├── tau-robot/            # strands-robots / SO-101 node
│   └── tau-vision/           # spor koçu (pose)
├── nodes/mac/                # macOS node (TauBar sidecar)
├── apps/taubar/              # Tauri v2 + React/TS
├── cloud/tau-cloud/          # Worker (TS): relay DO, D1, R2, Vectorize, AI Search, Whisper
├── persona/                  # persona.md, user.md
├── tools/                    # hot-reload tool'lar
│   └── _pending/             # tau'nun yazdığı, onay bekleyen tool'lar
├── infra/
│   ├── litellm/              # docker-compose + config.yaml
│   ├── zenoh/                # zenohd + MQTT plugin config
│   ├── services/             # launchd plist, systemd unit
│   └── remote/               # sshd_config, tmux, mosh
├── firmware/                 # ESPHome YAML, XIAO, Nicla (donanım gelince)
└── deploy/agentcore/
```

## Açık maddeler

Her biri `ready-for-human` bir issue olarak takipte.

1. **SO-101 hareket üretimi:** keyframe script / leader teleop + policy / LLM canlı yönlendirme → [038](../roadmap/L6-robot/038-decide-so101-motion-method.md)
2. **Domain:** tam ad (TLD) ve NS taşıma → [022](../roadmap/L3-cloud/022-move-dns-to-cloudflare.md)
3. **Kolye spor uyarısı:** uyarı kanalı, egzersizler, hatalar → [042](../roadmap/L6-robot/042-decide-workout-alert-channel.md)
4. **Hey tau:** wake word ifadesi → [030](../roadmap/L4-interface/030-pick-wake-phrase.md)
5. **Drone:** model seçimi, SHGM kuralları → [050](../roadmap/backlog/050-drone-model-and-rules.md)
6. **Alışveriş listesi (TR):** RPi5, XIAO, Nicla, ESP32 + LD2410 + sensörler → [049](../roadmap/backlog/049-hardware-shopping-list.md)
