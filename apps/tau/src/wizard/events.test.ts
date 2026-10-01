import { describe, expect, it } from "vitest";
import type { JobEvent } from "./api";
import {
  actionCommand,
  emptyPair,
  emptyRun,
  emptySpine,
  needsUiKind,
  pairNeedsToken,
  reducePair,
  reduceRun,
  reduceSpine,
  type RunState,
} from "./events";
// Recorded from `tau setup … --json` (see machine.test.ts); the guard, Telegram pairing, spine
// and remote-access streams below are the examples of docs/reference/setup.md, cli.md,
// tau-universe.md §4 and the shapes issue 173 added.
import installNet from "./fixtures/install-net.jsonl?raw";
import runNet from "./fixtures/run-net.jsonl?raw";
import runInitFake from "./fixtures/run-init-fake.jsonl?raw";
import runInitInvalid from "./fixtures/run-init-invalid.jsonl?raw";
import runTelegram from "./fixtures/run-telegram.jsonl?raw";
import runGuardMissing from "./fixtures/run-guard-missing.jsonl?raw";
import runDoctor from "./fixtures/run-doctor.jsonl?raw";
import runRemote from "./fixtures/run-remote.jsonl?raw";
import runRemotePhone from "./fixtures/run-remote-phone.jsonl?raw";
import runRemoteAction from "./fixtures/run-remote-action.jsonl?raw";

function lines(text: string): JobEvent[] {
  return text
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as JobEvent);
}

function fold(events: JobEvent[]): RunState {
  return events.reduce(reduceRun, emptyRun);
}

describe("tau setup run --json", () => {
  it("follows the network's steps to the spine deploy, which needs the owner", () => {
    const run = fold(lines(runNet));
    expect(run.steps.map((s) => [s.id, s.status])).toEqual([
      ["init", "done"],
      ["spine", "info"],
      ["spine-init", "done"],
      ["spine-deploy", "needs_ui"],
    ]);
    expect(run.steps[1].text).toMatch(/spine/);
    expect(run.logs.filter((l) => l.step === "init").length).toBeGreaterThan(3);
    expect(run.needsUi).toMatchObject({ feature: "net", step: "spine-deploy" });
    expect(needsUiKind(run.needsUi!)).toBe("spine");
    expect(run.needsUi!.command[3]).toBe("/example/home/tau-spine");
    expect(run.done).toMatchObject({ ok: true, configured: true, pending: [] });
    expect(run.error).toBeNull();
  });

  it("checks a key, writes it and says done", () => {
    const run = fold(lines(runInitFake));
    expect(run.steps).toMatchObject([{ id: "init", status: "done", code: 0 }]);
    expect(run.done?.ok).toBe(true);
    const invalid = fold(lines(runInitInvalid));
    expect(invalid.error?.code).toBe("key_invalid");
    expect(invalid.error?.message).toMatch(/spaces, quotes/);
    expect(invalid.done).toBeNull();
  });

  it("hands Telegram pairing to the app", () => {
    const run = fold(lines(runTelegram));
    expect(needsUiKind(run.needsUi!)).toBe("telegram");
    expect(run.done).toMatchObject({ configured: false, pending: [] });
  });

  it("hands the guard's enrolment to the app's terminal, with the restart note after it", () => {
    const run = fold([
      { event: "progress", feature: "guard", step: "doctor", status: "running", label: "Check the guard's prerequisites", command: ["guard", "doctor"] },
      { event: "log", feature: "guard", step: "doctor", line: "fail sface: …" },
      { event: "progress", feature: "guard", step: "doctor", status: "done", reason: "advisory", detail: "reported problems (exit code 1)", code: 1, label: "Check the guard's prerequisites" },
      { event: "needs_ui", feature: "guard", step: "setup", label: "Enroll your face and switch the guard on", command: ["guard", "setup"], argv: ["/example/home/.local/share/uv/tools/tau-core/bin/python", "-m", "tau_core", "guard", "setup"] },
      { event: "done", feature: "guard", ok: true, configured: false, results: [{ step: "doctor", status: "done", reason: "advisory", code: 1 }, { step: "setup", status: "needs_ui" }], pending: ["restart"] },
    ]);
    expect(run.steps[0]).toMatchObject({ status: "done", reason: "advisory", code: 1 });
    expect(needsUiKind(run.needsUi!)).toBe("guard");
    expect(run.done?.pending).toEqual(["restart"]);
    const missing = fold(lines(runGuardMissing));
    expect(missing.error?.code).toBe("not_installed");
  });

  it("shows an action the owner takes in Terminal and never treats it as runnable", () => {
    // Issue 173 (docs/reference/setup.md, "Check steps"): a `check` per check step, then a
    // `needs_ui` with `summary` and `action` and neither `command` nor `argv`.
    const action = {
      kind: "sudo",
      text: "Run this in your own terminal, as yourself and not with sudo: it asks for your password (sudo) only for the steps that need root. tau never runs it.",
      command: "bash ~/.local/share/tau/remote/setup-all.sh",
      sudo: true,
      url: null,
      changes: ["installs tmux and mosh with Homebrew", "with sudo: writes /etc/ssh/sshd_config.d/010-tau.conf"],
      script: "~/.local/share/tau/remote/setup-all.sh",
    };
    const run = fold([
      { event: "progress", feature: "remote", step: "tailscale", status: "checking", label: "Tailscale on this machine", command: ["remote", "tailscale"] },
      { event: "check", feature: "remote", step: "tailscale", ok: true, summary: "Tailscale is connected as my-mac.tailXXXXXX.ts.net", checks: [{ id: "connected", label: "Connected", status: "ok", detail: "my-mac.tailXXXXXX.ts.net" }], action: null, values: { host: "my-mac.tailXXXXXX.ts.net", ip: "100.x.y.z" } },
      { event: "progress", feature: "remote", step: "tailscale", status: "done", code: 0, label: "Tailscale on this machine" },
      { event: "progress", feature: "remote", step: "ssh", status: "checking", label: "SSH and mosh", command: ["remote", "ssh"] },
      {
        event: "check",
        feature: "remote",
        step: "ssh",
        ok: false,
        summary: "6 problem(s) with SSH, mosh or tmux",
        checks: [
          { id: "sshd", label: "SSH server", status: "fail", detail: "off (Remote Login)" },
          { id: "tmux", label: "tmux", status: "ok", detail: "/opt/homebrew/bin/tmux" },
          { id: "tmux_conf", label: "~/.tmux.conf block (tau's tmux settings)", status: "warn", detail: "missing" },
        ],
        action,
        values: { user: "alice", script: "~/.local/share/tau/remote/setup-all.sh" },
      },
      { event: "needs_ui", feature: "remote", step: "ssh", label: "SSH and mosh", summary: "6 problem(s) with SSH, mosh or tmux", action },
      { event: "done", feature: "remote", ok: true, configured: false, results: [{ step: "tailscale", status: "done", code: 0 }, { step: "ssh", status: "needs_ui" }], pending: ["ssh", "phone"] },
    ]);
    expect(run.steps.map((s) => [s.id, s.status])).toEqual([
      ["tailscale", "done"],
      ["ssh", "needs_ui"],
    ]);
    expect(run.steps[1].check).toMatchObject({ ok: false, summary: "6 problem(s) with SSH, mosh or tmux" });
    expect(run.steps[1].check?.checks.map((c) => c.status)).toEqual(["fail", "ok", "warn"]);
    expect(run.needsUi).toMatchObject({ step: "ssh", command: [], summary: "6 problem(s) with SSH, mosh or tmux" });
    expect(run.needsUi?.argv).toBeUndefined();
    expect(needsUiKind(run.needsUi!)).toBe("action");
    expect(actionCommand(run.needsUi!.action!)).toBe("bash ~/.local/share/tau/remote/setup-all.sh");
    expect(actionCommand({ command: ["open", "-a", "Tailscale"] })).toBe("open -a Tailscale");
    expect(actionCommand({ text: "only words", command: null })).toBeNull();
    expect(run.done?.pending).toEqual(["ssh", "phone"]);
    // With an argv it is the app's own step again, whatever else it carries.
    expect(needsUiKind({ ...run.needsUi!, argv: ["python", "-m", "tau_core", "remote", "ssh"] })).toBe(
      "terminal",
    );
  });

  it("stops at the recorded SSH action, with the check itself first in pending", () => {
    // Recorded in a scratch home where SSH was not set up for that user.
    const run = fold(lines(runRemoteAction));
    expect(run.steps.map((s) => [s.id, s.status])).toEqual([
      ["tailscale", "done"],
      ["ssh", "needs_ui"],
    ]);
    expect(run.steps[1].check?.ok).toBe(false);
    expect(run.steps[1].check?.checks.some((c) => c.status === "fail")).toBe(true);
    expect(needsUiKind(run.needsUi!)).toBe("action");
    expect(run.needsUi?.action).toMatchObject({ kind: "sudo", sudo: true, url: null });
    expect(actionCommand(run.needsUi!.action!)).toMatch(/^bash .*setup-all\.sh$/);
    expect(run.needsUi?.action?.changes?.length).toBeGreaterThan(2);
    expect(run.done).toMatchObject({ configured: false, pending: ["ssh", "phone"] });
  });

  it("follows remote access's check steps on a Mac where they pass", () => {
    const run = fold(lines(runRemote));
    expect(run.steps.map((s) => [s.id, s.status])).toEqual([
      ["tailscale", "done"],
      ["ssh", "done"],
      ["phone", "done"],
    ]);
    expect(run.steps.every((s) => s.check?.ok)).toBe(true);
    expect(run.needsUi).toBeNull();
    expect(run.done).toMatchObject({ ok: true, configured: true, pending: [] });
    // The phone step's values, for the Termius card.
    const phone = fold(lines(runRemotePhone));
    expect(phone.steps[0].check?.values).toMatchObject({
      host: "my-mac.tailXXXXXX.ts.net",
      ip: "100.x.y.z",
      port: 22,
      mosh: true,
      startup: "tau-attach",
    });
    expect(phone.steps[0].check?.checks.map((c) => c.id)).toContain("key");
  });

  it("logs plain output and stderr, and keeps the log short", () => {
    let run = fold([
      { event: "text", line: "downloading uv 0.10.11" },
      { event: "stderr", line: "warning: PATH" },
    ]);
    expect(run.logs).toEqual([{ line: "downloading uv 0.10.11" }, { line: "warning: PATH", stderr: true }]);
    for (let i = 0; i < 1000; i += 1) run = reduceRun(run, { event: "log", line: `line ${i}` });
    expect(run.logs.length).toBe(400);
    expect(run.logs[399].line).toBe("line 999");
    // Unknown events change nothing.
    expect(reduceRun(run, { event: "future" })).toBe(run);
  });
});

describe("tau setup install --json and doctor", () => {
  it("plans, installs and says what it installed", () => {
    const run = fold(lines(installNet));
    expect(run.plan).toMatchObject({ features: ["net"], added: ["tau-net"] });
    expect(run.phase).toBe("install");
    expect(run.logs[0].line).toMatch(/Resolved/);
    expect(run.done).toMatchObject({ ok: true, installed: ["tau-net"], changed: true });
  });

  it("carries the doctor's checks", () => {
    const run = fold(lines(runDoctor));
    expect(run.done?.checks?.map((c) => c.name)).toContain("config");
  });
});

describe("tau telegram pair --json", () => {
  const stream: JobEvent[] = [
    { event: "note", message: "Note: TELEGRAM_BOT_TOKEN is also set in this shell's environment." },
    { event: "bot", bot: "example_tau_bot", token: "written" },
    { event: "code", code: "K7QM-X2PA", link: "https://t.me/example_tau_bot?start=K7QM-X2PA", bot: "example_tau_bot", expires_at: "2026-10-01T11:32:00+00:00" },
    { event: "waiting", via: "hub" },
  ];

  it("shows the code and its link, then the pairing", () => {
    const waiting = stream.reduce(reducePair, emptyPair);
    expect(waiting).toMatchObject({
      bot: "example_tau_bot",
      token: "written",
      code: { code: "K7QM-X2PA", link: "https://t.me/example_tau_bot?start=K7QM-X2PA" },
      waiting: "hub",
      paired: null,
    });
    expect(waiting.notes).toHaveLength(1);
    const paired = reducePair(waiting, { event: "paired", name: "Example @example", dropped: 0, hub: true });
    expect(paired).toMatchObject({ waiting: null, paired: { name: "Example @example", hub: true } });
  });

  it("asks for the token again when it was missing or refused", () => {
    for (const reason of ["no_token", "token_invalid", "token_refused"]) {
      const state = reducePair(emptyPair, { event: "error", reason, message: "…" });
      expect(pairNeedsToken(state)).toBe(true);
    }
    const expired = reducePair(stream.reduce(reducePair, emptyPair), {
      event: "error",
      reason: "expired",
      message: "The code expired.",
    });
    expect(pairNeedsToken(expired)).toBe(false);
    expect(expired.error?.message).toBe("The code expired.");
    expect(expired.waiting).toBeNull();
  });
});

describe("tau net spine deploy --json", () => {
  it("asks for a token, then an account, then shows the address", () => {
    const needToken = reduceSpine(emptySpine, {
      type: "need_token",
      link: "https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=…",
      scopes: ["workers_scripts:edit"],
      permissions: ["Account > Workers Scripts > Edit", "Account > Workers KV Storage > Edit"],
      message: "Create an API token…",
    });
    expect(needToken.needToken?.permissions).toHaveLength(2);
    const choose = reduceSpine(emptySpine, {
      type: "choose_account",
      accounts: [
        { id: "0123456789abcdef", name: "Personal" },
        { id: "fedcba9876543210", name: "Work" },
      ],
      message: "Several accounts",
    });
    expect(choose.accounts?.map((a) => a.name)).toEqual(["Personal", "Work"]);
    const done = [
      { type: "progress", key: "net.spine.upload", text: "Uploading worker.js", fields: {} },
      { event: "stderr", line: "a warning" },
      { type: "done", url: "https://tau-spine.example.workers.dev", account_id: "0123456789abcdef", token_created: true, healthy: false },
    ].reduce(reduceSpine, emptySpine);
    expect(done.progress.map((p) => p.text)).toEqual(["Uploading worker.js", "a warning"]);
    expect(done.done).toMatchObject({ url: "https://tau-spine.example.workers.dev", healthy: false });
    expect(reduceSpine(emptySpine, { type: "error", message: "403: the token lacks Workers Scripts" }).error).toMatch(
      /403/,
    );
  });
});
