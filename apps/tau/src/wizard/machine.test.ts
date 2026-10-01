import { describe, expect, it } from "vitest";
import type { FeatureStatus, SetupStatus } from "./api";
import {
  STEPS,
  afterNeedsUi,
  defaultChoice,
  defaultSteps,
  featureRows,
  initialState,
  inputFields,
  inputsFor,
  nextStep,
  outcomeOf,
  permissionsFor,
  previousStep,
  reducer,
  setupKind,
  setupQueue,
  summaryState,
  toInstall,
  toggle,
} from "./machine";
// Recorded with `tau setup status --json` (tau-core from this repository in a throwaway
// `uv tool` environment, a scratch TAU_HOME; paths replaced by /Users/example).
import freshEn from "./fixtures/status-fresh-en.json";
import freshTr from "./fixtures/status-fresh-tr.json";
import afterEn from "./fixtures/status-after-en.json";
import linuxEn from "./fixtures/status-linux-en.json";

const fresh = freshEn as SetupStatus;
const linux = linuxEn as SetupStatus;
const after = afterEn as SetupStatus;

/** The fresh status as on a Mac without the app in /Applications. */
function withoutApp(status: SetupStatus): SetupStatus {
  return {
    ...status,
    features: status.features.map((f) =>
      f.id === "app" ? { ...f, state: "available", configured: false } : f,
    ),
  };
}

function feature(status: SetupStatus, id: string): FeatureStatus {
  const found = status.features.find((f) => f.id === id);
  if (!found) throw new Error(`no ${id}`);
  return found;
}

describe("the steps", () => {
  it("go forward and back, and every step can be skipped", () => {
    expect(STEPS[0]).toBe("language");
    expect(STEPS[STEPS.length - 1]).toBe("summary");
    expect(nextStep("language")).toBe("install");
    expect(nextStep("summary")).toBe("summary");
    expect(previousStep("language")).toBe("language");
    let state = initialState("tr");
    expect(state.current).toBe("language");
    state = reducer(state, { type: "complete", step: "language" });
    expect(state).toMatchObject({ current: "install", marks: { language: "done" } });
    state = reducer(state, { type: "skip", step: "install" });
    expect(state).toMatchObject({ current: "key", marks: { install: "skipped" } });
    state = reducer(state, { type: "complete", step: "key", mark: "failed" });
    expect(state.marks.key).toBe("failed");
    state = reducer(state, { type: "go", step: "language" });
    expect(state.current).toBe("language");
    state = reducer(state, { type: "lang", lang: "en" });
    expect(state.lang).toBe("en");
    state = reducer(state, { type: "outcome", feature: "guard", outcome: "partial" });
    expect(state.outcomes).toEqual({ guard: "partial" });
  });
});

describe("the features", () => {
  it("choose the catalog's defaults on a first run, and nothing new later", () => {
    // tui and the app are set up already in this recording (TauBar.app was in /Applications).
    expect(defaultChoice(fresh, true)).toEqual(["sub", "autostart"]);
    expect(defaultChoice(withoutApp(fresh), true)).toEqual(["app", "sub", "autostart"]);
    expect(defaultChoice(fresh, false)).toEqual([]);
    // Linux has no app and no guard; autostart is not a default there.
    expect(defaultChoice(linux, true)).toEqual([]);
  });

  it("render with labels, states and why a feature is missing", () => {
    const rows = featureRows(linux, []);
    const guard = rows.find((r) => r.id === "guard");
    expect(guard).toMatchObject({
      locked: true,
      checked: false,
      state: "unavailable",
      permissions: ["camera"],
    });
    expect(guard?.unavailableReason).toMatch(/macOS only/);
    const tui = rows.find((r) => r.id === "tui");
    expect(tui).toMatchObject({ checked: true, locked: true, state: "done" });
    const cloud = featureRows(fresh, ["cloud"]).find((r) => r.id === "cloud");
    expect(cloud).toMatchObject({ advanced: true, checked: true, requires: ["The tau network"] });
    // The labels come from tau in the chosen language.
    const tr = featureRows(freshTr as SetupStatus, []);
    expect(tr.find((r) => r.id === "guard")?.label).not.toBe(
      featureRows(fresh, []).find((r) => r.id === "guard")?.label,
    );
  });

  it("toggle with their requirements, and never a locked one", () => {
    expect(toggle(fresh, [], "cloud")).toEqual(["net", "cloud"]);
    expect(toggle(fresh, ["net", "cloud"], "net")).toEqual([]);
    expect(toggle(fresh, ["net", "cloud"], "cloud")).toEqual(["net"]);
    expect(toggle(fresh, ["sub"], "tui")).toEqual(["sub"]);
    expect(toggle(linux, [], "guard")).toEqual([]);
    expect(toggle(fresh, [], "nope")).toEqual([]);
  });

  it("install only the missing packages of the chosen ones", () => {
    expect(toInstall(fresh, ["sub", "guard", "telegram", "autostart", "net"])).toEqual([
      "sub",
      "guard",
      "net",
    ]);
    expect(toInstall(after, ["net"])).toEqual([]);
    expect(toInstall(linux, ["guard"])).toEqual([]);
  });
});

describe("the permissions", () => {
  it("are only those of the features that will be on", () => {
    expect(permissionsFor(withoutApp(fresh), ["sub", "net"])).toEqual([]);
    const rows = permissionsFor(withoutApp(fresh), ["guard", "app"]);
    expect(rows.map((r) => r.id)).toEqual(["camera", "notifications"]);
    expect(rows[0].features).toEqual([feature(fresh, "guard").label]);
    // The app is set up in this recording, so notifications come with it.
    expect(permissionsFor(fresh, []).map((r) => r.id)).toEqual(["notifications"]);
    // Linux: neither the app nor the guard, whatever was passed.
    expect(permissionsFor(linux, ["guard", "app"])).toEqual([]);
    // The microphone only when a chosen feature asks for it.
    const voice: SetupStatus = {
      ...fresh,
      features: [
        ...fresh.features,
        {
          ...feature(fresh, "sub"),
          id: "voice",
          label: "Voice",
          state: "missing",
          permissions: [{ id: "microphone", label: "microphone" }],
        },
      ],
    };
    expect(permissionsFor(voice, ["guard"]).map((r) => r.id)).toEqual([
      "camera",
      "notifications",
    ]);
    expect(permissionsFor(voice, ["voice"]).map((r) => r.id)).toEqual([
      "notifications",
      "microphone",
    ]);
  });
});

describe("the feature steps", () => {
  it("know how each chosen feature is set up", () => {
    const queue = setupQueue(fresh, ["guard", "app", "autostart", "tui", "telegram", "nope"]);
    expect(queue.map((f) => f.id)).toEqual(["tui", "app", "telegram", "guard", "autostart"]);
    expect(queue.map((f) => setupKind(fresh, f))).toEqual([
      "nothing",
      "this_app",
      "run",
      "run",
      "app_autostart",
    ]);
    // On Linux start-at-login is the engine's systemd note.
    expect(setupKind(linux, feature(linux, "autostart"))).toBe("run");
    expect(setupQueue(linux, ["guard"])).toEqual([]);
  });

  it("run the steps that are not optional, with the inputs those steps take", () => {
    const net = feature(fresh, "net");
    expect(defaultSteps(net)).toEqual(["init", "spine"]);
    expect(defaultSteps(feature(fresh, "guard"))).toEqual(["doctor", "setup", "restart"]);
    const values = { name: "Test tau", spine_dir: "~/tau-spine", owner: "", about: "x" };
    expect(inputsFor(net, ["init"], values)).toEqual({ name: "Test tau" });
    expect(inputsFor(net, ["init", "spine-init", "universe"], values)).toEqual({
      name: "Test tau",
      spine_dir: "~/tau-spine",
      about: "x",
    });
    // spine_dir is asked once for both spine steps.
    expect(inputFields(net, ["spine-init", "spine-deploy"]).map((i) => i.name)).toEqual([
      "spine_dir",
      "address",
    ]);
    expect(inputFields(net, ["spine-init"])[0]).toMatchObject({
      name: "spine_dir",
      required: true,
      default: "~/tau-spine",
      secret: false,
    });
  });

  it("go on after a step that needed the owner", () => {
    // A step the app ran itself (the guard's enrolment): `pending` is what comes after it.
    expect(afterNeedsUi(["restart"], "setup", "done")).toEqual(["restart"]);
    expect(afterNeedsUi(["restart"], "setup", "skip")).toEqual(["restart"]);
    expect(afterNeedsUi([], "pair", "done")).toEqual([]);
    // An action in Terminal (issue 173): `pending` starts with it, "done" checks it again.
    expect(afterNeedsUi(["ssh", "phone"], "ssh", "done")).toEqual(["ssh", "phone"]);
    expect(afterNeedsUi(["ssh", "phone"], "ssh", "skip")).toEqual(["phone"]);
  });

  it("sum up a feature", () => {
    expect(outcomeOf([{ status: "done" }, { status: "info" }], false)).toBe("done");
    expect(outcomeOf([{ status: "done" }, { status: "failed" }], false)).toBe("failed");
    expect(outcomeOf([{ status: "done" }], true)).toBe("partial");
    expect(summaryState(feature(after, "net"), [], {})).toBe("on");
    expect(summaryState(feature(after, "guard"), ["guard"], { guard: "partial" })).toBe("partial");
    expect(summaryState(feature(after, "guard"), ["guard"], {})).toBe("skipped");
    expect(summaryState(feature(after, "guard"), [], {})).toBe("not_chosen");
  });
});
