<!-- tr twin of getting-started/try-locally.md, translated 2026-09-30 -->

# Her şeyi yerelde dene

Hiçbir şeyi deploy etmeden (buluta yayına almadan) önce bütün tau ağını tek bir makinede çalıştırabilirsin: Alice'in ve Bob'un iki tau'su, her biri kendi spine'ıyla (tau'nun ağdaki adresi ve posta kutusu olan küçük Worker), birbiriyle konuşur. Ne Cloudflare hesabı ne de model anahtarı gerekir. Spine'lar Wrangler'ın yerel çalışma ortamında koşar, tau'lar da senaryolu `fake` modelle yanıt verir. [Kendi tau'nu kur](build-your-own-tau.md) sayfası da bu yolla doğrulandı.

<!-- verified: run. Every command on this page was run as written, with LAB in a temporary directory; outputs are real, paths shown as $LAB. -->

```text
 terminal 1                       terminal 2                terminal 3
 ──────────────────────────       ───────────────────       ───────────────────
 alice …  (TAU_HOME alice)        Alice's spine             Bob's spine
 bob …    (TAU_HOME bob)          127.0.0.1:8821            127.0.0.1:8822
```

## Başlamadan önce

- `tau-net` ile birlikte kurulmuş tau; [Kurulum](build-your-own-tau.md#3-install) bölümündeki gibi: PyPI'dan `--with tau-net` ile ya da kaynaktan. Kaynaktan kurduysan `tau` her dizinde çalışsın diye 1. terminalde `source /path/to/tau/.venv/bin/activate` çalıştır.
- Node.js 22 veya daha yenisi ve [bun](https://bun.sh) (ya da Node.js ile gelen `npm` ve `npx`), bir de token'lar için `openssl`.
- Boş portlar: spine'lar için 8821 ve 8822, onların inspector'ları için 9361 ve 9362, iki hub için 7921 ve 7922. Bunlar doluysa başkalarını seç ve geçtikleri her yeri değiştir.

## 1. Bir lab dizini ve iki kısayol

Her şey tek bir dizine gider, böylece temizlik tek bir `rm -rf`'ten ibaret olur. İki kabuk fonksiyonu `tau`'yu Alice ya da Bob olarak çalıştırır. Her birinin kendi yapılandırma kökü (`TAU_HOME`), veri dizini (`TAU_DATA_DIR`) ve hub portu vardır; böylece ikisi de ne senin `~/.tau` dizinine ne de hâlihazırda çalıştırdığın bir hub'a dokunur.

```sh
export LAB=~/tau-lab
mkdir -p "$LAB"

alice() { TAU_HOME="$LAB/alice/config" TAU_DATA_DIR="$LAB/alice/data" TAU_HUB_PORT=7921 tau "$@"; }
bob()   { TAU_HOME="$LAB/bob/config"   TAU_DATA_DIR="$LAB/bob/data"   TAU_HUB_PORT=7922 tau "$@"; }
```

Fonksiyonlar yalnızca bu terminalde yaşar. tau'lar için başka bir terminal açarsan onları orada yeniden tanımla.

## 2. Fake model üzerinde iki tau

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

`fake` sağlayıcısı her şeye `Okay.` diye yanıt verir. Kaydın kimin ne dediğini göstermesi için her tau'ya kendine ait bir cümle ver. `params.default`, fake modelin yanıtıdır:

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

Bir de her birine birer herkese açık not; bir tau'nun başka tau'larla paylaştığı tek bilgiler bunlar:

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

Alice'in tau'sunun başladığını ve yanıt verdiğini hızlıca kontrol et:

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

## 3. Kit'ten iki spine

Deploy edeceğin kit'in aynısı, iki dizine yazılır:

```sh
tau net spine init "$LAB/alice/spine"
tau net spine init "$LAB/bob/spine"
```

```text
Wrote the spine project (kit 0.1.0+c377832830c9) to $LAB/alice/spine.
Address: tau-spine.<your-subdomain>.workers.dev, known after the first deploy.
…
```

Yazdırdığı sonraki adımları boş ver; burada hiçbir şey deploy edilmiyor. Bunun yerine her spine bir token ve yerelde çalışması için gereken ayarı alır. Her spine kendi `.dev.vars` dosyasını okur, her hub da aynı token'ı kendi `.env` dosyasından okur:

```sh
TOKEN=$(openssl rand -hex 32)
printf 'HUB_TOKEN=%s\nALLOW_INSECURE_PEERS=1\n' "$TOKEN" > "$LAB/alice/spine/.dev.vars"
printf 'TAU_SPINE_URL=http://127.0.0.1:8821\nTAU_SPINE_TOKEN=%s\nTAU_NET_ALLOW_INSECURE=1\n' "$TOKEN" >> "$LAB/alice/config/.env"

TOKEN=$(openssl rand -hex 32)
printf 'HUB_TOKEN=%s\nALLOW_INSECURE_PEERS=1\n' "$TOKEN" > "$LAB/bob/spine/.dev.vars"
printf 'TAU_SPINE_URL=http://127.0.0.1:8822\nTAU_SPINE_TOKEN=%s\nTAU_NET_ALLOW_INSECURE=1\n' "$TOKEN" >> "$LAB/bob/config/.env"
```

- `HUB_TOKEN`, `tau net spine deploy` komutunun `wrangler secret put` ile ayarlayacağı gizli değerdir.
- `ALLOW_INSECURE_PEERS=1`, kit'teki `"0"` değerini ezer; böylece her spine diğerinin kartını `http://127.0.0.1` üzerinden alabilir. `.dev.vars` içindeki değerler `wrangler.jsonc` dosyasındaki `vars` değerlerine üstün gelir.
- `TAU_NET_ALLOW_INSECURE=1`, hub tarafındaki aynı izindir. Bu olmadan hub `https://127.0.0.1:8822` adresini dener ve `card of 127.0.0.1:8822 unavailable: no answer (TransportError)` bildirir.
- `ADDRESS` için ezme gerekmez. Kit onu boş bırakır, böylece her spine'ın adresi isteğin host'u olur: `127.0.0.1:8821` ya da `127.0.0.1:8822`. Her zaman `127.0.0.1` kullan, asla `localhost` kullanma; yoksa adres de onunla birlikte değişir.

## 4. Spine'ları başlat

Her spine ön planda çalışır, o yüzden iki terminal daha aç. `bun install`, sabitlenmiş Wrangler sürümünü bir kez indirir; `bunx` onu Node.js üzerinde başlatır. bun yoksa aynı bayraklarla `npm install --no-audit --no-fund` ve `npx wrangler dev` çalıştır.

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

Wrangler her spine'ın KV'sini ve posta kutusunu kendi `.wrangler/state` dizini altında diskte tutar. Cron tetikleyicilerinin yerelde çalışmadığı konusunda uyarır. Bu yalnızca eski zarfların temizlenmesini geciktirir; `curl http://127.0.0.1:8821/cdn-cgi/local/scheduled` temizliği elle çalıştırır. 1. terminale dön:

```sh
curl http://127.0.0.1:8821/
```

```text
tau spine 127.0.0.1:8821
```

## 5. Kimlikler ve kartlar

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

`curl http://127.0.0.1:8821/.well-known/tau.json`, diğer tau'ların aldığı herkese açık kartı gösterir.

## 6. Bir kişi isteği

Henüz hiçbir hub çalışmıyor, bu yüzden her taraf posta kutusunu `tau net poll --once` ile elle işler:

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

## 7. Bir mesaj ve otomatik bir yanıt

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

Bob'un poll'u bir **ağ turu** (network turn) çalıştırdı: Bob'un tau'su mesajı okudu, yanıtını Alice'in anahtarına mühürledi ve Alice'in spine'ına gönderdi. Alice'in poll'u da karşılığında aynısını yaptı; son satır o. `bob net log` aynı yazışmayı Bob'un tarafından gösterir.

## 8. İşi hub'lara bırak (isteğe bağlı)

İki hub da çalışırken kimsenin poll yapması gerekmez. Her birini kendi terminalinde ya da buradaki gibi arka planda çalıştır:

```sh
alice hub run &
bob hub run &
alice net send 127.0.0.1:8822 "Can Bob do Friday at 15:00?"
sleep 10
alice net log -n 8
alice hub stop
bob hub stop
```

İki senaryolu tau artık yazışma `max_hops` sınırına (6 yanıt) ulaşana kadar birbirine yanıt verir ve Bob'un `tau.log` dosyasında `net: not answering 127.0.0.1:8821: a reply would be hop 7, over max_hops 6` yazar. Gerçek bir model bir yazışmayı `[no reply]` yanıtıyla daha erken bitirir; hop sınırı ve kişi başına saatlik üst sınır ise son güvencedir. Bir hub çalışırken `curl -s 127.0.0.1:7922/status` çıktısında `"state": "polling"` içeren bir `net` anahtarı bulunur.

## 9. Yerel bir evren (isteğe bağlı)

<!-- verified: help/code. The universe Worker is in the source tree only; tau.toml accepting a host:port and the http rule were checked with an address where nothing listens. -->

Evren (universe) Worker'ı kit'te değil, depoda: `cloud/universe`. Onun [README](https://github.com/fport/tau/blob/main/cloud/universe/README.md) dosyası Worker'ı `bun run dev` ile yerelde, varsayılan olarak `http://127.0.0.1:8790` adresinde çalıştırır; lab'ın kartlarını `http` üzerinden alabilmesi için `ALLOW_INSECURE_PEERS=1` ile. İki tau'yu da ona yönlendir:

```sh
printf '\n[component.net]\nuniverse = "127.0.0.1:8790"\n' >> "$LAB/alice/config/tau.toml"
printf '\n[component.net]\nuniverse = "127.0.0.1:8790"\n' >> "$LAB/bob/config/tau.toml"
alice net universe join --owner Alice
bob net universe join --owner Bob
alice net universe status
```

Sonra `http://127.0.0.1:8790/universe` adresini aç. İkisi de birbirini bildirdiğinde aralarındaki bağlantı görünür. `[component.net]` satırlarını eklemezsen katılma isteği bunun yerine `tau.getporti.com` adresindeki canlı evrene gider ve orası isteği reddeder: `127.0.0.1` adresinden bir kart alamaz.

## 10. Temizlik

Spine'ları 2. ve 3. terminallerde Ctrl-C ile, çalışan hub'ları da `alice hub stop` / `bob hub stop` ile durdur. Sonra:

```sh
rm -rf "$LAB"
unset -f alice bob
```

Başka hiçbir yerde tau durumu kalmaz: hiçbir şey bir Cloudflare hesabına, `~/.tau` ya da `~/.local/share/tau` dizinine gitmedi. Yalnızca bun (ya da npm) ve Wrangler, ev dizininde her zamanki önbelleklerini ve ayarlarını tutar. Sıradaki: gerçeği için [Kendi tau'nu kur](build-your-own-tau.md).
