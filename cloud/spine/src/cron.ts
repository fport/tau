/** The minute cron: prune what is in transit, and keep the brain awake in cloud mode. */

import { brainHealth } from "./brain";
import { modeOf, type SpineEnv } from "./env";
import { nowSeconds } from "./http";
import { mailboxOf } from "./mailbox";

export async function runCron(env: SpineEnv): Promise<void> {
  const pruned = await mailboxOf(env).prune(nowSeconds());
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
