/**
 * A Worker that only exists to be bundled: `bun run bundle-check` runs `wrangler deploy
 * --dry-run` on it, so esbuild must resolve the shared modules by relative path and
 * `@noble/ciphers` from cloud/shared/node_modules, the way tau-host and the universe do.
 * Nothing deploys it.
 */

import { buildEnvelope, Identity, openEnvelope } from "../../index.ts";

export default {
  async fetch(): Promise<Response> {
    const tau = await Identity.generate();
    const { envelope } = await buildEnvelope(tau, {
      from: "tau.example.com/@alice",
      to: "tau.example.com/@alice",
      recipientBoxKey: tau.boxKey,
      kind: "message",
      content: { text: "bundled" },
    });
    const opened = await openEnvelope(envelope, tau.signKey, tau);
    return Response.json(opened.content);
  },
} satisfies ExportedHandler;
