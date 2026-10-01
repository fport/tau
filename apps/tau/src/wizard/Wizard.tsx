import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import mark from "../../../../docs/brand/tau-mark.svg";
import {
  api,
  type Access,
  type Discovery,
  type Lang,
  type PermissionId,
  type SetupStatus,
  type StatusProblem,
} from "./api";
import { emptyRun, reduceRun } from "./events";
import FeatureSteps from "./FeatureSteps";
import {
  STEPS,
  type Action,
  type StepId,
  type WizardState,
  APP_FEATURE,
  AUTOSTART_FEATURE,
  defaultChoice,
  featureRows,
  initialState,
  permissionsFor,
  previousStep,
  reducer,
  summaryState,
  toInstall,
  toggle,
} from "./machine";
import { Footer, LinkButton, Output, Problem, checkMark, endedProblem, useJob } from "./parts";
import { guessLang, strings, type T } from "./strings";
import "../styles.css";
import "./wizard.css";

/** What every step gets. */
export interface StepProps {
  t: T;
  state: WizardState;
  dispatch: (action: Action) => void;
  discovery: Discovery | null;
  discovering: boolean;
  status: SetupStatus | null;
  problem: StatusProblem | null;
  loading: boolean;
  firstRun: boolean;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  rediscover: () => Promise<Discovery | null>;
  reload: () => Promise<SetupStatus | null>;
}

function asProblem(e: unknown): StatusProblem {
  if (e && typeof e === "object" && "code" in e && "message" in e) return e as StatusProblem;
  return { code: "failed", message: String(e) };
}

// The first-launch wizard (roadmap 171): steps on the left, the current one on the right.
export default function Wizard() {
  const [state, dispatch] = useReducer(reducer, null, () =>
    initialState(guessLang(navigator.languages ?? [navigator.language])),
  );
  const t = useMemo(() => strings(state.lang), [state.lang]);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [discovering, setDiscovering] = useState(true);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [problem, setProblem] = useState<StatusProblem | null>(null);
  const [loading, setLoading] = useState(false);
  const [firstRun, setFirstRun] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const lang = useRef(state.lang);
  lang.current = state.lang;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.status(lang.current);
      setStatus(next);
      setProblem(null);
      setFirstRun((known) => known ?? !next.config);
      return next;
    } catch (e) {
      setStatus(null);
      setProblem(asProblem(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const rediscover = useCallback(async () => {
    setDiscovering(true);
    try {
      const found = await api.discover();
      setDiscovery(found);
      if (!found.tau) {
        setStatus(null);
        setProblem({ code: "no_tau", message: "" });
      }
      return found;
    } catch (e) {
      setProblem({ code: "failed", message: String(e) });
      return null;
    } finally {
      setDiscovering(false);
    }
  }, []);

  useEffect(() => {
    rediscover();
  }, [rediscover]);

  // The labels come from tau in the chosen language: ask again when it changes.
  useEffect(() => {
    if (discovery?.tau) reload();
  }, [discovery, state.lang, reload]);

  // The ⌘A of the fields (the app menu has no Select All; ⌘A belongs to xterm.js elsewhere).
  useEffect(() => {
    const selectAll = (event: KeyboardEvent) => {
      if (!event.metaKey || event.key.toLowerCase() !== "a") return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
        event.preventDefault();
        target.select();
      }
    };
    window.addEventListener("keydown", selectAll);
    return () => window.removeEventListener("keydown", selectAll);
  }, []);

  useEffect(() => {
    document.documentElement.lang = state.lang;
    document.title = t("app.title");
  }, [state.lang, t]);

  const props: StepProps = {
    t,
    state,
    dispatch,
    discovery,
    discovering,
    status,
    problem,
    loading,
    firstRun: firstRun ?? false,
    busy,
    setBusy,
    rediscover,
    reload,
  };

  return (
    <div className="wizard">
      <aside className="rail">
        <div className="brand">
          <img src={mark} alt="" />
          <div>
            <strong>{t("app.title")}</strong>
            <span>{t("app.subtitle")}</span>
          </div>
        </div>
        <ol className="steps">
          {STEPS.map((step, index) => {
            const m = state.marks[step];
            const sign = m === "done" ? "✓" : m === "skipped" ? "–" : m === "failed" ? "!" : index + 1;
            return (
              <li key={step}>
                <button
                  type="button"
                  className={`${step === state.current ? "current" : ""} ${m}`}
                  disabled={busy}
                  aria-current={step === state.current ? "step" : undefined}
                  onClick={() => dispatch({ type: "go", step })}
                >
                  <span className="sign">{sign}</span>
                  <span className="name">{t(`step.${step}`)}</span>
                  {m !== "todo" && <span className="mark-label">{t(`mark.${m}`)}</span>}
                </button>
              </li>
            );
          })}
        </ol>
        {busy && <p className="muted small rail-busy">{t("nav.busy")}</p>}
      </aside>
      <main className="pane">
        <StepView step={state.current} {...props} />
      </main>
    </div>
  );
}

function StepView({ step, ...props }: StepProps & { step: StepId }) {
  switch (step) {
    case "language":
      return <LanguageStep {...props} />;
    case "install":
      return <InstallStep {...props} />;
    case "key":
      return <KeyStep {...props} />;
    case "about":
      return <AboutStep {...props} />;
    case "features":
      return <FeaturesStep {...props} />;
    case "permissions":
      return <PermissionsStep {...props} />;
    case "setup":
      return <FeatureSteps {...props} />;
    case "summary":
      return <SummaryStep {...props} />;
  }
}

function back(props: StepProps, step: StepId) {
  return () => props.dispatch({ type: "go", step: previousStep(step) });
}

function skip(props: StepProps, step: StepId) {
  return () => props.dispatch({ type: "skip", step });
}

/** The step needs tau, which is not there (yet). */
function NeedsTau({ props, step }: { props: StepProps; step: StepId }) {
  const { t, loading, discovering } = props;
  return (
    <>
      <p className="muted">{loading || discovering ? t("common.loading") : t("common.needs_tau")}</p>
      <Footer t={t} busy={props.busy} onBack={back(props, step)} onSkip={skip(props, step)} />
    </>
  );
}

// -- 1. language ---------------------------------------------------------------------------

function LanguageStep(props: StepProps) {
  const { t, state, dispatch } = props;
  return (
    <section className="step">
      <h1>{t("language.title")}</h1>
      <p>{t("language.body")}</p>
      <div className="choices" role="radiogroup" aria-label={t("step.language")}>
        {(["en", "tr"] as Lang[]).map((lang) => (
          <label key={lang} className={`choice${state.lang === lang ? " active" : ""}`}>
            <input
              type="radio"
              name="lang"
              checked={state.lang === lang}
              onChange={() => dispatch({ type: "lang", lang })}
            />
            <span>
              <strong>{t(`language.${lang}`)}</strong>
            </span>
          </label>
        ))}
      </div>
      <Footer t={t} busy={props.busy}>
        <button
          type="button"
          className="primary"
          onClick={() => dispatch({ type: "complete", step: "language" })}
        >
          {t("nav.next")}
        </button>
      </Footer>
    </section>
  );
}

// -- 2. install tau ------------------------------------------------------------------------

function InstallStep(props: StepProps) {
  const { t, discovery, discovering, problem, dispatch, busy, setBusy, rediscover } = props;
  const job = useJob(reduceRun, emptyRun, setBusy);

  const install = async (what: "uv" | "tau" | "upgrade") => {
    const { ended } = await job.start((onEvent) => api.install(what, onEvent));
    const found = await rediscover();
    if (what === "uv" && ended?.code === 0 && found?.uv && !found.tau) {
      // uv is there now: go straight on with tau.
      await job.start((onEvent) => api.install("tau", onEvent), (last) => ({ ...last, done: null, error: null }));
      await rediscover();
    }
  };

  const tau = discovery?.tau;
  const tooOld = tau && problem?.code === "too_old";
  const failedStatus = tau && problem?.code === "failed";
  const jobProblem = job.failure ?? job.state.error?.message ?? endedProblem(t, job.ended);

  return (
    <section className="step">
      <h1>{t("install.title")}</h1>
      {discovering && !tau && <p className="muted">{t("install.looking")}</p>}

      {tau && (
        <div className="card">
          <p className="status ok">● {t("install.found", { version: tau.version })}</p>
          <dl className="facts">
            <dt>{t("install.python")}</dt>
            <dd>
              <code>{tau.python}</code>
            </dd>
            <dt>{t("install.home")}</dt>
            <dd>
              <code>{tau.home}</code>
            </dd>
            <dt>{t("install.via")}</dt>
            <dd>{t(`install.kind.${tau.kind}`)}</dd>
          </dl>
          {(discovery?.saved_hub || discovery?.saved_chat) && (
            <p className="muted small">{t("install.saved")}</p>
          )}
        </div>
      )}

      {tooOld && (
        <div className="card attention">
          <p>{t("install.too_old", { version: tau.version })}</p>
          {tau.uv_tool && discovery?.uv ? (
            <div className="buttons">
              <button type="button" className="primary" disabled={busy} onClick={() => install("upgrade")}>
                {t("install.upgrade")}
              </button>
            </div>
          ) : (
            <p className="muted small">{t("install.upgrade_checkout")}</p>
          )}
        </div>
      )}
      {failedStatus && (
        <Problem>
          {t("install.status_failed")} {problem?.message}
        </Problem>
      )}

      {!tau && !discovering && discovery?.uv && (
        <div className="card">
          <p>{t("install.missing")}</p>
          {discovery.install_version && (
            <p className="muted small">{t("install.version", { version: discovery.install_version })}</p>
          )}
          <div className="buttons">
            <button type="button" className="primary" disabled={busy} onClick={() => install("tau")}>
              {t("install.tau")}
            </button>
          </div>
        </div>
      )}

      {!tau && !discovering && discovery && !discovery.uv && (
        <div className="card">
          <p>{t("install.no_uv", { url: "https://astral.sh/uv/install.sh" })}</p>
          <div className="buttons">
            <button type="button" className="primary" disabled={busy} onClick={() => install("uv")}>
              {t("install.uv")}
            </button>
            <LinkButton url="https://docs.astral.sh/uv/">{t("install.uv_docs")}</LinkButton>
          </div>
        </div>
      )}

      {job.running && <p className="muted">{t("install.running")}</p>}
      {job.state.phase === "install" && job.state.logs.length === 0 && job.running && (
        <p className="muted small">uv tool install …</p>
      )}
      <Problem>{!job.running && jobProblem}</Problem>
      <Output t={t} lines={job.state.logs} open={job.running || Boolean(jobProblem)} />

      {discovery && discovery.rejected.length > 0 && (
        <details>
          <summary>{t("install.rejected")}</summary>
          <ul className="small muted plain">
            {discovery.rejected.map((r) => (
              <li key={r.python}>
                <code>{r.python}</code>: {r.problem}
              </li>
            ))}
          </ul>
        </details>
      )}

      <Footer t={t} busy={busy} onBack={back(props, "install")} onSkip={skip(props, "install")}>
        {!tau && !discovering && (
          <button type="button" disabled={busy} onClick={() => rediscover()}>
            {t("install.recheck")}
          </button>
        )}
        <button
          type="button"
          className="primary"
          disabled={busy || !tau || Boolean(tooOld)}
          onClick={() => dispatch({ type: "complete", step: "install" })}
        >
          {t("nav.next")}
        </button>
      </Footer>
    </section>
  );
}

// -- 3. model key --------------------------------------------------------------------------

const PROVIDERS = ["anthropic", "openai", "gemini", "bedrock", "fake"] as const;
type Provider = (typeof PROVIDERS)[number];
const KEY_PROVIDERS: Provider[] = ["anthropic", "openai", "gemini"];
const KEY_PAGES: Partial<Record<Provider, string>> = {
  anthropic: "https://console.anthropic.com/settings/keys",
  openai: "https://platform.openai.com/api-keys",
  gemini: "https://aistudio.google.com/apikey",
};

function KeyStep(props: StepProps) {
  const { t, status, state, dispatch, busy, setBusy, reload } = props;
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [key, setKey] = useState("");
  const job = useJob(reduceRun, emptyRun, setBusy);
  if (!status) return <NeedsTau props={props} step="key" />;

  const needsKey = KEY_PROVIDERS.includes(provider);
  const save = async () => {
    const inputs: Record<string, string> = { language: state.lang, provider };
    if (needsKey) inputs.key = key.trim();
    // The key leaves the page with this call and is not kept: the field empties at once.
    setKey("");
    const { state: run, ended } = await job.start((onEvent) =>
      api.run({ kind: "run", target: "init" }, { inputs }, state.lang, onEvent),
    );
    if (ended?.code === 0 && run.done?.ok) {
      await reload();
      dispatch({ type: "complete", step: "key" });
    }
  };

  const error = job.failure ?? job.state.error?.message ?? null;
  const failedStep = job.state.steps.find((s) => s.status === "failed");

  return (
    <section className="step">
      <h1>{t("key.title")}</h1>
      {status.config ? (
        <p>{t("key.configured", { home: status.home })}</p>
      ) : (
        <>
          <p>{t("key.body", { home: status.home })}</p>
          <div className="choices" role="radiogroup" aria-label={t("key.provider")}>
            {PROVIDERS.map((p) => (
              <label key={p} className={`choice${provider === p ? " active" : ""}`}>
                <input
                  type="radio"
                  name="provider"
                  checked={provider === p}
                  disabled={busy}
                  onChange={() => setProvider(p)}
                />
                <span>
                  <strong>{t(`key.provider.${p}`)}</strong>
                </span>
              </label>
            ))}
          </div>
          {needsKey && (
            <div className="field-row">
              <label className="field">
                <span>{t("key.key")}</span>
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  disabled={busy}
                  onChange={(e) => setKey(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && key.trim()) save();
                  }}
                />
              </label>
              {KEY_PAGES[provider] && (
                <LinkButton url={KEY_PAGES[provider] as string}>{t("key.get")}</LinkButton>
              )}
            </div>
          )}
          {provider === "bedrock" && <p className="muted small">{t("key.bedrock")}</p>}
          {provider === "fake" && <p className="muted small">{t("key.fake")}</p>}
          {job.running && <p className="muted">{t("key.saving")}</p>}
          <Problem>{error ?? failedStep?.detail}</Problem>
          <Output t={t} lines={job.state.logs} open={Boolean(failedStep)} />
        </>
      )}
      <Footer t={t} busy={busy} onBack={back(props, "key")} onSkip={skip(props, "key")}>
        {status.config ? (
          <button
            type="button"
            className="primary"
            onClick={() => dispatch({ type: "complete", step: "key" })}
          >
            {t("nav.next")}
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={busy || (needsKey && !key.trim())}
            onClick={save}
          >
            {t("key.save")}
          </button>
        )}
      </Footer>
    </section>
  );
}

// -- 4. about you --------------------------------------------------------------------------

function AboutStep(props: StepProps) {
  const { t, status, state, dispatch, busy, setBusy, reload } = props;
  const [values, setValues] = useState({ name: "", address: "", languages: "" });
  const job = useJob(reduceRun, emptyRun, setBusy);
  if (!status) return <NeedsTau props={props} step="about" />;

  const save = async () => {
    const { ended } = await job.start((onEvent) =>
      api.run({ kind: "run", target: "about" }, { inputs: values }, state.lang, onEvent),
    );
    if (ended?.code === 0) {
      await reload();
      dispatch({ type: "complete", step: "about" });
    }
  };
  const error = job.failure ?? job.state.error?.message ?? null;
  const field = (name: keyof typeof values, label: string) => (
    <label className="field">
      <span>{label}</span>
      <input
        type="text"
        value={values[name]}
        disabled={busy}
        onChange={(e) => {
          const value = e.currentTarget.value;
          setValues((v) => ({ ...v, [name]: value }));
        }}
      />
    </label>
  );

  return (
    <section className="step">
      <h1>{t("about.title")}</h1>
      {status.about ? (
        <p>{t("about.configured")}</p>
      ) : (
        <>
          <p>{t("about.body")}</p>
          {field("name", t("about.name"))}
          {field("address", t("about.address"))}
          {field("languages", t("about.languages"))}
          <Problem>{error}</Problem>
        </>
      )}
      <Footer t={t} busy={busy} onBack={back(props, "about")} onSkip={skip(props, "about")}>
        {status.about ? (
          <button
            type="button"
            className="primary"
            onClick={() => dispatch({ type: "complete", step: "about" })}
          >
            {t("nav.next")}
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={busy || !values.name.trim()}
            onClick={save}
          >
            {t("about.save")}
          </button>
        )}
      </Footer>
    </section>
  );
}

// -- 5. features ---------------------------------------------------------------------------

function FeaturesStep(props: StepProps) {
  const { t, status, state, dispatch, busy, setBusy, reload, firstRun } = props;
  const job = useJob(reduceRun, emptyRun, setBusy);

  useEffect(() => {
    if (status && !state.choiceMade) {
      dispatch({ type: "choose", chosen: defaultChoice(status, firstRun) });
    }
  }, [status, state.choiceMade, firstRun, dispatch]);

  if (!status) return <NeedsTau props={props} step="features" />;

  const rows = featureRows(status, state.chosen);
  const installing = toInstall(status, state.chosen);
  const checkout = !status.install.can_install && installing.length > 0;

  const go = async () => {
    if (!installing.length || checkout) {
      dispatch({ type: "complete", step: "features", mark: checkout ? "failed" : "done" });
      return;
    }
    const { ended, state: run } = await job.start((onEvent) =>
      api.run({ kind: "install", features: installing }, null, state.lang, onEvent),
    );
    await reload();
    if (ended?.code === 0 && run.done?.ok) {
      dispatch({ type: "complete", step: "features" });
    }
  };

  const error = job.failure ?? job.state.error?.message ?? endedProblem(t, job.ended);
  const basic = rows.filter((r) => !r.advanced);
  const advanced = rows.filter((r) => r.advanced);
  const renderRow = (row: (typeof rows)[number]) => {
    const extra =
      row.id === APP_FEATURE
        ? t("features.this_app")
        : row.id === AUTOSTART_FEATURE && status.platform === "darwin"
          ? t("features.autostart")
          : null;
    const stateLabel = t(`features.state.${row.state}`);
    return (
      <label
        key={row.id}
        className={`choice feature${row.checked ? " active" : ""}${row.locked ? " disabled" : ""}`}
      >
        <input
          type="checkbox"
          checked={row.checked}
          disabled={row.locked || busy}
          onChange={() => dispatch({ type: "choose", chosen: toggle(status, state.chosen, row.id) })}
        />
        <span>
          <strong>
            {row.label}
            {stateLabel && <em className={`badge ${row.state}`}>{stateLabel}</em>}
          </strong>
          <small>{row.description}</small>
          {extra && <small>{extra}</small>}
          {row.unavailableReason && <small className="reason">{row.unavailableReason}</small>}
          {row.permissions.length > 0 && (
            <small>{t("features.needs", { permissions: row.permissions.join(", ") })}</small>
          )}
          {row.requires.length > 0 && (
            <small>{t("features.requires", { features: row.requires.join(", ") })}</small>
          )}
        </span>
      </label>
    );
  };

  return (
    <section className="step">
      <h1>{t("features.title")}</h1>
      <p>{t("features.body")}</p>
      {props.loading && <p className="muted small">{t("common.loading")}</p>}
      <div className="choices">{basic.map(renderRow)}</div>
      {advanced.length > 0 && (
        <>
          <h2>{t("features.advanced")}</h2>
          <div className="choices">{advanced.map(renderRow)}</div>
        </>
      )}
      {checkout && <p className="banner">{t("features.checkout")}</p>}
      {job.running && <p className="muted">{t("features.installing")}</p>}
      {job.state.done?.installed && job.state.done.installed.length > 0 && (
        <p className="status ok">
          ● {t("features.installed", { packages: job.state.done.installed.join(", ") })}
        </p>
      )}
      <Problem>{!job.running && error}</Problem>
      <Output t={t} lines={job.state.logs} open={job.running || Boolean(error)} />
      <Footer t={t} busy={busy} onBack={back(props, "features")} onSkip={skip(props, "features")}>
        {error && !job.running && (
          <button
            type="button"
            onClick={() => dispatch({ type: "complete", step: "features", mark: "failed" })}
          >
            {t("nav.continue")}
          </button>
        )}
        <button type="button" className="primary" disabled={busy} onClick={go}>
          {installing.length && !checkout ? t("features.install") : t("nav.next")}
        </button>
      </Footer>
    </section>
  );
}

// -- 6. permissions ------------------------------------------------------------------------

function PermissionsStep(props: StepProps) {
  const { t, status, state, dispatch, busy } = props;
  const rows = useMemo(
    () => (status ? permissionsFor(status, state.chosen) : []),
    [status, state.chosen],
  );
  const [access, setAccess] = useState<Partial<Record<PermissionId, Access>>>({});
  const [asking, setAsking] = useState<PermissionId | null>(null);

  useEffect(() => {
    for (const row of rows) {
      api
        .permission(row.id, false)
        .then((a) => setAccess((current) => ({ ...current, [row.id]: a })))
        .catch(() => undefined);
    }
  }, [rows]);

  if (!status) return <NeedsTau props={props} step="permissions" />;

  const ask = async (id: PermissionId) => {
    setAsking(id);
    try {
      const answer = await api.permission(id, true);
      setAccess((current) => ({ ...current, [id]: answer }));
    } finally {
      setAsking(null);
    }
  };

  return (
    <section className="step">
      <h1>{t("permissions.title")}</h1>
      {rows.length === 0 ? (
        <p>{t("permissions.none")}</p>
      ) : (
        <>
          <p>{t("permissions.body")}</p>
          {rows.map((row) => {
            const a = access[row.id];
            return (
              <div key={row.id} className="card permission">
                <div className="row">
                  <h2>{row.label}</h2>
                  {a && <span className={`badge ${a}`}>{t(`permissions.access.${a}`)}</span>}
                </div>
                <p>{t(`permissions.why.${row.id}`)}</p>
                <p className="muted small">
                  {t("permissions.for", { features: row.features.join(", ") })}
                </p>
                {a === "denied" && <p className="small">{t(`permissions.fix.${row.id}`)}</p>}
                <div className="buttons">
                  {a === "not_determined" && (
                    <button
                      type="button"
                      className="primary"
                      disabled={asking !== null}
                      onClick={() => ask(row.id)}
                    >
                      {asking === row.id ? t("permissions.asking") : t("permissions.allow")}
                    </button>
                  )}
                  {(a === "denied" || a === "granted") && (
                    <button type="button" onClick={() => api.permissionSettings(row.id)}>
                      {t("permissions.settings")}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </>
      )}
      <Footer
        t={t}
        busy={busy || asking !== null}
        onBack={back(props, "permissions")}
        onSkip={skip(props, "permissions")}
      >
        <button
          type="button"
          className="primary"
          disabled={asking !== null}
          onClick={() => dispatch({ type: "complete", step: "permissions" })}
        >
          {t("nav.next")}
        </button>
      </Footer>
    </section>
  );
}

// -- 8. summary ----------------------------------------------------------------------------

function SummaryStep(props: StepProps) {
  const { t, status, state, discovery, busy, setBusy, reload, dispatch } = props;
  const [hubNote, setHubNote] = useState<string | null>(null);
  const doctor = useJob(reduceRun, emptyRun, setBusy);

  useEffect(() => {
    reload();
    dispatch({ type: "complete", step: "summary" });
    // Once, when the summary opens.
  }, [reload, dispatch]);

  const startHub = async () => {
    try {
      const result = await api.setRunHub(true);
      setHubNote(result.message ?? t("summary.hub_started"));
    } catch (e) {
      setHubNote(String(e));
    }
  };

  const keyLine = status?.config ? t("summary.key.set") : t("summary.key.skipped");
  const checks = doctor.state.done?.checks ?? [];

  return (
    <section className="step">
      <h1>{t("summary.title")}</h1>
      <p>{t("summary.body")}</p>
      <ul className="summary">
        <li>
          <span>{t("summary.key")}</span>
          <em className={`badge ${status?.config ? "done" : "skipped"}`}>{keyLine}</em>
        </li>
        <li>
          <span>{t("summary.about")}</span>
          <em className={`badge ${status?.about ? "done" : "skipped"}`}>
            {status?.about ? t("summary.key.set") : t("summary.key.skipped")}
          </em>
        </li>
        {status?.features
          .filter((f) => f.available)
          .map((f) => {
            const s = summaryState(f, state.chosen, state.outcomes);
            const label =
              s === "on" ? t("setup.outcome.done") : s === "not_chosen" ? t("summary.chosen") : t(`setup.outcome.${s}`);
            return (
              <li key={f.id}>
                <span>{f.label}</span>
                <em className={`badge ${s === "on" ? "done" : s}`}>{label}</em>
              </li>
            );
          })}
      </ul>

      <div className="buttons big">
        <button type="button" className="primary" onClick={() => api.newChat()}>
          {t("summary.chat")}
        </button>
        <button type="button" disabled={!discovery?.hub_ready} onClick={startHub}>
          {t("summary.hub")}
        </button>
        <button type="button" onClick={() => api.openSettings()}>
          {t("summary.settings")}
        </button>
      </div>
      {!discovery?.hub_ready && <p className="muted small">{t("summary.hub_not_ready")}</p>}
      {hubNote && <p className="banner">{hubNote}</p>}

      {discovery?.tau && (
        <div className="card">
          <div className="row">
            <h2>{t("summary.doctor")}</h2>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                doctor.start((onEvent) =>
                  api.run({ kind: "run", target: "doctor" }, null, state.lang, onEvent),
                )
              }
            >
              {t("summary.doctor_run")}
            </button>
          </div>
          {checks.length > 0 && (
            <ul className="checks">
              {checks.map((c, i) => (
                // Names repeat (two `persona` checks): the position is the key.
                <li key={i} className={c.status}>
                  <span className="check-mark">{checkMark(c.status)}</span>
                  <span>
                    <strong>{c.name}</strong> {c.detail}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Problem>{doctor.failure ?? doctor.state.error?.message}</Problem>
        </div>
      )}
      <Footer t={t} busy={busy} onBack={back(props, "summary")} />
    </section>
  );
}

