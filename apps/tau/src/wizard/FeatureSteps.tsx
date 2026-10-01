// Step 7: each chosen feature's steps, through `tau setup run <feature> --json`. A step that
// needs the owner (`needs_ui`) is handled here: the guard's enrolment and anything else that
// needs a terminal in the wizard's own terminal, Telegram pairing and the spine deploy through
// their JSON modes, and an action the owner takes in Terminal (issue 173) shown with its
// command to copy, never run.

import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { api, type FeatureStatus, type JobEvent } from "./api";
import type { ExitInfo } from "../chat/api";
import {
  actionCommand,
  emptyPair,
  emptyRun,
  emptySpine,
  needsUiKind,
  pairNeedsToken,
  reducePair,
  reduceRun,
  reduceSpine,
  type CheckEvent,
  type HandAction,
  type NeedsUi,
  type Result,
  type RunState,
  type StepStatus,
  type StepView,
} from "./events";
import {
  afterNeedsUi,
  defaultSteps,
  inputFields,
  inputsFor,
  outcomeOf,
  setupKind,
  setupQueue,
  type Outcome,
} from "./machine";
import { CommandLine, Footer, LinkButton, Output, Problem, checkMark, endedProblem, useJob } from "./parts";
import type { T } from "./strings";
import type { StepProps } from "./Wizard";

const TerminalView = lazy(() => import("../chat/TerminalView"));

export default function FeatureSteps(props: StepProps) {
  const { t, status, state, dispatch, busy } = props;
  if (!status) {
    return (
      <section className="step">
        <h1>{t("setup.title")}</h1>
        <p className="muted">{props.loading ? t("common.loading") : t("common.needs_tau")}</p>
        <Footer
          t={t}
          busy={busy}
          onBack={() => dispatch({ type: "go", step: "permissions" })}
          onSkip={() => dispatch({ type: "skip", step: "setup" })}
        />
      </section>
    );
  }
  const queue = setupQueue(status, state.chosen);
  const failed = Object.values(state.outcomes).some((o) => o === "failed");
  return (
    <section className="step">
      <h1>{t("setup.title")}</h1>
      <p>{queue.length ? t("setup.body") : t("setup.none")}</p>
      {queue.map((feature) => (
        <FeatureCard key={feature.id} props={props} feature={feature} />
      ))}
      <Footer
        t={t}
        busy={busy}
        onBack={() => dispatch({ type: "go", step: "permissions" })}
        onSkip={() => dispatch({ type: "skip", step: "setup" })}
      >
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => dispatch({ type: "complete", step: "setup", mark: failed ? "failed" : "done" })}
        >
          {t("nav.next")}
        </button>
      </Footer>
    </section>
  );
}

function OutcomeBadge({ t, outcome }: { t: T; outcome?: Outcome }) {
  if (!outcome) return null;
  return <em className={`badge ${outcome}`}>{t(`setup.outcome.${outcome}`)}</em>;
}

function FeatureCard({ props, feature }: { props: StepProps; feature: FeatureStatus }) {
  const { t, status, state, dispatch } = props;
  const kind = setupKind(status as NonNullable<typeof status>, feature);
  const outcome = state.outcomes[feature.id];
  const setOutcome = (o: Outcome) => dispatch({ type: "outcome", feature: feature.id, outcome: o });

  useEffect(() => {
    // These have nothing to run.
    if ((kind === "this_app" || kind === "nothing") && !outcome) {
      dispatch({ type: "outcome", feature: feature.id, outcome: "done" });
    }
  }, [kind, outcome, feature.id, dispatch]);

  return (
    <div className="card feature-card">
      <div className="row">
        <h2>{feature.label}</h2>
        <OutcomeBadge t={t} outcome={outcome} />
      </div>
      {kind === "this_app" && <p className="muted small">{t("setup.this_app")}</p>}
      {kind === "nothing" && <p className="muted small">{feature.description}</p>}
      {kind === "app_autostart" && <AutostartCard props={props} done={outcome === "done"} onDone={() => setOutcome("done")} />}
      {kind === "run" && <FeatureRun props={props} feature={feature} outcome={outcome} setOutcome={setOutcome} />}
    </div>
  );
}

/** macOS: the app is the hub's supervisor (the camera works only for a hub it runs), so start
 * at login means "Run the hub" and the app's own login item, not a launchd agent. */
function AutostartCard({ props, done, onDone }: { props: StepProps; done: boolean; onDone: () => void }) {
  const { t } = props;
  const [problem, setProblem] = useState<string | null>(null);
  const turnOn = async () => {
    setProblem(null);
    try {
      const result = await api.setRunHub(true);
      await api.setLaunchAtLogin(true);
      if (result.message) setProblem(result.message);
      onDone();
    } catch (e) {
      setProblem(String(e));
    }
  };
  return (
    <>
      <p className="muted small">{t("features.autostart")}</p>
      {done ? (
        <p className="status ok">● {t("setup.autostart.done")}</p>
      ) : (
        <div className="buttons">
          <button type="button" className="primary" disabled={props.busy} onClick={turnOn}>
            {t("setup.autostart.do")}
          </button>
        </div>
      )}
      <Problem>{problem}</Problem>
    </>
  );
}

/** One feature through `tau setup run`: the steps to run, their inputs, the run's progress and
 * whatever a `needs_ui` step asks of the owner. */
function FeatureRun({
  props,
  feature,
  outcome,
  setOutcome,
}: {
  props: StepProps;
  feature: FeatureStatus;
  outcome?: Outcome;
  setOutcome: (o: Outcome) => void;
}) {
  const { t, state, busy, setBusy } = props;
  const [chosen, setChosen] = useState<string[]>(() => defaultSteps(feature));
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      feature.steps.flatMap((s) => s.inputs).map((i) => [i.name, i.default ?? ""]),
    ),
  );
  const [results, setResults] = useState<Result[]>([]);
  const [skippedUi, setSkippedUi] = useState(false);
  const job = useJob(reduceRun, emptyRun, setBusy);
  const fields = useMemo(() => inputFields(feature, chosen), [feature, chosen]);

  const runSteps = async (
    steps: string[],
    allResults: Result[],
    skipped: boolean,
    /** After a step that needed the owner: the steps shown so far stay, that one marked. */
    carry?: (last: RunState) => RunState,
  ) => {
    const inputs = inputsFor(feature, steps, values);
    // Secrets leave the page with the call; the fields empty at once.
    const secrets = new Set(fields.filter((f) => f.secret).map((f) => f.name));
    if (secrets.size) setValues((v) => Object.fromEntries(Object.entries(v).map(([k, x]) => [k, secrets.has(k) ? "" : x])));
    const { state: run } = await job.start(
      (onEvent) =>
        api.run({ kind: "run", target: feature.id }, { steps, inputs }, state.lang, onEvent),
      carry,
    );
    const merged = [...allResults, ...(run.done?.results ?? [])].filter((r) => r.status !== "needs_ui");
    setResults(merged);
    if (run.needsUi) return; // the owner's turn
    if (run.error || !run.done) {
      setOutcome("failed");
      return;
    }
    setOutcome(outcomeOf(merged, skipped));
  };

  const start = () => {
    setResults([]);
    setSkippedUi(false);
    runSteps(chosen, [], false);
  };

  const continueAfter = (decision: "done" | "skip") => {
    const needsUi = job.state.needsUi;
    const pending = job.state.done?.pending ?? [];
    if (!needsUi) return;
    const skipped = skippedUi || decision === "skip";
    setSkippedUi(skipped);
    // A step the app ran is done; one the owner skipped is skipped; an action in Terminal is
    // checked again by the next run.
    const status: StepStatus =
      decision === "skip" ? "skipped" : needsUiKind(needsUi) === "action" ? "checking" : "done";
    const carry = (last: RunState): RunState => ({
      ...last,
      needsUi: null,
      done: null,
      error: null,
      steps: last.steps.map((s) => (s.id === needsUi.step ? { ...s, status } : s)),
    });
    // With nothing after it, `steps: []` runs nothing and asks tau for the feature's state.
    runSteps(afterNeedsUi(pending, needsUi.step, decision), results, skipped, carry);
  };

  const run = job.state;
  const error = job.failure ?? run.error?.message ?? null;
  const started = run.steps.length > 0 || job.running || Boolean(error) || outcome !== undefined;

  return (
    <>
      <p className="muted small">{feature.description}</p>
      {!started && (
        <>
          <ul className="step-picks">
            {feature.steps.map((step) => (
              <li key={step.id}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={chosen.includes(step.id)}
                    disabled={busy}
                    onChange={(e) => {
                      const on = e.currentTarget.checked;
                      setChosen((c) =>
                        feature.steps
                          .map((s) => s.id)
                          .filter((id) => (id === step.id ? on : c.includes(id))),
                      );
                    }}
                  />
                  <span>
                    {step.label}
                    {step.optional && <em className="optional"> · {t("setup.optional")}</em>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {fields.map((input) => (
            <label key={input.name} className="field">
              <span>{input.label}</span>
              <input
                type={input.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                value={values[input.name] ?? ""}
                disabled={busy}
                onChange={(e) => {
                  const value = e.currentTarget.value;
                  setValues((v) => ({ ...v, [input.name]: value }));
                }}
              />
            </label>
          ))}
        </>
      )}

      {run.steps.length > 0 && <StepList t={t} steps={run.steps} />}
      {run.needsUi && !job.running && (
        <NeedsUiPanel
          key={`${run.needsUi.feature}:${run.needsUi.step}:${results.length}`}
          props={props}
          needsUi={run.needsUi}
          onContinue={continueAfter}
        />
      )}
      <Problem>{!job.running && (error ?? endedProblem(t, job.ended))}</Problem>
      <Output t={t} lines={run.logs} open={Boolean(error)} />

      <div className="buttons">
        {!started && (
          <>
            <button type="button" className="primary" disabled={busy} onClick={start}>
              {t("setup.run")}
            </button>
            <button type="button" disabled={busy} onClick={() => setOutcome("skipped")}>
              {t("setup.skip_feature")}
            </button>
          </>
        )}
        {started && !job.running && !run.needsUi && (
          <button type="button" disabled={busy} onClick={start}>
            {t("setup.run_again")}
          </button>
        )}
      </div>
    </>
  );
}

function StepList({ t, steps }: { t: T; steps: StepView[] }) {
  return (
    <ul className="run-steps">
      {steps.map((step) => (
        <li key={step.id} className={step.status}>
          <div className="run-step">
            <span className="step-label">{step.label}</span>
            <em className={`badge ${step.status}`}>{t(`setup.status.${step.status}`)}</em>
          </div>
          {step.detail && <p className="muted small">{step.detail}</p>}
          {step.text && <p className="small note-text">{step.text}</p>}
          {step.url && (
            <div className="buttons">
              <LinkButton url={step.url}>{t("common.open")}</LinkButton>
            </div>
          )}
          {step.check && <CheckView t={t} check={step.check} phone={step.id === "phone"} />}
        </li>
      ))}
    </ul>
  );
}

/** A `check` event (issue 173): its checklist, and for the phone step its values as a
 * Termius card. Other steps' values are for the engine, not for showing. */
export function CheckView({ t, check, phone }: { t: T; check: CheckEvent; phone: boolean }) {
  return (
    <div className="check-block">
      {check.summary && <p className={`small ${check.ok ? "status ok" : ""}`}>{check.summary}</p>}
      {check.checks.length > 0 && (
        <ul className="checks">
          {check.checks
            // The phone's values are on the card below, once.
            .filter((c) => !(phone && (PHONE_KEYS as readonly string[]).includes(c.id ?? "")))
            .map((c, i) => (
            <li key={i} className={c.status}>
              <span className="check-mark">{checkMark(c.status)}</span>
              <span>
                {(c.label ?? c.name ?? c.id) && <strong>{String(c.label ?? c.name ?? c.id)} </strong>}
                {c.detail && String(c.detail)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {phone && <PhoneCard t={t} values={check.values ?? {}} />}
    </div>
  );
}

/** What Termius needs, in its order. */
export const PHONE_KEYS = ["host", "ip", "user", "port", "mosh", "startup", "keys"] as const;

export function showValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "✓" : "–";
  if (Array.isArray(value)) return value.map(showValue).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The phone step's values (host, IP, user, port, mosh, startup, keys) as a Termius card. */
function PhoneCard({ t, values }: { t: T; values: Record<string, unknown> }) {
  const rows = PHONE_KEYS.filter((k) => values[k] !== null && values[k] !== undefined && values[k] !== "");
  if (!rows.length) return null;
  return (
    <div className="values phone">
      <h3>{t("setup.phone.title")}</h3>
      <dl className="facts">
        {rows.map((key) => (
          <div key={key} className="fact">
            <dt>{t(`setup.phone.${key}`)}</dt>
            <dd>
              <code>{showValue(values[key])}</code>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function NeedsUiPanel({
  props,
  needsUi,
  onContinue,
}: {
  props: StepProps;
  needsUi: NeedsUi;
  onContinue: (decision: "done" | "skip") => void;
}) {
  const kind = needsUiKind(needsUi);
  switch (kind) {
    case "action":
      return <ActionCard props={props} needsUi={needsUi} action={needsUi.action as HandAction} onContinue={onContinue} />;
    case "telegram":
      return <TelegramPair props={props} onContinue={onContinue} />;
    case "spine":
      return <SpineDeploy props={props} dir={needsUi.command[3]} onContinue={onContinue} />;
    case "guard":
    case "terminal":
      return <TerminalStep props={props} needsUi={needsUi} guard={kind === "guard"} onContinue={onContinue} />;
  }
}

/** Issue 173: something the owner does in Terminal (a `sudo` command, say). Shown with its
 * command to copy; the app never runs it. "Done" checks again, "Skip" goes past it. */
function ActionCard({
  props,
  needsUi,
  action,
  onContinue,
}: {
  props: StepProps;
  needsUi: NeedsUi;
  action: HandAction;
  onContinue: (decision: "done" | "skip") => void;
}) {
  const { t, busy } = props;
  const command = actionCommand(action);
  return (
    <div className="needs-ui action">
      <h3>{needsUi.label}</h3>
      {needsUi.summary && <p className="small muted">{needsUi.summary}</p>}
      {action.text && <p className="note-text">{action.text}</p>}
      {command && (
        <>
          {/* tau's own text says where to run it; without one, the wizard does. */}
          {!action.text && <p className="small">{t("setup.action.run")}</p>}
          <CommandLine t={t} command={command} />
        </>
      )}
      {action.sudo && <p className="small muted">{t("setup.action.sudo")}</p>}
      {action.changes && action.changes.length > 0 && (
        <>
          <p className="small">{t("setup.action.changes")}</p>
          <ul className="small plain-list">
            {action.changes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}
      {action.script && (
        <p className="small">
          {t("setup.action.script")} <code>{action.script}</code>
        </p>
      )}
      <div className="buttons">
        {action.url && <LinkButton url={action.url}>{t("common.open")}</LinkButton>}
        <button type="button" className="primary" disabled={busy} onClick={() => onContinue("done")}>
          {t("setup.done_check")}
        </button>
        <button type="button" disabled={busy} onClick={() => onContinue("skip")}>
          {t("setup.skip_step")}
        </button>
      </div>
    </div>
  );
}

/** A step that needs a terminal (the guard's enrolment): `tau <command>` in the wizard's own
 * PTY. The app is its parent, so the camera prompt and grant are the app's. */
function TerminalStep({
  props,
  needsUi,
  guard,
  onContinue,
}: {
  props: StepProps;
  needsUi: NeedsUi;
  guard: boolean;
  onContinue: (decision: "done" | "skip") => void;
}) {
  const { t, state, setBusy } = props;
  const [attempt, setAttempt] = useState(0);
  const [exit, setExit] = useState<ExitInfo | null>(null);
  const running = attempt > 0 && !exit;

  useEffect(() => {
    setBusy(running);
    return () => setBusy(false);
  }, [running, setBusy]);

  const pty = useMemo(
    () => ({
      start: (
        cols: number,
        rows: number,
        onOutput: (bytes: Uint8Array) => void,
        onExit: (info: ExitInfo) => void,
      ) => api.ptyStart(needsUi.command, state.lang, cols, rows, onOutput, onExit),
      write: api.ptyWrite,
      resize: api.ptyResize,
    }),
    [needsUi.command, state.lang],
  );

  return (
    <div className="needs-ui terminal-step">
      <h3>{needsUi.label}</h3>
      <p className="small">{guard ? t("setup.guard.intro") : t("setup.terminal.intro")}</p>
      <CommandLine t={t} command={`tau ${needsUi.command.join(" ")}`} />
      {attempt > 0 && (
        <Suspense fallback={<p className="muted small">{t("common.loading")}</p>}>
          <TerminalView
            key={attempt}
            pty={pty}
            once
            className="wizard-terminal"
            exitNotice={(info) =>
              info.success ? t("setup.terminal.finished") : t("setup.terminal.failed", { code: info.code ?? info.signal ?? "?" })
            }
            onExit={setExit}
          />
        </Suspense>
      )}
      <div className="buttons">
        {attempt === 0 && (
          <button type="button" className="primary" onClick={() => setAttempt(1)}>
            {t("setup.terminal.start")}
          </button>
        )}
        {exit?.success && (
          <button type="button" className="primary" onClick={() => onContinue("done")}>
            {t("setup.continue")}
          </button>
        )}
        {exit && !exit.success && (
          <button
            type="button"
            className="primary"
            onClick={() => {
              setExit(null);
              setAttempt((n) => n + 1);
            }}
          >
            {t("nav.retry")}
          </button>
        )}
        {!running && (
          <button type="button" onClick={() => onContinue("skip")}>
            {t("setup.skip_step")}
          </button>
        )}
      </div>
    </div>
  );
}

/** Telegram (issue 172): the bot token at a hidden field, then the one-time code and its link,
 * and the wait for the owner's /start. */
function TelegramPair({
  props,
  onContinue,
}: {
  props: StepProps;
  onContinue: (decision: "done" | "skip") => void;
}) {
  const { t, state, busy, setBusy } = props;
  const [token, setToken] = useState("");
  const job = useJob(reducePair, emptyPair, setBusy);
  const pair = job.state;

  const go = async () => {
    const input = { token: token.trim() || null };
    // The token leaves the page with this call; the field empties at once.
    setToken("");
    await job.start((onEvent: (event: JobEvent) => void) =>
      api.run({ kind: "telegram_pair" }, input, state.lang, onEvent),
    );
  };

  const askToken = !job.running && !pair.paired && (!pair.code || pairNeedsToken(pair) || Boolean(pair.error));
  return (
    <div className="needs-ui telegram">
      <p className="small">{t("telegram.intro")}</p>
      {pair.notes.map((n, i) => (
        <p key={i} className="muted small">
          {n}
        </p>
      ))}
      {pair.bot && <p className="status ok">● {t("telegram.bot", { bot: pair.bot })}</p>}
      {pair.code && !pair.paired && !pair.error && (
        <div className="pair-code">
          <p className="small">{t("telegram.code")}</p>
          <p className="code-big">/start {pair.code.code}</p>
          <div className="buttons">
            {pair.code.link && (
              <LinkButton url={pair.code.link} primary>
                {t("telegram.open")}
              </LinkButton>
            )}
          </div>
          {pair.waiting && <p className="muted small waiting">{t("telegram.waiting")}</p>}
        </div>
      )}
      {pair.paired && <p className="status ok">● {t("telegram.paired", { name: pair.paired.name })}</p>}
      <Problem>{pair.error?.message ?? job.failure}</Problem>
      {askToken && (
        <>
          <div className="field-row">
            <label className="field">
              <span>{t("telegram.token")}</span>
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={token}
                disabled={busy}
                onChange={(e) => setToken(e.currentTarget.value)}
              />
            </label>
            <LinkButton url="https://t.me/BotFather">{t("telegram.botfather")}</LinkButton>
          </div>
          <p className="muted small">{t("telegram.keep")}</p>
        </>
      )}
      <div className="buttons">
        {askToken && (
          <button type="button" className="primary" disabled={busy} onClick={go}>
            {t("telegram.pair")}
          </button>
        )}
        {pair.paired && (
          <button type="button" className="primary" onClick={() => onContinue("done")}>
            {t("setup.continue")}
          </button>
        )}
        {!job.running && !pair.paired && (
          <button type="button" onClick={() => onContinue("skip")}>
            {t("setup.skip_step")}
          </button>
        )}
      </div>
    </div>
  );
}

/** The spine (issue 174): the deploy through Cloudflare's API, asking for the token through
 * the pre-filled link and for the account when there are several. */
function SpineDeploy({
  props,
  dir,
  onContinue,
}: {
  props: StepProps;
  dir: string;
  onContinue: (decision: "done" | "skip") => void;
}) {
  const { t, state, busy, setBusy } = props;
  const [token, setToken] = useState("");
  const [account, setAccount] = useState("");
  const job = useJob(reduceSpine, emptySpine, setBusy);
  const spine = job.state;

  const deploy = async (input: { token?: string; account_id?: string }) => {
    setToken("");
    await job.start((onEvent) =>
      api.run({ kind: "spine_deploy", dir }, input, state.lang, onEvent),
    );
  };

  const waitingForToken = !job.running && spine.needToken && !spine.done;
  const choosing = !job.running && spine.accounts && spine.accounts.length > 0 && !spine.done;
  return (
    <div className="needs-ui spine">
      <p className="small">{t("spine.intro")}</p>
      <code className="small">{dir}</code>
      {spine.progress.length > 0 && (
        <ul className="small plain-list progress-lines">
          {spine.progress.slice(-8).map((p, i) => (
            <li key={i}>{p.text}</li>
          ))}
        </ul>
      )}
      {waitingForToken && spine.needToken && (
        <div className="card">
          <p className="small">{t("spine.need_token")}</p>
          {spine.needToken.permissions.length > 0 && (
            <ul className="small plain-list">
              {spine.needToken.permissions.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <div className="buttons">
            <LinkButton url={spine.needToken.link} primary>
              {t("spine.open")}
            </LinkButton>
          </div>
          <label className="field">
            <span>{t("spine.token")}</span>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(e) => setToken(e.currentTarget.value)}
            />
          </label>
        </div>
      )}
      {choosing && spine.accounts && (
        <div className="choices" role="radiogroup" aria-label={t("spine.account")}>
          <p className="small">{spine.message ?? t("spine.account")}</p>
          {spine.accounts.map((a) => (
            <label key={a.id} className={`choice${account === a.id ? " active" : ""}`}>
              <input type="radio" name="account" checked={account === a.id} onChange={() => setAccount(a.id)} />
              <span>
                <strong>{a.name}</strong>
              </span>
            </label>
          ))}
        </div>
      )}
      {spine.done && (
        <>
          <p className="status ok">● {t("spine.done", { url: spine.done.url })}</p>
          {!spine.done.healthy && <p className="muted small">{t("spine.unhealthy")}</p>}
        </>
      )}
      <Problem>{!job.running && (spine.error ?? job.failure ?? (spine.needToken || spine.accounts ? null : endedProblem(t, job.ended)))}</Problem>
      <div className="buttons">
        {!job.running && !spine.done && !waitingForToken && !choosing && (
          <button type="button" className="primary" disabled={busy} onClick={() => deploy({})}>
            {spine.error ? t("nav.retry") : t("spine.deploy")}
          </button>
        )}
        {waitingForToken && (
          <button type="button" className="primary" disabled={!token.trim()} onClick={() => deploy({ token: token.trim() })}>
            {t("nav.continue")}
          </button>
        )}
        {choosing && (
          <button type="button" className="primary" disabled={!account} onClick={() => deploy({ account_id: account })}>
            {t("nav.continue")}
          </button>
        )}
        {spine.done && (
          <button type="button" className="primary" onClick={() => onContinue("done")}>
            {t("setup.continue")}
          </button>
        )}
        {!job.running && !spine.done && (
          <button type="button" onClick={() => onContinue("skip")}>
            {t("setup.skip_step")}
          </button>
        )}
      </div>
    </div>
  );
}
