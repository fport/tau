/**
 * The tools of a hosted tau and their tiers (ADR 0013 §2), with the descriptions the model
 * reads (fixed English, as tau-sub's tools say them).
 *
 * - `ask_sub` is tier 0: it runs one of the owner's sub-taus for one turn.
 * - `create_sub` is tier 2: it activates a new agent configuration, so every call waits for
 *   the owner's approval in the app.
 *
 * `net_send` (tier 2) joins them with the network (issue 162). The implementations live in
 * the Tau Durable Object, which owns the data they touch; here are only the specs.
 */

import type { ToolSpec } from "../providers/types";

export type Tier = 0 | 1 | 2;

export interface ToolRun {
  text: string;
  error?: boolean;
}

export interface HostTool {
  spec: ToolSpec;
  tier: Tier;
  /** What a tier-2 call does, shown on the approval card. */
  effect?: string;
  run(input: Record<string, unknown>): Promise<ToolRun>;
}

export const ASK_SUB_SPEC: ToolSpec = {
  name: "ask_sub",
  description:
    "Ask one of the owner's sub-taus a question and return its answer. A sub-tau is a small " +
    "specialist of this tau with its own persona and model (for example /coach for workouts). " +
    "It runs one turn on its own. Call it with an empty name to list the sub-taus.",
  parameters: {
    type: "object",
    properties: {
      name: {
        type: "string",
        description: 'The sub-tau\'s name without the slash, for example "coach"; empty to list them.',
      },
      question: {
        type: "string",
        description:
          "The question, with every detail the sub-tau needs: it does not see this conversation.",
      },
    },
    required: ["name", "question"],
  },
};

export const CREATE_EFFECT = "Creates a new sub-tau of your tau.";

export const CREATE_SUB_SPEC: ToolSpec = {
  name: "create_sub",
  description:
    "Create a new sub-tau: a small specialist of the owner's tau with its own persona. Needs " +
    "the owner's approval every time. An existing sub-tau is never replaced.",
  parameters: {
    type: "object",
    properties: {
      name: {
        type: "string",
        description: '2 to 31 characters: lowercase letters, digits and "-", starting with a letter.',
      },
      about: {
        type: "string",
        description: "One line of at most 200 characters saying what the sub-tau does.",
      },
      persona: {
        type: "string",
        description: "The specialist's character and task, written to it in the second person.",
      },
    },
    required: ["name", "about", "persona"],
  },
};

/** The answer of a call that was never run because an earlier approval of its turn expired. */
export const TOOL_LIMIT_NOTE = "Not run: the turn ended when an earlier approval request in it expired.";

/** Why a tier-2 call did not run (the model reads it as the tool's answer). */
export function refusal(tool: string, reason: "denied" | "expired"): string {
  return reason === "denied"
    ? `The owner did not approve ${tool}; it was not run. Do not try it another way.`
    : `The owner did not answer the approval request for ${tool} within 10 minutes; it was not run.`;
}
