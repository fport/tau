/** The minute cron: prune what is in transit, and keep the brain awake in cloud mode. */

import { brainHealth } from "./brain";
import { modeOf, type SpineEnv } from "./env";
import { nowSeconds } from "./http";

export const MAILBOX_RETENTION_SECONDS = 7 * 86_400;
export const SEEN_RETENTION_SECONDS = 86_400;

export async function runCron(env: SpineEnv): Promise<void> {
  const now = nowSeconds();
  const [mailbox, seen] = await env.DB.batch([
    env.DB.prepare("DELETE FROM mailbox WHERE received_at < ?1").bind(
      now - MAILBOX_RETENTION_SECONDS,
    ),
    env.DB.prepare("DELETE FROM seen WHERE ts < ?1").bind(now - SEEN_RETENTION_SECONDS),
  ]);
  const pruned = { mailbox: mailbox?.meta.changes ?? 0, seen: seen?.meta.changes ?? 0 };
  if (pruned.mailbox > 0 || pruned.seen > 0) {
    console.log(JSON.stringify({ event: "pruned", ...pruned }));
  }
  // A ping renews the container's activity timeout; with a ping every minute it never
  // reaches sleepAfter, so the Telegram poller inside keeps running.
  if (modeOf(env) === "cloud" && env.KEEP_AWAKE === "1" && env.BRAIN !== undefined) {
    const response = await brainHealth(env);
    if (response.status !== 200) console.warn(JSON.stringify({ event: "brain_ping_failed" }));
  }
}
