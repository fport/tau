<!-- tr twin of reference/slash-commands.md, translated 2026-09-30 -->

# Slash komutları

`/` ile başlayan bir satır bir slash komutudur. Onu kanal işler, model asla görmez. Belirtim (adlar, takma adlar, argümanlar, yardım anahtarları) `tau_core.commands` içindedir; `tau chat` ve `tau tui` aynı on üç komutu aynı ifadelerle uygular, böylece ikisi asla birbirinden kopmaz (Telegram kanalı bunların bir sohbette anlamlı olan alt kümesini sunar).

- Kanonik adlar İngilizcedir ve ipuçlarında ve menülerde yalnızca onlar gösterilir.
- Türkçe takma adlar her zaman kabul edilir ve asla gösterilmez.
- Eşleştirme büyük/küçük harfe duyarsızdır (`str.casefold`): `/Resume 2` ve `/ARAÇLAR` çalışır.
- Argüman, ilk boşluktan sonraki her şeydir; baştaki ve sondaki boşluklar kırpılır.
- Bilinmeyen bir komut `Unknown command: /x. Commands: /help, /tools, …` yazdırır.

## Komutlar { #the-commands }

| Komut | Takma adlar | Argüman | Etkisi |
|---|---|---|---|
| `/help` | `/yardım`, `/yardim`, `/?` | – | komutları tek satırlık yardımlarıyla listeler |
| `/tools` | `/araçlar`, `/araclar` | – | kayıtlı araçlar, tier'ları (izin seviyeleri) ve açıklamalarıyla |
| `/sessions` | `/oturumlar` | – | mesaj içeren en son 10 eski oturum, numaralı, en yenisi önce; mevcut oturum asla listelenmez |
| `/resume` | `/devam` | `[n]` ya da `[id]` | en son eski oturumu sürdürür; son `/sessions` listesindeki n'inciyi (liste yoksa, şu an yazdıracağı listedekini); ya da o id'ye sahip oturumu |
| `/new` | `/yeni` | – | yeni bir oturum başlatır; mevcut oturum kayıtta kalır |
| `/session` | `/oturum` | – | mevcut oturumun id'si, başlığı, mesaj sayısı ve deposu |
| `/compact` | `/özet`, `/ozet` | `[focus]` | bu oturumu kendi modeliyle özetler ve özetle başlatılan yeni bir oturumda devam eder; eski oturum korunur ve ikisi birbirine bağlanır |
| `/clear` | `/temizle`, `/cls` | – | ekranı (terminal) ya da transkripti (TUI) temizler; oturum ve ajan devam eder |
| `/status` | `/durum` | – | profil, oturum, model, bağlam, araçlar, arayüz dili, sürümler, hub, bütçe |
| `/model` | `/rol` | `[role]` | `tau.toml` içindeki rolleri mevcut olan işaretli şekilde listeler ya da bu oturumu bir role geçirir |
| `/lang` | `/dil` | `en` ya da `tr` | bu çalıştırma için arayüz dilini değiştirir |
| `/settings` | `/ayarlar`, `/ayar` | `[key value]` | başlangıç yapılandırmasını (roller, kimlik bilgisi durumu, dil, profil, bağlam, dosyalar) gösterir ya da bir değeri değiştirir; TUI kendi ayarlar ekranını açar |
| `/quit` | `/çık`, `/cik`, `/exit` | – | çıkar |

`/exit`, `/quit`'in bir takma adıdır; ipuçları her zaman `/quit` gösterir.

## Her komutun çıktısı { #output-of-each-command }

Örnekler `en` arayüzünde; `tr` aynı satırların çevrilmiş hâlini gösterir.

### `/help`

```text
Commands:
  /help                  list the commands
  /tools                 registered tools with their tier and description
  /sessions              list the 10 most recent earlier sessions
  /resume [n|id]         resume the most recent earlier session, the n-th of the last listing, or an id
  /new                   start a fresh session
  /session               current session id, title, message count and store
  /compact [focus]       summarize this session into a new one and continue there (the old one is kept)
  /clear                 clear the screen; the session continues
  /status                profile, session, model, context, tools, language, versions and hub
  /model [role]          show the model roles, or switch this session to one
  /lang en|tr            switch the UI language for this run
  /settings [key value]  show the settings, or change one (language, profile, model, set NAME)
  /quit                  leave
```

### `/tools`

```text
Tools (2):
  current_time  tier 0 · read — Returns the current date and time in the Europe/Istanbul time zone.
  demo_physical_action  tier 2 · physical, needs approval — Demo tool that simulates a physical action (tier 2, asks for approval on every call).
```

Tier etiketleri: `read`, `digital write, logged`, `physical, needs approval`.

### `/sessions` ve `/resume` { #sessions-and-resume }

```text
Recent sessions:
 1. 20260929-173826-f949  29.09.2026 17:38  terminal  Merhaba tau (2 messages)
 2. 20260929-120000-abcd  29.09.2026 12:00  tui       Salon lambası açık mı? (14 messages)
```

`/resume` → `Resuming: <title> · <id> (<n> messages loaded).` Hatalar: `No earlier session to resume.`, `Session not found: <id>.`, `There is no session <n> in the list (1-<count>).`, `You are already in this session: <id>.` ve `Could not open the session: <error>` (genellikle nedeni, farklı bir `[agent] context` moduyla kaydedilmiş bir oturumdur; bkz. [Oturumlar ve sıkıştırma](sessions.md)).

### `/new` ve `/session` { #new-and-session }

`/new` → `New session: <id>.`

```text
Session: 20260929-173826-f949
Title: Merhaba tau
Messages: 2
Store: file (~/.local/share/tau/sessions)
```

### `/compact [focus]`

```text
Compacting 14 messages…
Compacted 14 messages into a summary. New session 20260929-181200-7c1e; the previous session 20260929-120000-abcd is kept.
<the summary, dimmed>
```

`focus`, özetleyicinin talimatlarına `Focus on: …` olarak eklenir. Başarısızlıklar (`Compaction failed: <error>`) mevcut oturumu çalışır hâlde bırakır; hiçbir şey yazılmaz. TUI'de özet bir worker içinde çalışır: arayüz meşgul görünür, salt okunur komutlar yine yanıt verir, Esc iptal eder (`Compaction cancelled; the session continues.`).

### `/clear`

Terminal: bir ANSI temizleme, yeniden hazır bannerı, ardından `Screen cleared; the session continues (<n> messages kept).` TUI: transkript, karşılama kartı ve bilgi kartları boşaltılır. Diskte hiçbir şey değişmez; `/resume` ya da `--resume` geçmişi yeniden gösterir.

### `/status`

```text
Profile: home
Session: 20260929-173826-f949 · Merhaba tau · 2 messages stored · role brain
Model: brain → anthropic · claude-sonnet-5
Context: sliding, window 60 · 2 messages in memory
Tools: 2 registered · 1 need approval (tier 2)
UI language: en
Versions: tau-core 0.3.1 · tau-tui 0.3.1
Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
Budget: brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); fast $0.03 of $1.00 today (resets 01.10.2026 00:00)
```

Model satırı sağlayıcıyı ve model id'sini belirtir, rolün `fallback`'i kullanılıyorsa bunu söyler; asla bir anahtar yazdırmaz. Bütçe satırı, bir rolün `tau.toml` içinde bütçesi olduğunda görünür: her rolün mevcut dönemde harcadığı tutar ve üst sınırı, yerel harcama defterinden (ledger) okunur; `tau spend` çıktısının ve modelin `## Now` bloğunun aynı metni ([Modeller ve bütçeler](../guides/models-and-budgets.md)). Hub satırı `tau doctor` yoklamasıdır (bir saniye, yalnızca bilgi amaçlı). TUI'de `/status` bir bilgi kartıdır.

### `/model [role]`

```text
Model role: brain (anthropic)
Roles in tau.toml:
  brain  anthropic · current
  fast   anthropic
  local  ollama
```

`/model fast`, ajanı o rolle **aynı** oturum üzerinde yeniden kurar: önce yeni ajan kurulur, böylece başarısız bir kurulum (bilinmeyen rol, eksik kimlik bilgileri, kullanılamayan sağlayıcı) hiçbir şeyi değiştirmez ve nedenini yazdırır. Rol oturumun metadata'sına yazılır, böylece `/resume` ve `--resume` onunla geri döner. `tau chat --role` o çalıştırma için bir rolü sabitler ve kayıtlı olana üstün gelir.

### `/lang en|tr`

Onay zaten yeni dildedir: `/lang tr`, `Arayüz dili: tr.` yanıtını; `/lang en` ise `UI language: en.` yanıtını verir. Argüman olmadan: `Usage: /lang en|tr (current: en).` Persona'nın yanıt dili bundan etkilenmez.

### `/settings [key value]`

Argüman olmadan, başlangıç yapılandırmasını dosyalarda durduğu hâliyle gösterir:

```text
Settings · ~/.tau
Model roles:
  brain  anthropic · claude-sonnet-5 · credentials ok
  fast   anthropic · claude-haiku-4-5 · credentials ok
  local  ollama · qwen3.5:9b · no credentials needed
UI language: en · profile: home
Context: sliding, window 60 · max_turns 12 · max_total_tokens none
Files:
  tau.toml            ~/.tau/tau.toml · present
  .env                ~/.tau/.env · present
  .env.example        ~/.tau/.env.example · present
  persona/persona.md  ~/.tau/persona/persona.md · present
  persona/user.md     ~/.tau/persona/user.md · present
Change: /settings language en|tr · /settings profile NAME · /settings model ROLE PROVIDER MODEL_ID · /settings set NAME · /settings clear NAME. The TUI (`tau tui`) has an editor: /settings or F10. `tau init --force` rewrites tau.toml from the template.
```

Rol başına kimlik bilgisi durumu `credentials ok`, `no credentials needed`, `missing X, Y`, `missing X, Y · fallback anthropic in use` ya da `provider not available: …` olur; hiçbir değer asla yazdırılmaz.

Terminalde ayarlayıcılar dosyaları `tau_core.settings` üzerinden yazar (`tau.toml` içindeki yorumlar korunur, `.env` `0600` modunda kalır) ve yeniden yükler:

| Biçim | Etkisi |
|---|---|
| `/settings language en\|tr` | `tau.toml` içinde `[ui] language`; arayüz hemen değişir (`Settings saved.` ve ardından, zaten yeni dilde, `Arayüz dili: tr.`) |
| `/settings profile NAME` | `.env` içinde `TAU_PROFILE`; ajan aynı oturum üzerinde yeniden kurulur (`Settings saved; model reloaded.`) |
| `/settings model ROLE PROVIDER MODEL_ID` | bir rolün sağlayıcısı ve model id'si (`max_tokens` ve `fallback` değerleri korunur); yeniden kurar. Planlanan bir sağlayıcı (sonraki bir issue'nun yapacağı; şu an hiç yok), rol onu zaten belirtmiyorsa reddedilir: `Not saved: tau.toml: [models.roles.brain] provider '…' is not supported yet (issue …); available: anthropic, bedrock, fake, gemini, ollama, openai.` |
| `/settings set NAME` | gizli bir istemle `Value for NAME (not echoed): ` sorar, `NAME` değerini `.env` dosyasına yazar (baştaki ve sondaki boşluklar kırpılır), çalışan sürece export eder ve yeniden kurar (`NAME set in .env.`); boş ya da yalnızca boşluktan oluşan bir değer hiçbir şeyi değiştirmez |
| `/settings clear NAME` | `NAME` değerini `.env` dosyasından ve süreçten kaldırır (`NAME removed from .env.` / `NAME is not in .env.`) |

Yapılandırmanın reddettiği bir değere `Not saved: <reason>` yanıtı verilir ve hiçbir şey yazılmaz (`tau.toml` yazmadan önce kontrol edilir); kaydedilen ama ajanı yeniden kurulamayan bir dosya `Settings saved, but the agent could not be rebuilt: <reason>` der ve mevcut ajan devam eder. Başka her şey kullanım satırını yazdırır.

TUI'de `/settings [section]` ayarlar ekranını açar (F10 da aynısını yapar); bir bölüm adı verilirse (`roles`, `credentials`, `interface`, `agent`, `doctor`, `files`) o bölümde açılır. Ekran [İlk çalıştırma](../getting-started/first-run.md#in-the-interface-tau-tui) sayfasında anlatılıyor. Bir tur meşgulken reddedilir.

## Terminal ve TUI karşılaştırması { #terminal-versus-tui }

| | `tau chat` | `tau tui` |
|---|---|---|
| Bir tur çalışırken | komut yazılamaz; REPL bir seferde tek bir iş yapar | `/new`, `/resume`, `/compact`, `/clear`, `/model <role>`, `/settings` turun bitmesini bekler (bir bildirim bunu söyler); `/status` ve `/model` her zaman yanıt verir |
| `/settings` | raporu yazdırır; ayarlayıcılar dosyaları yazar | ayarlar ekranını açar (F10 da) |
| Menü | yok; `/help` listeler | boş bir yazma alanına `/` yazmak bulanık eşleşmeli bir menü açar (`↑↓` seçer, Tab tamamlar, Enter çalıştırır, Esc kapatır) |
| Oturum seçici | `/sessions` + `/resume n` | aynısı, artı ctrl+r / F2 ve ≥ 140 sütunda kenar çubuğu |
| `/clear` | ekranı temizler | transkripti temizler |

## Kodda { #in-code }

```python
from tau_core import SLASH_COMMANDS, command_hint, resolve_command, t

resolve_command("/Devam 2")   # ("resume", "2"); None for "/x" or plain text
command_hint()                # "/help, /tools, /sessions, /resume, /new, ..."
t("session.not_found", "tr", session="x")   # "Oturum bulunamadı: x."
```

Bir insanın okuduğu her dizge, anahtarlı ve dil başına olarak `tau_core.i18n`'den gelir; eklentiler kendi anahtarlarını `register_messages` ile ekler.

## Telegram'da { #on-telegram }

[Telegram](../guides/telegram.md) kanalı aynı belirtimi aynı ifadelerle çözümler: `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/status`, `/model`, `/compact` ve `/lang` çalışır, Türkçe takma adlar dahil. `/start` (botu açtığında Telegram'ın gönderdiği) ve tek başına `/` yardımı gösterir; `/help@your_bot` de çalışır. Hub bu komutları izin verilen her sohbet için botun menüsü olarak ayarlar (sohbet kapsamlı `setMyCommands`), yardım metinleri arayüz dilindedir; `/lang` menüyü yeni dilde yeniden ayarlar. Bilinmeyen bir komut yalnızca Telegram'da çalışan komutları listeler. Geri kalanlar (`/clear`, `/quit` ve kimlik bilgilerini düzenleyen her komut) Telegram'da kullanılamadıklarını söyler. `/lang`, o sohbetin dilini hub yeniden başlayana kadar değiştirir.
