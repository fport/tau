/**
 * The brain: in cloud mode the Python hub (`tau cloud run`) runs as a Cloudflare Container
 * managed through this Durable Object class. The local-mode configuration has no BRAIN
 * binding, so every caller treats `env.BRAIN` as optional.
 */

import { Container } from "@cloudflare/containers";
import { baseUrl, insecurePeersAllowed } from "./address";
import { BRAIN_SECRET_NAMES, type SpineEnv } from "./env";
import { error, isObject, json, parseJson } from "./http";

/** The single brain instance of this tau. */
export const BRAIN_NAME = "brain";

/** The port `tau cloud run` listens on inside the container. */
export const BRAIN_PORT = 8080;

/** How long a cold start may take before /hub/brain gives up (image pull + Python start). */
const BRAIN_START_TIMEOUT_MS = 90_000;

/**
 * The container's environment: where its spine is, the hub token, and the secrets that are
 * set. TAU_SPINE_URL falls back to the configured ADDRESS when SPINE_URL is empty.
 */
export function brainEnvVars(env: SpineEnv): Record<string, string> {
  const vars: Record<string, string> = {};
  const address = (env.ADDRESS ?? "").trim().toLowerCase();
  const spineUrl =
    (env.SPINE_URL ?? "").trim() || (address ? baseUrl(address, insecurePeersAllowed(env)) : "");
  if (spineUrl) vars.TAU_SPINE_URL = spineUrl.replace(/\/+$/, "");
  if (env.HUB_TOKEN) vars.TAU_SPINE_TOKEN = env.HUB_TOKEN;
  for (const name of BRAIN_SECRET_NAMES) {
    const value = env[name];
    if (typeof value === "string" && value !== "") vars[name] = value;
  }
  return vars;
}

export interface BrainHealth {
  status: number;
  body: string;
}

export class TauBrain extends Container<SpineEnv> {
  override defaultPort = BRAIN_PORT;
  // Without KEEP_AWAKE the brain sleeps after 15 minutes without requests. The cron pings
  // it every minute when KEEP_AWAKE is "1", so it then never sleeps.
  override sleepAfter = "15m";
  // Class fields run after the base constructor, so `this.env` is set here.
  override envVars = brainEnvVars(this.env);

  /** Starts the container if needed and returns its `GET /health` answer. */
  async health(): Promise<BrainHealth> {
    await this.startAndWaitForPorts({
      ports: BRAIN_PORT,
      cancellationOptions: { portReadyTimeoutMS: BRAIN_START_TIMEOUT_MS },
    });
    const response = await this.containerFetch("http://brain/health", { method: "GET" });
    return { status: response.status, body: await response.text() };
  }

  override onError(err: unknown): unknown {
    console.error(JSON.stringify({ event: "brain_error", error: String(err) }));
    throw err;
  }
}

/** GET /hub/brain: the container's health JSON, or 503 brain_unavailable. */
export async function brainHealth(env: SpineEnv): Promise<Response> {
  if (env.BRAIN === undefined) return error(503, "brain_unavailable");
  try {
    const health = await env.BRAIN.getByName(BRAIN_NAME).health();
    const body = parseJson(health.body);
    if (health.status !== 200 || !isObject(body)) return error(503, "brain_unavailable");
    return json(body);
  } catch (err) {
    console.error(JSON.stringify({ event: "brain_unavailable", error: String(err) }));
    return error(503, "brain_unavailable");
  }
}
