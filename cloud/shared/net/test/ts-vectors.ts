/**
 * TypeScript → Python: the vectors of net/ts-vectors.json, built by this module from random
 * inputs (`pnpm run vectors`, make-ts-vectors.mjs) and checked by tau-net
 * (packages/tau-net/tests/test_ts_vectors.py): keys TypeScript generated, envelopes it built
 * and sealed (`host/@handle` addresses and the `visit` kind included), universe requests it
 * signed (`claim` included) and a claim link.
 *
 * The random inputs are recorded in the file, so ts-vectors.test.ts rebuilds it and fails
 * when the TypeScript no longer produces the same bytes. Every key is test-only.
 */

import {
  b64uDecode,
  b64uEncode,
  buildEnvelope,
  claimLink,
  Identity,
  makeRequestPayload,
  newId,
  randomBytes,
  signRequest,
  type IdentityJson,
  type Kind,
  type PayloadFields,
  type UniverseKind,
} from "../index.ts";

export const TS = 1_790_000_000;
export const UNIVERSE = "universe.example.com";

/** The taus of the vectors: a hosted tau with a handle address, a hub, and a universe. */
export const ADDRESSES = {
  host: "tau.example.com/@alice",
  hub: "bob.example.com",
  universe: UNIVERSE,
} as const;
type Label = keyof typeof ADDRESSES;

const TRICKY_TEXT =
  'Quotes " and \\ backslash, newline \n tab \t, controls \u0001 \u001f \u007f, separators ' +
  "   , html <b>&amp;</b> 'single', slash / and emoji 🌟🇹🇷, " +
  "Türkçe: çğıöşü İĞÜŞÖÇ, zero width ‍, BOM ﻿ mid-text.";

const VISITOR_THREAD = "visitor-thread-000000000002";

interface EnvelopeSpec {
  name: string;
  note: string;
  sender: Label;
  recipient: Label;
  kind: Kind;
  content: Record<string, unknown>;
  /** The case whose id is this envelope's thread and reply_to (an answer), if any. */
  answers?: string;
  thread?: string;
  hops?: number;
}

const ENVELOPES: EnvelopeSpec[] = [
  {
    name: "contact_request_from_handle",
    note: "a hosted tau (host/@handle address) asks a hub for contact",
    sender: "host",
    recipient: "hub",
    kind: "contact_request",
    content: { name: "Alice's hosted tau", text: "Merhaba! Ben barındırılan bir tau'yum 🌿" },
  },
  {
    name: "message_to_handle_from_sub",
    note: "a hub's sub-tau answers a hosted tau: odd hops, sub names the sender's sub-tau",
    sender: "hub",
    recipient: "host",
    kind: "message",
    content: { text: "Our /coach says hi.", sub: "coach" },
    answers: "contact_request_from_handle",
  },
  {
    name: "visit",
    note: "ADR 0013 §5: the universe relays a visitor's text to a hub-run web sub-tau",
    sender: "universe",
    recipient: "hub",
    kind: "visit",
    content: { text: 'Hi! Can you help me plan a 10k? "quoted" \\ ş 🌟', sub: "coach" },
    thread: VISITOR_THREAD,
  },
  {
    name: "message_answering_visit",
    note: "the hub answers a visit with a message: same thread and sub, reply_to, hops 1",
    sender: "hub",
    recipient: "universe",
    kind: "message",
    content: { text: "Sure: three easy runs a week to start.", sub: "coach" },
    answers: "visit",
  },
  {
    name: "message_tricky_text",
    note: "JSON escapes, non-ASCII text and an unknown key, between plain addresses",
    sender: "universe",
    recipient: "hub",
    kind: "message",
    content: { text: TRICKY_TEXT, mood: "curious" },
  },
];

interface RequestSpec {
  name: string;
  note: string;
  signer: Label;
  kind: UniverseKind;
  fields: Omit<PayloadFields, "universe" | "address" | "ts" | "nonce">;
  /** Overrides the signer's address (a claim from an own-host tau). */
  address?: string;
}

const REQUESTS: RequestSpec[] = [
  {
    name: "join",
    note: "join with owner and about",
    signer: "hub",
    kind: "join",
    fields: { owner: "Bob", about: "Runs a hub at home. İyi günler! 🌿" },
  },
  {
    name: "report_plain",
    note: "a report tau-net's own make_payload would write",
    signer: "hub",
    kind: "report",
    fields: {
      links: [{ peer: "alice.example.com", messages: 3 }],
      subs: [{ name: "coach", about: "A patient running coach." }],
    },
  },
  {
    name: "report_web_subs",
    note: "ADR 0013: a link to a handle address and a web sub-tau with starters",
    signer: "host",
    kind: "report",
    fields: {
      links: [{ peer: "bob.example.com", messages: 7 }],
      subs: [
        {
          name: "coach",
          about: "A patient running coach.",
          web: true,
          starters: ["Plan my first 5k", "How often should I run?"],
        },
        { name: "study-buddy", about: "", web: false },
      ],
    },
  },
  { name: "leave", note: "leave has no extra fields", signer: "hub", kind: "leave", fields: {} },
  { name: "claim_plain", note: "a hub claims a handle", signer: "hub", kind: "claim", fields: {} },
  {
    name: "claim_handle_address",
    note: "an own-host tau claims a handle for its host/@handle address",
    signer: "host",
    kind: "claim",
    fields: {},
    address: "own.example.com/@alice",
  },
];

/** The random inputs of the vectors, recorded in the file. */
export interface TsVectorInputs {
  identities: Record<Label, IdentityJson>;
  envelopes: Record<string, { id: string; ephemeral_secret: string; nonce: string }>;
  claim_nonces: Record<string, string>;
}

/** Fresh random inputs: new test-only identities, ids, ephemeral keys, nonces. */
export async function freshInputs(): Promise<TsVectorInputs> {
  const identities = {} as Record<Label, IdentityJson>;
  for (const label of Object.keys(ADDRESSES) as Label[]) {
    identities[label] = (await Identity.generate()).toIdentityJson();
  }
  const envelopes: TsVectorInputs["envelopes"] = {};
  for (const spec of ENVELOPES) {
    envelopes[spec.name] = {
      id: newId(),
      ephemeral_secret: b64uEncode(randomBytes(32)),
      nonce: b64uEncode(randomBytes(12)),
    };
  }
  const claim_nonces: Record<string, string> = {};
  for (const spec of REQUESTS) if (spec.kind === "claim") claim_nonces[spec.name] = newId();
  return { identities, envelopes, claim_nonces };
}

function bytes(text: string | undefined): Uint8Array {
  const decoded = text === undefined ? null : b64uDecode(text);
  if (decoded === null) throw new Error("ts-vectors: a recorded input is missing or not b64u");
  return decoded;
}

/** Builds every vector from `inputs`: the same inputs always give the same file. */
export async function buildTsVectors(inputs: TsVectorInputs) {
  const ids = {} as Record<Label, Identity>;
  const identities: Record<string, unknown> = {};
  for (const label of Object.keys(ADDRESSES) as Label[]) {
    const id = await Identity.fromJson(inputs.identities[label]);
    ids[label] = id;
    identities[label] = {
      address: ADDRESSES[label],
      identity: id.toIdentityJson(),
      env_value: id.toEnvValue(),
      sign_key: id.signKey,
      box_key: id.boxKey,
    };
  }

  const envelopes = [];
  const built: Record<string, { id: string; thread: string }> = {};
  for (const spec of ENVELOPES) {
    const random = inputs.envelopes[spec.name];
    if (random === undefined) throw new Error(`ts-vectors: no inputs for ${spec.name}`);
    const answered = spec.answers === undefined ? undefined : built[spec.answers];
    const thread = answered?.thread ?? spec.thread ?? null;
    const replyTo = answered?.id ?? null;
    const hops = answered === undefined ? (spec.hops ?? 0) : 1;
    const input = {
      from: ADDRESSES[spec.sender],
      to: ADDRESSES[spec.recipient],
      kind: spec.kind,
      content: spec.content,
      id: random.id,
      thread,
      reply_to: replyTo,
      hops,
      ts: TS,
      ephemeral_secret: random.ephemeral_secret,
      nonce: random.nonce,
    };
    const result = await buildEnvelope(ids[spec.sender], {
      from: input.from,
      to: input.to,
      recipientBoxKey: ids[spec.recipient].boxKey,
      kind: spec.kind,
      content: spec.content,
      id: input.id,
      thread,
      replyTo,
      hops,
      ts: TS,
      seal: { ephemeralSecret: bytes(input.ephemeral_secret), nonce: bytes(input.nonce) },
    });
    built[spec.name] = { id: result.payload.id, thread: result.payload.thread };
    envelopes.push({
      name: spec.name,
      note: spec.note,
      sender: spec.sender,
      recipient: spec.recipient,
      input,
      payload: result.payload,
      envelope: result.envelope,
    });
  }

  const universe = [];
  let claim: { request: unknown; link: string } | undefined;
  for (const spec of REQUESTS) {
    const nonce = spec.kind === "claim" ? inputs.claim_nonces[spec.name] : undefined;
    if (spec.kind === "claim" && nonce === undefined) {
      throw new Error(`ts-vectors: no nonce for ${spec.name}`);
    }
    const input = {
      kind: spec.kind,
      universe: UNIVERSE,
      address: spec.address ?? ADDRESSES[spec.signer],
      ts: TS,
      ...spec.fields,
      ...(nonce === undefined ? {} : { nonce }),
    };
    const payload = makeRequestPayload(spec.kind, input);
    const request = await signRequest(ids[spec.signer], payload);
    universe.push({
      name: spec.name,
      note: spec.note,
      signer: spec.signer,
      input,
      payload,
      request,
    });
    if (spec.name === "claim_plain") claim = { request, link: claimLink(UNIVERSE, request) };
  }

  return {
    about:
      "Test vectors from cloud/shared/net for tau-net (issue 158). Generated by `pnpm run " +
      "vectors` in cloud/shared (net/test/make-ts-vectors.mjs) from the random inputs below; " +
      "do not edit. Every key is test-only.",
    inputs,
    identities,
    envelopes,
    universe,
    claim_link: claim,
  };
}
