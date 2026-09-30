/**
 * The owner's app and the visitor page: every UI string, in English (the source) and Turkish.
 *
 * The app picks the table from the tau's language setting (before onboarding, from the
 * page's `<html lang>`). Functions put numbers and names in place. This module is pure (no
 * DOM), so a Worker test can check that both tables have the same keys.
 */

export type UiLanguage = "en" | "tr";

export interface Messages {
  // navigation
  chat: string;
  subTaus: string;
  approvals: string;
  settings: string;
  signOut: string;
  newChat: string;
  sessions: string;
  noSessions: string;
  menu: string;
  // onboarding
  onboardTitle: string;
  onboardIntro: string;
  provider: string;
  providerFake: string;
  key: string;
  keyHelp: string;
  language: string;
  universe: string;
  universeHelp: string;
  universeYes: string;
  universeNo: string;
  universeLater: string;
  privacyTitle: string;
  privacy1: string;
  privacy2: string;
  privacy3: string;
  start: string;
  checkingKey: string;
  // chat
  placeholderMain: string;
  placeholderSub: (name: string) => string;
  send: string;
  noMessages: string;
  toolCall: (name: string) => string;
  toolResult: string;
  approvalNeeded: string;
  approve: string;
  deny: string;
  status_pending: string;
  status_approved: string;
  status_denied: string;
  status_expired: string;
  expiresAt: (time: string) => string;
  deleteSession: string;
  confirmDeleteSession: string;
  notice_max_steps: string;
  notice_budget: string;
  notice_max_tokens: string;
  notice_stopped: string;
  // errors
  err_budget: (spent: string, budget: string, resets: string) => string;
  err_busy: string;
  err_awaiting_approval: string;
  err_not_onboarded: string;
  err_provider_auth: string;
  err_provider_rate: string;
  err_provider_unavailable: string;
  err_provider_bad_request: (detail: string) => string;
  err_provider_other: (detail: string) => string;
  err_vault: string;
  err_key_invalid: string;
  err_key_unchecked: string;
  err_bad_key: string;
  err_draft_failed: (detail: string) => string;
  err_decided: (status: string) => string;
  err_stale: string;
  err_network: string;
  err_generic: (code: string) => string;
  // sub-taus
  newSub: string;
  noSubs: string;
  name: string;
  nameHelp: string;
  about: string;
  persona: string;
  role: string;
  roleBrain: string;
  roleFast: string;
  public: string;
  publicHelp: string;
  publicNote: string;
  publicNoteHelp: string;
  web: string;
  webHelp: string;
  webNeedsPublic: string;
  webDaily: string;
  starters: string;
  startersHelp: string;
  save: string;
  saved: string;
  create: string;
  cancel: string;
  delete: string;
  confirmDeleteSub: (name: string) => string;
  chatWith: (name: string) => string;
  openPage: string;
  howToStart: string;
  describe: string;
  describeHelp: string;
  draftIt: string;
  drafting: string;
  fromTemplate: string;
  template_blank: string;
  template_coach: string;
  template_writer: string;
  template_tutor: string;
  useTemplate: string;
  visitsToday: (count: number, cap: number) => string;
  visitorChats: string;
  noVisitorChats: string;
  visitor: string;
  flags: string;
  // approvals
  noApprovals: string;
  openSession: string;
  // settings
  currentKey: (provider: string, last4: string) => string;
  noKey: string;
  replaceKey: string;
  models: string;
  modelsHelp: string;
  unpriced: (ids: string) => string;
  budget: string;
  budgetHelp: string;
  spent: (spent: string, budget: string) => string;
  personaHelp: string;
  resetPersona: string;
  profile: string;
  profileHelp: string;
  universeSetting: string;
  universeSaved: string;
  exportTitle: string;
  exportHelp: string;
  exportButton: string;
  deleteAccount: string;
  deleteHelp: string;
  deleteConfirm: (handle: string) => string;
  deleteButton: string;
  // visitor page
  you: string;
  visitorPlaceholder: string;
  visitorError: (code: string) => string;
  visitorThreadGone: string;
  visitorCap: string;
  visitorBusy: string;
  loading: string;
}

const en: Messages = {
  chat: "Chat",
  subTaus: "Sub-taus",
  approvals: "Approvals",
  settings: "Settings",
  signOut: "Sign out",
  newChat: "New chat",
  sessions: "Sessions",
  noSessions: "No sessions yet.",
  menu: "Menu",
  onboardTitle: "Set up your tau",
  onboardIntro: "Your tau runs on your own provider key. Pick the provider, paste the key, choose a language.",
  provider: "Provider",
  providerFake: "Fake (development, no key)",
  key: "API key",
  keyHelp: "Checked with one small request, then encrypted. It is never shown again; only its last four characters.",
  language: "Language",
  universe: "The tau universe",
  universeHelp:
    "A public map of taus. A listed tau shows its handle, its public sub-taus and how many messages it exchanges, never what is said.",
  universeYes: "List me in the universe",
  universeNo: "Keep me unlisted",
  universeLater: "You can change this later in Settings.",
  privacyTitle: "Who can read what",
  privacy1: "Your tau lives on this host. Its operator can read your chats, your sub-taus and your visitors' chats.",
  privacy2: "Your provider key is encrypted at rest and never shown again.",
  privacy3: "For privacy, run tau locally or deploy your own host.",
  start: "Start",
  checkingKey: "Checking the key…",
  placeholderMain: "Message your tau…",
  placeholderSub: (name) => `Message /${name}…`,
  send: "Send",
  noMessages: "Say something to start.",
  toolCall: (name) => `tool · ${name}`,
  toolResult: "result",
  approvalNeeded: "Approval needed",
  approve: "Approve",
  deny: "Deny",
  status_pending: "waiting for you",
  status_approved: "approved",
  status_denied: "denied",
  status_expired: "expired",
  expiresAt: (time) => `expires at ${time}`,
  deleteSession: "Delete session",
  confirmDeleteSession: "Delete this session and its messages?",
  notice_max_steps: "The turn stopped after too many steps.",
  notice_budget: "The turn stopped: this month's budget is used up.",
  notice_max_tokens: "The answer was cut at the length limit.",
  notice_stopped: "The turn stopped.",
  err_budget: (spent, budget, resets) =>
    `This month's budget is used up: ${spent} of ${budget}. It starts over on ${resets}; you can raise it in Settings.`,
  err_busy: "A turn is still running in this session.",
  err_awaiting_approval: "Answer the approval in this session first.",
  err_not_onboarded: "Set up a provider and key first.",
  err_provider_auth: "The provider refused the key. Paste a new one in Settings.",
  err_provider_rate: "The provider is throttling this key. Try again in a moment.",
  err_provider_unavailable: "The provider cannot be reached right now. Try again later.",
  err_provider_bad_request: (detail) => `The provider refused the request: ${detail}`,
  err_provider_other: (detail) => `The provider failed: ${detail}`,
  err_vault: "The key cannot be opened on this host (VAULT_KEY). Ask the operator, or paste the key again.",
  err_key_invalid: "The provider does not accept this key.",
  err_key_unchecked: "The key could not be checked right now. Try again.",
  err_bad_key: "That does not look like an API key.",
  err_draft_failed: (detail) => `The draft did not work: ${detail}`,
  err_decided: (status) => `This approval is already ${status}.`,
  err_stale: "The turn of this approval is gone.",
  err_network: "No connection to the host.",
  err_generic: (code) => `Something went wrong (${code}).`,
  newSub: "New sub-tau",
  noSubs: "No sub-taus yet. A sub-tau is a small specialist of your tau with its own persona.",
  name: "Name",
  nameHelp: "2–31 characters: lowercase letters, digits and -, starting with a letter.",
  about: "About",
  persona: "Persona",
  role: "Model",
  roleBrain: "brain (stronger)",
  roleFast: "fast (cheaper)",
  public: "Public",
  publicHelp: "Other taus and visitors may talk to it. It never sees your profile.",
  publicNote: "Public note",
  publicNoteHelp: "What it may tell others about you. Empty: nothing.",
  web: "Web page",
  webHelp: "A chat page for anyone at /@handle/name. Each answer uses your key.",
  webNeedsPublic: "Needs Public.",
  webDaily: "Visitor answers per day",
  starters: "Starters",
  startersHelp: "Up to 4 suggested first messages, 80 characters each.",
  save: "Save",
  saved: "Saved.",
  create: "Create",
  cancel: "Cancel",
  delete: "Delete",
  confirmDeleteSub: (name) => `Delete /${name}, its sessions and its visitor chats?`,
  chatWith: (name) => `Chat with /${name}`,
  openPage: "Open its page",
  howToStart: "Start from",
  describe: "A description",
  describeHelp: "Say what it should do; your brain model drafts the persona. You read it before saving.",
  draftIt: "Draft it",
  drafting: "Drafting…",
  fromTemplate: "A template",
  template_blank: "Blank",
  template_coach: "Workout coach",
  template_writer: "Writer",
  template_tutor: "Tutor",
  useTemplate: "Use template",
  visitsToday: (count, cap) => `${count} of ${cap} visitor answers today`,
  visitorChats: "Visitor chats (24 h)",
  noVisitorChats: "No visitor chats in the last 24 hours.",
  visitor: "visitor",
  flags: "Visibility",
  noApprovals: "Nothing waits for you.",
  openSession: "Open the session",
  currentKey: (provider, last4) => `${provider} · key ending in ${last4}`,
  noKey: "no key",
  replaceKey: "New key (leave empty to keep the current one)",
  models: "Models",
  modelsHelp: "Model ids for each role, as your provider names them.",
  unpriced: (ids) => `No price is known for ${ids}: the budget cannot count it.`,
  budget: "Monthly budget (USD)",
  budgetHelp: "Counted from your provider's token usage. A turn that would start over it is refused.",
  spent: (spent, budget) => `${spent} of ${budget} used this month (UTC)`,
  personaHelp: "Your tau's character. Empty: the default persona.",
  resetPersona: "Use the default",
  profile: "Profile",
  profileHelp: "Facts about you your tau may use in your own chats (your user.md). Never shown to others.",
  universeSetting: "Universe listing",
  universeSaved: "Kept for when this host joins the tau network.",
  exportTitle: "Export",
  exportHelp: "Everything of your tau as one JSON file (without the key).",
  exportButton: "Download JSON",
  deleteAccount: "Delete account",
  deleteHelp: "Deletes your tau, its sub-taus, sessions, visitor chats and your account on this host. This cannot be undone.",
  deleteConfirm: (handle) => `Type ${handle} to confirm`,
  deleteButton: "Delete everything",
  you: "you",
  visitorPlaceholder: "Write a message…",
  visitorError: (code) => `No answer (${code}). Try again later.`,
  visitorThreadGone: "This conversation expired; a new one starts.",
  visitorCap: "It has answered enough for today. Come back tomorrow.",
  visitorBusy: "Too many messages. Wait a minute.",
  loading: "Loading…",
};

const tr: Messages = {
  chat: "Sohbet",
  subTaus: "Alt-tau'lar",
  approvals: "Onaylar",
  settings: "Ayarlar",
  signOut: "Çıkış yap",
  newChat: "Yeni sohbet",
  sessions: "Oturumlar",
  noSessions: "Henüz oturum yok.",
  menu: "Menü",
  onboardTitle: "tau'nu kur",
  onboardIntro: "tau'n kendi sağlayıcı anahtarınla çalışır. Sağlayıcıyı seç, anahtarı yapıştır, bir dil seç.",
  provider: "Sağlayıcı",
  providerFake: "Sahte (geliştirme, anahtarsız)",
  key: "API anahtarı",
  keyHelp: "Küçük bir istekle denenir, sonra şifrelenir. Bir daha gösterilmez; yalnızca son dört karakteri.",
  language: "Dil",
  universe: "tau evreni",
  universeHelp:
    "tau'ların herkese açık haritası. Listelenen bir tau adını, açık alt-tau'larını ve kaç mesajlaştığını gösterir, ne konuşulduğunu asla.",
  universeYes: "Beni evrende listele",
  universeNo: "Listelenmeyeyim",
  universeLater: "Bunu sonra Ayarlar'dan değiştirebilirsin.",
  privacyTitle: "Kim neyi okuyabilir",
  privacy1: "tau'n bu sunucuda yaşar. İşletmecisi sohbetlerini, alt-tau'larını ve ziyaretçilerinin sohbetlerini okuyabilir.",
  privacy2: "Sağlayıcı anahtarın şifreli saklanır ve bir daha gösterilmez.",
  privacy3: "Gizlilik için tau'yu yerelde çalıştır ya da kendi sunucunu kur.",
  start: "Başla",
  checkingKey: "Anahtar deneniyor…",
  placeholderMain: "tau'na yaz…",
  placeholderSub: (name) => `/${name} alt-tau'suna yaz…`,
  send: "Gönder",
  noMessages: "Başlamak için bir şey yaz.",
  toolCall: (name) => `araç · ${name}`,
  toolResult: "sonuç",
  approvalNeeded: "Onay gerekiyor",
  approve: "Onayla",
  deny: "Reddet",
  status_pending: "seni bekliyor",
  status_approved: "onaylandı",
  status_denied: "reddedildi",
  status_expired: "süresi doldu",
  expiresAt: (time) => `${time} saatinde düşer`,
  deleteSession: "Oturumu sil",
  confirmDeleteSession: "Bu oturum ve mesajları silinsin mi?",
  notice_max_steps: "Tur çok fazla adımdan sonra durdu.",
  notice_budget: "Tur durdu: bu ayın bütçesi bitti.",
  notice_max_tokens: "Yanıt uzunluk sınırında kesildi.",
  notice_stopped: "Tur durdu.",
  err_budget: (spent, budget, resets) =>
    `Bu ayın bütçesi bitti: ${budget} bütçenin ${spent} kadarı harcandı. ${resets} tarihinde yeniden başlar; Ayarlar'dan artırabilirsin.`,
  err_busy: "Bu oturumda hâlâ bir tur sürüyor.",
  err_awaiting_approval: "Önce bu oturumdaki onayı yanıtla.",
  err_not_onboarded: "Önce bir sağlayıcı ve anahtar kur.",
  err_provider_auth: "Sağlayıcı anahtarı kabul etmedi. Ayarlar'dan yenisini yapıştır.",
  err_provider_rate: "Sağlayıcı bu anahtarı yavaşlatıyor. Birazdan yeniden dene.",
  err_provider_unavailable: "Sağlayıcıya şu an ulaşılamıyor. Sonra yeniden dene.",
  err_provider_bad_request: (detail) => `Sağlayıcı isteği reddetti: ${detail}`,
  err_provider_other: (detail) => `Sağlayıcı hata verdi: ${detail}`,
  err_vault: "Anahtar bu sunucuda açılamıyor (VAULT_KEY). İşletmeciye sor ya da anahtarı yeniden yapıştır.",
  err_key_invalid: "Sağlayıcı bu anahtarı kabul etmiyor.",
  err_key_unchecked: "Anahtar şu an denenemedi. Yeniden dene.",
  err_bad_key: "Bu bir API anahtarına benzemiyor.",
  err_draft_failed: (detail) => `Taslak olmadı: ${detail}`,
  err_decided: (status) => `Bu onay zaten yanıtlandı (${status}).`,
  err_stale: "Bu onayın turu artık yok.",
  err_network: "Sunucuyla bağlantı yok.",
  err_generic: (code) => `Bir şeyler ters gitti (${code}).`,
  newSub: "Yeni alt-tau",
  noSubs: "Henüz alt-tau yok. Alt-tau, tau'nun kendi kişiliği olan küçük bir uzmanıdır.",
  name: "Ad",
  nameHelp: "2–31 karakter: küçük harf, rakam ve -, harfle başlar.",
  about: "Hakkında",
  persona: "Kişilik",
  role: "Model",
  roleBrain: "brain (daha güçlü)",
  roleFast: "fast (daha ucuz)",
  public: "Herkese açık",
  publicHelp: "Başka tau'lar ve ziyaretçiler onunla konuşabilir. Profilini asla görmez.",
  publicNote: "Açık not",
  publicNoteHelp: "Senin hakkında başkalarına ne söyleyebileceği. Boşsa: hiçbir şey.",
  web: "Web sayfası",
  webHelp: "/@ad/isim adresinde herkes için bir sohbet sayfası. Her yanıt senin anahtarını kullanır.",
  webNeedsPublic: "Herkese açık olmalı.",
  webDaily: "Günlük ziyaretçi yanıtı",
  starters: "Başlangıçlar",
  startersHelp: "En çok 4 önerilen ilk mesaj, her biri 80 karakter.",
  save: "Kaydet",
  saved: "Kaydedildi.",
  create: "Oluştur",
  cancel: "Vazgeç",
  delete: "Sil",
  confirmDeleteSub: (name) => `/${name}, oturumları ve ziyaretçi sohbetleri silinsin mi?`,
  chatWith: (name) => `/${name} ile sohbet`,
  openPage: "Sayfasını aç",
  howToStart: "Nereden başlasın",
  describe: "Bir tarif",
  describeHelp: "Ne yapacağını anlat; brain modelin kişiliği taslak olarak yazar. Kaydetmeden önce okursun.",
  draftIt: "Taslak yaz",
  drafting: "Taslak yazılıyor…",
  fromTemplate: "Bir şablon",
  template_blank: "Boş",
  template_coach: "Antrenman koçu",
  template_writer: "Yazar",
  template_tutor: "Öğretmen",
  useTemplate: "Şablonu kullan",
  visitsToday: (count, cap) => `Bugün ${cap} ziyaretçi yanıtının ${count} tanesi kullanıldı`,
  visitorChats: "Ziyaretçi sohbetleri (24 sa)",
  noVisitorChats: "Son 24 saatte ziyaretçi sohbeti yok.",
  visitor: "ziyaretçi",
  flags: "Görünürlük",
  noApprovals: "Seni bekleyen bir şey yok.",
  openSession: "Oturumu aç",
  currentKey: (provider, last4) => `${provider} · ${last4} ile biten anahtar`,
  noKey: "anahtar yok",
  replaceKey: "Yeni anahtar (şimdikini korumak için boş bırak)",
  models: "Modeller",
  modelsHelp: "Her rol için, sağlayıcının verdiği adla model kimliği.",
  unpriced: (ids) => `${ids} için bilinen bir fiyat yok: bütçe bunu sayamaz.`,
  budget: "Aylık bütçe (USD)",
  budgetHelp: "Sağlayıcının bildirdiği token kullanımından sayılır. Bütçeyi aşacak bir tur başlamaz.",
  spent: (spent, budget) => `Bu ay ${budget} bütçenin ${spent} kadarı kullanıldı (UTC)`,
  personaHelp: "tau'nun karakteri. Boşsa: varsayılan kişilik.",
  resetPersona: "Varsayılanı kullan",
  profile: "Profil",
  profileHelp: "tau'nun kendi sohbetlerinde kullanabileceği bilgiler (user.md). Başkalarına asla gösterilmez.",
  universeSetting: "Evrende listelenme",
  universeSaved: "Bu sunucu tau ağına katıldığında kullanılmak üzere saklanır.",
  exportTitle: "Dışa aktar",
  exportHelp: "tau'nun her şeyi tek bir JSON dosyasında (anahtar hariç).",
  exportButton: "JSON indir",
  deleteAccount: "Hesabı sil",
  deleteHelp: "tau'nu, alt-tau'larını, oturumlarını, ziyaretçi sohbetlerini ve bu sunucudaki hesabını siler. Geri alınamaz.",
  deleteConfirm: (handle) => `Onaylamak için ${handle} yaz`,
  deleteButton: "Her şeyi sil",
  you: "sen",
  visitorPlaceholder: "Bir mesaj yaz…",
  visitorError: (code) => `Yanıt yok (${code}). Sonra yeniden dene.`,
  visitorThreadGone: "Bu sohbetin süresi doldu; yenisi başlıyor.",
  visitorCap: "Bugünlük yeterince yanıt verdi. Yarın yeniden gel.",
  visitorBusy: "Çok fazla mesaj. Bir dakika bekle.",
  loading: "Yükleniyor…",
};

export const MESSAGES: Readonly<Record<UiLanguage, Messages>> = { en, tr };
