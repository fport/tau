// The setup wizard's state machine and the views it derives from `tau setup status --json`,
// without React or Tauri (tested in machine.test.ts against recorded status fixtures).
//
// The steps, in order: language, install tau, the model key, about you, the features, their
// permissions, each feature's steps, the summary. Every step can be skipped; the rail on the
// left shows each one's mark, and any step can be opened again.

import type { FeatureStatus, Lang, PermissionId, SetupStatus } from "./api";

export const STEPS = [
  "language",
  "install",
  "key",
  "about",
  "features",
  "permissions",
  "setup",
  "summary",
] as const;

export type StepId = (typeof STEPS)[number];
export type Mark = "todo" | "done" | "skipped" | "failed";
/** How a feature's steps went. */
export type Outcome = "done" | "partial" | "failed" | "skipped";

export interface WizardState {
  lang: Lang;
  current: StepId;
  marks: Record<StepId, Mark>;
  /** The features chosen in this run (not those that are set up already). */
  chosen: string[];
  /** Whether the features step has been seen (its default choice applied). */
  choiceMade: boolean;
  outcomes: Record<string, Outcome>;
}

export type Action =
  | { type: "lang"; lang: Lang }
  | { type: "go"; step: StepId }
  | { type: "complete"; step: StepId; mark?: Mark }
  | { type: "skip"; step: StepId }
  | { type: "choose"; chosen: string[] }
  | { type: "outcome"; feature: string; outcome: Outcome };

export function initialState(lang: Lang): WizardState {
  const marks = Object.fromEntries(STEPS.map((s) => [s, "todo"])) as Record<StepId, Mark>;
  return { lang, current: "language", marks, chosen: [], choiceMade: false, outcomes: {} };
}

export function nextStep(step: StepId): StepId {
  const at = STEPS.indexOf(step);
  return STEPS[Math.min(at + 1, STEPS.length - 1)];
}

export function previousStep(step: StepId): StepId {
  const at = STEPS.indexOf(step);
  return STEPS[Math.max(at - 1, 0)];
}

export function reducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case "lang":
      return { ...state, lang: action.lang };
    case "go":
      return { ...state, current: action.step };
    case "complete":
      return {
        ...state,
        marks: { ...state.marks, [action.step]: action.mark ?? "done" },
        current: action.step === "summary" ? "summary" : nextStep(action.step),
      };
    case "skip":
      return {
        ...state,
        marks: { ...state.marks, [action.step]: "skipped" },
        current: nextStep(action.step),
      };
    case "choose":
      return { ...state, chosen: action.chosen, choiceMade: true };
    case "outcome":
      return { ...state, outcomes: { ...state.outcomes, [action.feature]: action.outcome } };
  }
}

// -- features ----------------------------------------------------------------------------

/** The app itself: it has nothing to install and its only step points to the download. */
export const APP_FEATURE = "app";
/** Start at login: on macOS the app does it (run the hub, open at login), not launchd. */
export const AUTOSTART_FEATURE = "autostart";

/** One row of the features list. */
export interface FeatureRow {
  id: string;
  label: string;
  description: string;
  state: FeatureStatus["state"];
  checked: boolean;
  /** Cannot be toggled: set up already, or not on this platform. */
  locked: boolean;
  unavailableReason: string | null;
  advanced: boolean;
  permissions: string[];
  requires: string[];
  docs: string;
}

function byId(status: SetupStatus): Map<string, FeatureStatus> {
  return new Map(status.features.map((f) => [f.id, f]));
}

/** The features chosen on a first visit, as `tau setup` chooses them: on a first run (there
 * was no tau.toml when the wizard started; the key step writes one) the catalog's defaults for
 * this platform that are available and not set up, plus the app itself (the wizard runs in
 * it); on a later run nothing new. */
export function defaultChoice(status: SetupStatus, firstRun: boolean): string[] {
  if (!firstRun) return [];
  return status.features
    .filter(
      (f) => f.available && f.state !== "done" && (f.default || f.id === APP_FEATURE),
    )
    .map((f) => f.id);
}

/** The rows of the features list, in catalog order. */
export function featureRows(status: SetupStatus, chosen: string[]): FeatureRow[] {
  const features = byId(status);
  return status.features.map((f) => ({
    id: f.id,
    label: f.label,
    description: f.description,
    state: f.state,
    checked: f.state === "done" || chosen.includes(f.id),
    locked: !f.available || f.state === "done",
    unavailableReason: f.available ? null : f.unavailable_reason,
    advanced: f.advanced,
    permissions: f.permissions.map((p) => p.label),
    requires: f.requires.map((id) => features.get(id)?.label ?? id),
    docs: f.docs,
  }));
}

/** Toggle `id`: choosing a feature chooses what it requires; dropping one drops what requires
 * it. Locked features never change. */
export function toggle(status: SetupStatus, chosen: string[], id: string): string[] {
  const features = byId(status);
  const feature = features.get(id);
  if (!feature || !feature.available || feature.state === "done") return chosen;
  const next = new Set(chosen);
  if (next.has(id)) {
    const drop = [id];
    while (drop.length) {
      const gone = drop.pop() as string;
      next.delete(gone);
      for (const f of status.features) {
        if (next.has(f.id) && f.requires.includes(gone)) drop.push(f.id);
      }
    }
  } else {
    const add = [id];
    while (add.length) {
      const wanted = add.pop() as string;
      const f = features.get(wanted);
      if (!f || !f.available || f.state === "done" || next.has(wanted)) continue;
      next.add(wanted);
      add.push(...f.requires);
    }
  }
  return status.features.map((f) => f.id).filter((fid) => next.has(fid));
}

/** The chosen features whose package is missing: what `tau setup install` gets. */
export function toInstall(status: SetupStatus, chosen: string[]): string[] {
  return status.features
    .filter((f) => chosen.includes(f.id) && f.available && f.package && !f.installed)
    .map((f) => f.id);
}

/** The features that will be on: chosen now, or set up already (on this platform). */
export function activeFeatures(status: SetupStatus, chosen: string[]): FeatureStatus[] {
  return status.features.filter(
    (f) => f.available && (f.state === "done" || chosen.includes(f.id)),
  );
}

export interface PermissionRow {
  id: PermissionId;
  label: string;
  /** The labels of the features that need it. */
  features: string[];
}

const PERMISSION_ORDER: PermissionId[] = ["camera", "notifications", "microphone"];

/** The macOS permissions of the features that will be on, and only those. */
export function permissionsFor(status: SetupStatus, chosen: string[]): PermissionRow[] {
  const rows = new Map<PermissionId, PermissionRow>();
  for (const f of activeFeatures(status, chosen)) {
    for (const p of f.permissions) {
      const row = rows.get(p.id) ?? { id: p.id, label: p.label, features: [] };
      row.features.push(f.label);
      rows.set(p.id, row);
    }
  }
  return PERMISSION_ORDER.filter((id) => rows.has(id)).map((id) => rows.get(id) as PermissionRow);
}

/** How a chosen feature is set up in the wizard. */
export type SetupKind =
  /** `tau setup run <id> --json`. */
  | "run"
  /** The app itself: nothing to do. */
  | "this_app"
  /** The app runs the hub and opens at login (macOS autostart). */
  | "app_autostart"
  /** No steps on this platform. */
  | "nothing";

export function setupKind(status: SetupStatus, feature: FeatureStatus): SetupKind {
  if (feature.id === APP_FEATURE) return "this_app";
  if (feature.id === AUTOSTART_FEATURE && status.platform === "darwin") return "app_autostart";
  if (!feature.steps.length) return "nothing";
  return "run";
}

/** The chosen features, in catalog order, that the feature-steps page sets up. */
export function setupQueue(status: SetupStatus, chosen: string[]): FeatureStatus[] {
  return status.features.filter((f) => chosen.includes(f.id) && f.available);
}

/** The steps that run unless the owner changes them: every step that is not optional. */
export function defaultSteps(feature: FeatureStatus): string[] {
  return feature.steps.filter((s) => !s.optional).map((s) => s.id);
}

/** The input values a run sends: only names the chosen steps take (tau refuses others), with
 * empty values left out. */
export function inputsFor(
  feature: FeatureStatus,
  steps: string[],
  values: Record<string, string>,
): Record<string, string> {
  const names = new Set(
    feature.steps.filter((s) => steps.includes(s.id)).flatMap((s) => s.inputs.map((i) => i.name)),
  );
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    if (names.has(name) && value.trim() !== "") out[name] = value;
  }
  return out;
}

/** The inputs to show for the chosen steps, each name once (steps share values by name). */
export function inputFields(feature: FeatureStatus, steps: string[]) {
  const seen = new Set<string>();
  return feature.steps
    .filter((s) => steps.includes(s.id))
    .flatMap((s) => s.inputs)
    .filter((input) => (seen.has(input.name) ? false : (seen.add(input.name), true)));
}

/** The steps to run after a step that needed the owner: `pending` from the run's `done`. For
 * a step the app ran itself (`argv`) `pending` holds the steps after it. For an action the
 * owner takes in Terminal (issue 173) `pending` starts with that step again, so "done" re-runs
 * it (a check) and "skip" drops it. */
export function afterNeedsUi(pending: string[], step: string, decision: "done" | "skip"): string[] {
  if (decision === "skip" && pending[0] === step) return pending.slice(1);
  return pending;
}

/** A feature's outcome from what its runs reported. */
export function outcomeOf(results: { status: string }[], skippedUi: boolean): Outcome {
  if (results.some((r) => r.status === "failed")) return "failed";
  if (skippedUi) return "partial";
  return "done";
}

/** The summary's line for a feature. */
export function summaryState(
  feature: FeatureStatus,
  chosen: string[],
  outcomes: Record<string, Outcome>,
): Outcome | "on" | "not_chosen" {
  if (feature.state === "done" || feature.configured) return "on";
  if (outcomes[feature.id]) return outcomes[feature.id];
  if (chosen.includes(feature.id)) return "skipped";
  return "not_chosen";
}
