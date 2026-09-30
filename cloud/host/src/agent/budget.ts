/**
 * Prices and the monthly budget (ADR 0011, ADR 0013 §2).
 *
 * Every model call's usage is priced with the price table generated from tau-core
 * (src/generated/prices.ts) and recorded in the tau's spend ledger. The budget is US dollars
 * per calendar month in UTC, 5 by default. A turn that would start with the month's spend at
 * or over the budget is refused; visitor turns and drafts count against the same budget.
 * A model without a price counts as free, like tau-core's unpriced calls; the app says so.
 */

import { PRICES, type Price } from "../generated/prices";
import type { ProviderName, Usage } from "../providers/types";

export const DEFAULT_BUDGET_USD = 5;
export const MAX_BUDGET_USD = 1000;

const FREE: Price = { input: 0, output: 0, cache_read: 0, cache_write: 0 };

/** The price of a model, free for the fake provider, or null when the table has no entry. */
export function priceFor(provider: ProviderName, model: string): Price | null {
  if (provider === "fake") return FREE;
  return Object.hasOwn(PRICES, model) ? (PRICES[model] ?? null) : null;
}

/** Dollars for one call's normalized usage (cached tokens are apart from `input`). */
export function cost(usage: Usage, price: Price): number {
  const read = price.cache_read ?? price.input;
  const write = price.cache_write ?? price.input;
  const total =
    usage.input * price.input +
    usage.output * price.output +
    usage.cacheRead * read +
    usage.cacheWrite * write;
  return total / 1_000_000;
}

/** `YYYY-MM` of a time in seconds, in UTC: the ledger's month. */
export function monthOf(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 7);
}

/** The first second of the next UTC month: when the budget starts over. */
export function nextMonthStart(seconds: number): number {
  const date = new Date(seconds * 1000);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1) / 1000;
}

export interface BudgetState {
  month: string;
  spent_usd: number;
  budget_usd: number;
  /** When the month's budget starts over (seconds). */
  resets_at: number;
  exhausted: boolean;
}

export function budgetState(spent: number, budget: number, now: number): BudgetState {
  return {
    month: monthOf(now),
    spent_usd: Math.round(spent * 1_000_000) / 1_000_000,
    budget_usd: budget,
    resets_at: nextMonthStart(now),
    exhausted: spent >= budget,
  };
}

/** The `- Budget:` line of `## Now` (fixed English: the model reads it). */
export function budgetLine(state: BudgetState): string {
  return `$${state.spent_usd.toFixed(2)} of $${state.budget_usd.toFixed(2)} used this month (UTC)`;
}
