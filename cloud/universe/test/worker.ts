/**
 * The Worker under test: the server of src/server.ts with a stand-in renderer, and the
 * Durable Object classes. The pages themselves are React (app/) and need Vite to build, so
 * the server's tests check what the server decides (routes, statuses, languages, headers,
 * lookups) and test/site.test.ts checks the rendered pages in the built Worker.
 */

import type { RenderPage } from "../src/pages";
import { createUniverse } from "../src/server";

export { Directory } from "../src/directory";
export { Relay } from "../src/relay";

/** The stand-in page: says which app route it rendered, in which language. */
export const renderStandIn: RenderPage = async (_request, target) =>
  new Response(
    `<!doctype html><html lang="${target.lang}"><title>${target.path}</title>` +
      `<p data-route="${target.path}">${target.path}</p></html>`,
    { headers: { "content-type": "text/html; charset=utf-8" } },
  );

export default createUniverse(renderStandIn);
