import { describe, expect, it } from "vitest";
import type { SleepStatus } from "./api";
import { SLEEP_CHOICES, lastLines, loginNote, sleepChoiceEnabled } from "./format";

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
