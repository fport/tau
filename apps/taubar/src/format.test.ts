import { describe, expect, it } from "vitest";
import type { HubSettings, SleepStatus } from "./api";
import {
  SLEEP_CHOICES,
  checkoutSettings,
  formFromSettings,
  formatEnv,
  hubTone,
  lastLines,
  loginNote,
  parseEnv,
  settingsFromForm,
  sleepChoiceEnabled,
} from "./format";

const hubSettings: HubSettings = {
  python: "/path/to/tau/.venv/bin/python",
  tau_home: "/path/to/tau",
  data_dir: null,
  port: 7897,
  path: null,
  env: { TELEGRAM_BOT_TOKEN: "", TAU_PROFILE: "home" },
};

describe("hub form", () => {
  it("round-trips settings", () => {
    const form = formFromSettings(hubSettings);
    expect(form.port).toBe("7897");
    expect(form.data_dir).toBe("");
    expect(form.env).toBe("TAU_PROFILE=home\nTELEGRAM_BOT_TOKEN=");
    expect(settingsFromForm(form)).toEqual({ settings: hubSettings, errors: [] });
  });

  it("turns empty fields into null and rejects a bad port", () => {
    const form = { ...formFromSettings(hubSettings), port: "80000", data_dir: "  " };
    const { settings, errors } = settingsFromForm(form);
    expect(settings.port).toBeNull();
    expect(settings.data_dir).toBeNull();
    expect(errors).toEqual(['Control port must be a number from 1 to 65535, not "80000".']);
  });

  it("parses KEY=value lines", () => {
    expect(parseEnv("# comment\n\nA=1\nB=\nC = x=y \n")).toEqual({
      env: { A: "1", B: "", C: "x=y" },
      errors: [],
    });
    expect(parseEnv("NOPE\n1X=2").errors).toHaveLength(2);
    expect(formatEnv({ B: "2", A: "1" })).toBe("A=1\nB=2");
  });

  it("derives python and TAU_HOME from a checkout", () => {
    expect(checkoutSettings("/path/to/tau/")).toEqual({
      python: "/path/to/tau/.venv/bin/python",
      tau_home: "/path/to/tau",
    });
  });

  it("colours the hub states", () => {
    expect(hubTone("up")).toBe("ok");
    expect(hubTone("restarting")).toBe("attention");
    expect(hubTone("off")).toBe("pending");
    expect(hubTone("error")).toBe("error");
  });
});

const status = (lid_available: boolean): SleepStatus => ({
  wanted: "keep_awake_on_ac",
  effective: "keep_awake_on_ac",
  lid_available,
  disabled_elsewhere: false,
  problem: null,
});

describe("sleep choices", () => {
  it("lists the three modes in menu order", () => {
    expect(SLEEP_CHOICES.map((c) => c.mode)).toEqual([
      "normal",
      "keep_awake_on_ac",
      "keep_awake_lid_closed",
    ]);
  });

  it("offers the lid-closed mode only with the sudoers rule", () => {
    expect(sleepChoiceEnabled("keep_awake_lid_closed", status(false))).toBe(false);
    expect(sleepChoiceEnabled("keep_awake_lid_closed", status(true))).toBe(true);
    expect(sleepChoiceEnabled("normal", status(false))).toBe(true);
    expect(sleepChoiceEnabled("keep_awake_on_ac", status(false))).toBe(true);
  });
});

describe("loginNote", () => {
  it("explains every login item state", () => {
    expect(loginNote("enabled")).toMatch(/opens when you log in/);
    expect(loginNote("requires_approval")).toMatch(/allow it/);
    expect(loginNote("not_found")).toMatch(/does not open at login/);
    expect(loginNote("not_registered")).toMatch(/does not open at login/);
  });
});

describe("lastLines", () => {
  it("keeps the newest lines", () => {
    expect(lastLines(["a", "b", "c"], 2)).toEqual(["b", "c"]);
    expect(lastLines(["a"], 2)).toEqual(["a"]);
  });
});
