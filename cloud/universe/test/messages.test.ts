/** The universe page's script strings: one table per language, the same keys in each. */

import { describe, expect, it } from "vitest";
import { MESSAGES, type Messages, pageLanguage } from "../client/messages";

const keys = (table: Messages) => Object.keys(table).sort();

/** Every message with sample arguments, as text. */
function rendered(table: Messages): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(table) as [string, unknown][]) {
    out[key] =
      typeof value === "function"
        ? String((value as (...args: unknown[]) => string)(2, "2", "3"))
        : String(value);
  }
  return out;
}

describe("the universe page's messages", () => {
  it("have the same keys in English and Turkish", () => {
    expect(keys(MESSAGES.tr)).toEqual(keys(MESSAGES.en));
    expect(keys(MESSAGES.en).length).toBeGreaterThan(20);
  });

  it("have the same shape for every key: text or a function of the same arguments", () => {
    for (const key of keys(MESSAGES.en) as (keyof Messages)[]) {
      const en = MESSAGES.en[key];
      const tr = MESSAGES.tr[key];
      expect(typeof tr, key).toBe(typeof en);
      if (typeof en === "function" && typeof tr === "function") {
        expect(tr.length, key).toBe(en.length);
      }
    }
  });

  it("are never empty, and keep the join command's place in both languages", () => {
    const en = rendered(MESSAGES.en);
    const tr = rendered(MESSAGES.tr);
    for (const key of Object.keys(en)) {
      expect(en[key]!.trim(), key).not.toBe("");
      expect(tr[key]!.trim(), key).not.toBe("");
      expect(tr[key]!.includes("{cmd}"), key).toBe(en[key]!.includes("{cmd}"));
    }
    expect(MESSAGES.en.runOnHub).toContain("{cmd}");
    expect(MESSAGES.en.fewSoFar("3 taus")).toContain("{cmd}");
  });

  it("count in each language's own way", () => {
    expect(MESSAGES.en.taus(1, "1")).toBe("1 tau");
    expect(MESSAGES.en.taus(3, "3")).toBe("3 taus");
    expect(MESSAGES.en.msgs(14, "14")).toBe("14 msgs");
    expect(MESSAGES.tr.taus(3, "3")).toBe("3 tau");
    expect(MESSAGES.tr.msgs(14, "14")).toBe("14 mesaj");
    expect(MESSAGES.en.skyCount("14 msgs", "3", "7 taus")).toBe("14 msgs · 3 of 7 taus");
    expect(MESSAGES.tr.skyCount("14 mesaj", "3", "7 tau")).toBe("14 mesaj · 7 tau, 3 çevrimiçi");
  });

  it("are chosen by <html lang>", () => {
    expect(pageLanguage("tr")).toBe("tr");
    expect(pageLanguage("tr-TR")).toBe("tr");
    expect(pageLanguage("en")).toBe("en");
    expect(pageLanguage("")).toBe("en");
    expect(pageLanguage(null)).toBe("en");
    expect(pageLanguage("de")).toBe("en");
  });
});
