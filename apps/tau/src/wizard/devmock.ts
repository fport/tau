// `bun run dev` in a plain browser: a stand-in for the wizard's Rust side, so the wizard
// (http://localhost:1420/#wizard) can be looked at without the app. It replays the recorded
// `tau setup` streams of ./fixtures with small delays. `?scenario=nouv`, `notau` or `old`
// start without uv, without tau, or with a tau-core older than `tau setup`. main.tsx imports
// it only in development and outside Tauri, so no build contains it.

import { mockIPC } from "@tauri-apps/api/mocks";
import type { Discovery, JobEvent, SetupStatus } from "./api";
import freshEn from "./fixtures/status-fresh-en.json";
import freshTr from "./fixtures/status-fresh-tr.json";
import runNet from "./fixtures/run-net.jsonl?raw";
import runInitFake from "./fixtures/run-init-fake.jsonl?raw";
import runAbout from "./fixtures/run-about.jsonl?raw";
import runTelegram from "./fixtures/run-telegram.jsonl?raw";
import runDoctor from "./fixtures/run-doctor.jsonl?raw";
import installNet from "./fixtures/install-net.jsonl?raw";
import runRemote from "./fixtures/run-remote.jsonl?raw";

type Internals = { runCallback: (id: number, data: unknown) => void };
type ChannelLike = { id: number };

const scenario = new URLSearchParams(window.location.search).get("scenario") ?? "found";
let uv = scenario !== "nouv";
let tau = scenario === "found" || scenario === "old";
let old = scenario === "old";
let config = false;
let about = false;
const installed = new Set<string>(["tau-tui"]);
const done = new Set<string>(["tui", "app"]);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const lines = (text: string): JobEvent[] =>
  text
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as JobEvent);

const counters = new WeakMap<ChannelLike, number>();
function send(channel: ChannelLike, message: unknown) {
  const index = counters.get(channel) ?? 0;
  counters.set(channel, index + 1);
  const internals = (window as unknown as { __TAURI_INTERNALS__: Internals }).__TAURI_INTERNALS__;
  internals.runCallback(channel.id, { index, message });
}

async function play(channel: ChannelLike, events: JobEvent[], code = 0) {
  for (const event of events) {
    await sleep(event.event === "log" ? 40 : 260);
    send(channel, event);
  }
  send(channel, { event: "ended", code, signal: null, timed_out: false, cancelled: false });
  return { code, signal: null, timed_out: false, cancelled: false };
}

function discovery(): Discovery {
  return {
    tau: tau
      ? {
          python: "/Users/example/.local/share/uv/tools/tau-core/bin/python",
          home: "/Users/example/.tau",
          kind: "uv_tool",
          via: "/Users/example/.local/share/uv/tools/tau-core",
          version: old ? "tau-core 0.4.0" : "tau-core 0.5.0",
          uv_tool: true,
        }
      : null,
    uv: uv ? "/Users/example/.local/bin/uv" : null,
    rejected: [],
    saved_hub: tau,
    saved_chat: tau,
    default_home: "/Users/example/.tau",
    install_version: null,
    hub_ready: tau,
  };
}

function status(lang: string): SetupStatus {
  const base = (lang === "tr" ? freshTr : freshEn) as SetupStatus;
  return {
    ...base,
    config,
    about,
    features: base.features.map((f) => {
      const isInstalled = !f.package || installed.has(f.package);
      const isDone = done.has(f.id);
      return {
        ...f,
        installed: isInstalled,
        configured: isDone,
        state: isDone ? "done" : f.package && !isInstalled ? "missing" : f.package ? "installed" : "available",
      };
    }),
  };
}

const guardRun: JobEvent[] = [
  { event: "progress", feature: "guard", step: "doctor", status: "running", label: "Check the guard's prerequisites", command: ["guard", "doctor"] },
  { event: "log", feature: "guard", step: "doctor", line: "fail sface: the face model is not downloaded yet" },
  { event: "progress", feature: "guard", step: "doctor", status: "done", reason: "advisory", detail: "reported problems (exit code 1); the next steps fix the expected ones", code: 1, label: "Check the guard's prerequisites" },
  { event: "needs_ui", feature: "guard", step: "setup", label: "Enroll your face and switch the guard on", command: ["guard", "setup"], argv: ["python", "-m", "tau_core", "guard", "setup"] },
  { event: "done", feature: "guard", ok: true, configured: false, results: [{ step: "doctor", status: "done", reason: "advisory", code: 1 }, { step: "setup", status: "needs_ui" }], pending: ["restart"] },
];

// The remote run of docs/reference/setup.md ("Check steps"): SSH not set up yet.
const sshAction = {
  kind: "sudo",
  text: "Run this in your own terminal, as yourself and not with sudo: it asks for your password (sudo) only for the steps that need root. tau never runs it.",
  command: "bash ~/.local/share/tau/remote/setup-all.sh",
  sudo: true,
  url: null,
  changes: ["installs tmux and mosh with Homebrew", "with sudo: writes /etc/ssh/sshd_config.d/010-tau.conf: keys only, only you, only from the tailnet and localhost"],
  script: "~/.local/share/tau/remote/setup-all.sh",
};
const [tailscaleChecked, , tailscaleDone] = lines(runRemote);
const remoteRun: JobEvent[] = [
  lines(runRemote)[0],
  tailscaleChecked,
  tailscaleDone,
  { event: "progress", feature: "remote", step: "ssh", status: "checking", label: "SSH and mosh", command: ["remote", "ssh"] },
  { event: "check", feature: "remote", step: "ssh", ok: false, summary: "2 problem(s) with SSH, mosh or tmux", checks: [{ id: "sshd", label: "SSH server", status: "fail", detail: "off (Remote Login)" }, { id: "tmux", label: "tmux", status: "ok", detail: "/opt/homebrew/bin/tmux" }, { id: "mosh", label: "mosh", status: "fail", detail: "not found" }], action: sshAction, values: {} },
  { event: "needs_ui", feature: "remote", step: "ssh", label: "SSH and mosh", summary: "2 problem(s) with SSH, mosh or tmux", action: sshAction },
  { event: "done", feature: "remote", ok: true, configured: false, results: [{ step: "tailscale", status: "done", code: 0 }, { step: "ssh", status: "needs_ui" }], pending: ["ssh", "phone"] },
];
// "Done, check again": the recorded run of a Mac where every check passes.
const phoneRun: JobEvent[] = lines(runRemote).slice(3);

async function run(args: Record<string, unknown>) {
  const channel = args.events as ChannelLike;
  const spec = args.spec as { kind: string; target?: string; features?: string[] };
  const input = (args.input ?? {}) as { steps?: string[]; token?: string | null; account_id?: string };
  if (spec.kind === "install") {
    for (const id of spec.features ?? []) {
      const pkg = status("en").features.find((f) => f.id === id)?.package;
      if (pkg) installed.add(pkg);
    }
    return play(channel, lines(installNet));
  }
  if (spec.kind === "telegram_pair") {
    await play(channel, [
      { event: "bot", bot: "example_tau_bot", token: input.token ? "written" : "kept" },
      { event: "code", code: "K7QM-X2PA", link: "https://t.me/example_tau_bot?start=K7QM-X2PA", bot: "example_tau_bot" },
      { event: "waiting", via: "cli" },
    ]).catch(() => undefined);
    return { code: 0, signal: null, timed_out: false, cancelled: false };
  }
  if (spec.kind === "spine_deploy") {
    if (!input.token && !input.account_id) {
      return play(channel, [{ type: "need_token", link: "https://dash.cloudflare.com/profile/api-tokens", permissions: ["Account > Workers Scripts > Edit", "Account > Workers KV Storage > Edit", "Account > Account Settings > Read"], message: "No token yet." }], 1);
    }
    return play(channel, [
      { type: "progress", key: "verify", text: "The token is active." },
      { type: "progress", key: "upload", text: "Uploaded worker.js." },
      { type: "done", url: "https://tau-spine.example.workers.dev", account_id: "0123456789abcdef", token_created: true, healthy: true },
    ]);
  }
  switch (spec.target) {
    case "init":
      config = true;
      return play(channel, lines(runInitFake));
    case "about":
      about = true;
      return play(channel, lines(runAbout));
    case "doctor":
      return play(channel, lines(runDoctor));
    case "net":
      done.add("net");
      return play(channel, lines(runNet));
    case "telegram":
      return play(channel, input.steps?.length === 0 ? [{ event: "done", feature: "telegram", ok: true, configured: true, results: [], pending: [] }] : lines(runTelegram));
    case "guard":
      if (input.steps?.[0] === "restart") {
        done.add("guard");
        return play(channel, [
          { event: "progress", feature: "guard", step: "restart", status: "info", label: "Restart the hub", text: "The guard starts with the next hub, locked." },
          { event: "done", feature: "guard", ok: true, configured: true, results: [{ step: "restart", status: "info" }], pending: [] },
        ]);
      }
      return play(channel, guardRun);
    case "remote":
      return play(channel, input.steps?.[0] === "ssh" ? phoneRun : remoteRun);
    default:
      return play(channel, [{ event: "done", feature: spec.target, ok: true, configured: true, results: [], pending: [] }]);
  }
}

mockIPC(async (cmd, payload) => {
  const args = (payload ?? {}) as Record<string, unknown>;
  switch (cmd) {
    case "wizard_discover":
      await sleep(400);
      return discovery();
    case "wizard_status":
      await sleep(250);
      if (!tau) throw { code: "no_tau", message: "tau is not installed yet." };
      if (old) throw { code: "too_old", message: "This tau-core has no `tau setup` yet." };
      return status(String(args.lang));
    case "wizard_install": {
      const channel = args.events as ChannelLike;
      if (args.what === "uv") {
        uv = true;
        return play(channel, [
          { event: "progress", phase: "download", url: "https://astral.sh/uv/install.sh" },
          { event: "progress", phase: "install_uv" },
          { event: "text", line: "downloading uv 0.10.11 aarch64-apple-darwin" },
          { event: "text", line: "installing to /Users/example/.local/bin" },
        ]);
      }
      tau = true;
      old = false;
      return play(channel, [
        { event: "progress", phase: "install", argv: ["tool", "install", "tau-core", "--with", "tau-tui"] },
        { event: "stderr", line: "Resolved 76 packages in 1.2s" },
        { event: "stderr", line: "Installed 1 executable: tau" },
      ]);
    }
    case "wizard_run":
      return run(args);
    case "wizard_permission":
      await sleep(args.request ? 900 : 100);
      return args.request ? "granted" : "not_determined";
    case "wizard_pty_start": {
      const output = args.output as ChannelLike;
      const exit = args.exit as ChannelLike;
      const text = new TextEncoder().encode(
        "\x1b[1mtau guard setup\x1b[0m\r\nDownloading SFace… ok\r\nTouch ID… ok\r\nLook at the camera, then turn left, right, up, down.\r\nENROLLED. The guard is on.\r\n",
      );
      setTimeout(() => send(output, text.buffer), 300);
      setTimeout(() => send(exit, { success: true, code: 0, signal: null }), 1800);
      return null;
    }
    case "set_run_hub":
      return { message: null };
    default:
      return null;
  }
});
