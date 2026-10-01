import { describe, expect, it } from "vitest";
import { KEYS, TABLES, guessLang, strings } from "./strings";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("the wizard's message table", () => {
  it("has every text in English and Turkish, with the same placeholders", () => {
    for (const key of KEYS) {
      const en = TABLES.en[key];
      const tr = TABLES.tr[key];
      // `features.state.available` is empty on purpose: no badge for it.
      if (key !== "features.state.available") {
        expect(en, key).not.toBe("");
        expect(tr, key).not.toBe("");
      }
      expect(placeholders(tr), key).toEqual(placeholders(en));
    }
  });

  it("fills placeholders and leaves unknown ones", () => {
    expect(strings("en")("install.found", { version: "tau-core 0.5.0" })).toBe("Found tau-core 0.5.0");
    expect(strings("tr")("install.found", { version: "tau-core 0.5.0" })).toBe(
      "tau-core 0.5.0 bulundu",
    );
    expect(strings("en")("common.exit", {})).toBe("It ended with exit code {code}.");
  });

  it("starts in Turkish only when the system asks for it", () => {
    expect(guessLang(["tr-TR", "en-US"])).toBe("tr");
    expect(guessLang(["en-GB", "tr"])).toBe("tr");
    expect(guessLang(["en-US"])).toBe("en");
    expect(guessLang([])).toBe("en");
  });
});
