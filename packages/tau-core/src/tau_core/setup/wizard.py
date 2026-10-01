"""The terminal wizard of ``tau setup`` (and its ``--yes`` form).

1. The language, asked first when neither ``--lang``/``TAU_LANG`` nor a ``tau.toml`` gives one.
2. A numbered checklist of the catalog's features: numbers toggle, Enter goes on. What is set
   up already is marked and never asked again; what this platform lacks is shown with why.
3. One ``uv tool install --force tau-core==<version> --with …`` for the missing packages, then
   ``os.execv`` of the new ``tau setup --resume <state file>``. Outside a uv tool environment
   nothing is reinstalled: the wizard names the packages and goes on with what is installed.
4. The configuration: ``tau init`` when there is no ``tau.toml``, "about you" for
   ``persona/user.md``, each chosen feature's steps, then ``tau doctor``. Every step can be
   skipped; a failed step is reported and the others go on.
5. A summary: what is on, skipped (and why) or failed, what to run next and where the docs are.

Every text comes from the message table; the steps run as subprocesses of this installation's
``tau``, with the terminal when they are interactive. A check step (remote access) runs quietly:
the wizard shows its result and what the owner has to do, offers to open its page, and waits for
"done" (check again) or "skip". It never runs the command it shows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import click

from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from tau_core.setup.catalog import Catalog, Feature, Step
from tau_core.setup.checks import Action, render_action, render_checks
from tau_core.setup.engine import (
    InstallPlan,
    Outcome,
    ResumeError,
    Skip,
    command_text,
    install_plan,
    new_tau,
    preflight,
    read_state,
    render_user_md,
    run_check,
    step_argv,
    store_secrets,
    write_state,
    write_user_md,
)
from tau_core.setup.host import Host
from tau_core.setup.state import FeatureState, Snapshot, configured_language, take_snapshot

__all__ = ["Wizard", "outcome_for_skip", "platform_label"]

Echo = Callable[..., None]


def platform_label(platform: str, language: str) -> str:
    if platform in ("darwin", "linux"):
        return t(f"setup.platform.{platform}", language)
    return t("setup.platform.other", language, platform=platform)


def outcome_for_skip(
    feature: Feature, step: Step, skip: Skip, language: str, platform: str
) -> Outcome:
    fields = dict(skip.fields)
    if "platform" in fields:
        fields["platform"] = platform_label(platform, language)
    brief = t(f"setup.skip.{skip.reason}", language, **fields)
    detail = f"{brief}. {t(skip.text_key, language)}" if skip.text_key else brief
    label = t(step.label, language)
    return Outcome(feature.id, step.id, label, "skipped", skip.reason, detail, brief=brief)


class Wizard:
    def __init__(
        self,
        host: Host,
        catalog: Catalog,
        *,
        features: Sequence[str] = (),
        yes: bool = False,
        no_install: bool = False,
        resume: Path | None = None,
        remove: str | None = None,
        upgrade: bool = False,
        echo: Echo = click.echo,
    ):
        self.host = host
        self.catalog = catalog
        self.features = list(features)
        self.yes = yes
        self.no_install = no_install
        self.resume = resume
        self.remove_id = remove
        self.upgrade = upgrade
        self.echo = echo
        self.language = DEFAULT_LANGUAGE
        self._explained: set[str] = set()
        """The catalog texts already shown for this feature (a second skip shows only why)."""
        self.notes: list[str] = []
        """Lines for the summary that are not per feature (an install that did not happen)."""

    # -- small helpers --------------------------------------------------------------------------

    def t(self, key: str, **fields: object) -> str:
        return t(key, self.language, **fields)

    def label(self, feature: Feature) -> str:
        return self.t(feature.label)

    def confirm(self, text: str, *, default: bool) -> bool:
        """A yes/no question in the UI language (``--yes`` answers yes)."""
        if self.yes:
            return True
        hint = self.t("setup.confirm.hint_yes" if default else "setup.confirm.hint_no")
        yes_words = set(self.t("setup.confirm.yes_words").split(","))
        no_words = set(self.t("setup.confirm.no_words").split(","))
        while True:
            answer = click.prompt(f"{text} [{hint}]", default="", show_default=False)
            answer = str(answer).strip().casefold()
            if not answer:
                return default
            if answer in yes_words:
                return True
            if answer in no_words:
                return False
            self.echo(self.t("setup.confirm.invalid"))

    def snapshot(self) -> Snapshot:
        return take_snapshot(self.host, self.catalog)

    # -- the flow ---------------------------------------------------------------------------------

    def run(self) -> int:
        snapshot = self.snapshot()
        if self.resume is not None:
            return self._resumed(snapshot)
        self.language = self._pick_language(snapshot)
        if not self.yes and not self.host.stdin_isatty():
            self.echo(self.t("setup.no_tty"), err=True)
            return 2
        self.header(snapshot)
        if self.remove_id is not None:
            return self._remove(snapshot, self.remove_id)
        if self.upgrade:
            return self._upgrade(snapshot)
        selection = self._choose(snapshot)
        if selection is None:
            if not self.features:
                self.echo(self.t("setup.quit"))
            return 2 if self.features else 0
        plan = install_plan(self.catalog, snapshot, self.host, add=selection)
        states = [snapshot.get(fid) for fid in selection]
        to_configure = [s.feature.id for s in states if s is not None and not s.done]
        if not self._show_plan(snapshot, plan, to_configure):
            self.echo(self.t("setup.quit"))
            return 0
        if plan.added:
            restarted = self._install(snapshot, plan, selection, to_configure)
            if restarted:
                return 0
        return self.configure(selection, to_configure)

    def _resumed(self, snapshot: Snapshot) -> int:
        assert self.resume is not None
        try:
            state = read_state(self.resume)
        except ResumeError as exc:
            self.language = configured_language(snapshot.home, self.host.environ) or "en"
            self.echo(self.t("setup.resume.invalid", path=self.resume, reason=exc), err=True)
            return 2
        language = state.get("language")
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        self.yes = state.get("yes") is True
        features = state.get("features")
        selection = (
            [f for f in features if isinstance(f, str)] if isinstance(features, list) else []
        )
        selection = [fid for fid in selection if self.catalog.get(fid) is not None]
        fresh = state.get("fresh")
        fresh_ids = [f for f in fresh if f in selection] if isinstance(fresh, list) else selection
        self.header(snapshot)
        self.echo(self.t("setup.install.restarting"))
        return self.configure(selection, fresh_ids)

    def _pick_language(self, snapshot: Snapshot) -> str:
        language = configured_language(snapshot.home, self.host.environ)
        if language is not None:
            return language
        if self.yes or not self.host.stdin_isatty():
            return DEFAULT_LANGUAGE
        prompt = f"{t('setup.language.prompt', 'en')} / {t('setup.language.prompt', 'tr')}"
        choice = click.prompt(
            prompt, type=click.Choice(LANGUAGES), default=DEFAULT_LANGUAGE, show_choices=True
        )
        # The steps are subprocesses: they see the choice until tau init writes it to tau.toml.
        self.host.environ["TAU_LANG"] = choice
        return str(choice)

    def header(self, snapshot: Snapshot) -> None:
        self.echo(
            self.t(
                "setup.title",
                version=snapshot.version,
                platform=platform_label(snapshot.platform, self.language),
            )
        )
        key = "setup.home" if snapshot.config else "setup.home.missing"
        self.echo(self.t(key, path=snapshot.home))
        if snapshot.ssh:
            self.echo(self.t("setup.ssh"))
        self.echo()

    # -- choosing -------------------------------------------------------------------------------

    def checklist_lines(
        self, snapshot: Snapshot, selected: set[str], *, ids: bool = False
    ) -> list[str]:
        """The checklist: a number per feature (``ids``: the feature id instead), the mark,
        the label, the description and the state."""
        labels = [self.label(state.feature) for state in snapshot.features]
        width = max(len(label) for label in labels)
        id_width = max(len(state.feature.id) for state in snapshot.features)
        lines = [self.t("setup.checklist.header")]
        for number, (state, label) in enumerate(zip(snapshot.features, labels, strict=True), 1):
            feature = state.feature
            if state.state == "unavailable":
                mark = " - "
                note = self.t(
                    "setup.state.unavailable",
                    platform=platform_label(snapshot.platform, self.language),
                )
            elif state.done:
                mark = " ✓ "
                note = self.t("setup.state.done")
            else:
                mark = "[x]" if feature.id in selected else "[ ]"
                note = self.t(f"setup.state.{state.state}")
            if feature.advanced:
                note = ", ".join(filter(None, (note, self.t("setup.state.advanced"))))
            about = self.t(feature.description)
            key = f"{feature.id:<{id_width}}" if ids else f"{number:>2}"
            line = f"  {key} {mark} {label:<{width}}  {about}"
            lines.append(f"{line}  ({note})" if note else line)
        return lines

    def _defaults(self, snapshot: Snapshot) -> list[str]:
        if snapshot.config:
            return []  # a re-run: nothing is chosen for the owner
        return [
            state.feature.id
            for state in snapshot.features
            if snapshot.platform in state.feature.default_on and state.available and not state.done
        ]

    def _given(self, snapshot: Snapshot) -> list[str] | None:
        known = self.catalog.ids()
        unknown = [fid for fid in self.features if fid not in known]
        if unknown:
            self.echo(
                self.t(
                    "setup.error.unknown_feature",
                    feature=", ".join(unknown),
                    known=", ".join(known),
                ),
                err=True,
            )
            return None
        chosen: list[str] = []
        for fid in self.features:
            state = snapshot.get(fid)
            assert state is not None
            if not state.available:
                feature = state.feature
                reason = self.t(feature.unavailable) if feature.unavailable else ""
                self.echo(
                    self.t("setup.checklist.unavailable", label=self.label(feature), reason=reason)
                )
                continue
            chosen.append(fid)
        return chosen

    def _choose(self, snapshot: Snapshot) -> list[str] | None:
        if self.features:
            chosen = self._given(snapshot)
        elif self.yes:
            chosen = self._defaults(snapshot)
        else:
            chosen = self._checklist(snapshot)
        if chosen is None:
            return None
        full = self.catalog.with_requires(chosen)
        for fid in full:
            needed_state = snapshot.get(fid)
            if fid not in chosen and needed_state is not None and not needed_state.done:
                needed = needed_state.feature
                for dependent in chosen:
                    feature = self.catalog.get(dependent)
                    if feature is not None and fid in feature.requires:
                        self.echo(
                            self.t(
                                "setup.checklist.requires",
                                label=self.label(feature),
                                required=self.label(needed),
                            )
                        )
        return [fid for fid in full if (s := snapshot.get(fid)) is not None and s.available]

    def _checklist(self, snapshot: Snapshot) -> list[str] | None:
        selected = set(self._defaults(snapshot))
        states = snapshot.features
        while True:
            for line in self.checklist_lines(snapshot, selected):
                self.echo(line)
            answer = str(
                click.prompt(self.t("setup.checklist.hint"), default="", show_default=False)
            ).strip()
            if answer.lower() in ("q", "quit"):
                return None
            if not answer:
                return [s.feature.id for s in states if s.feature.id in selected]
            for token in answer.replace(",", " ").split():
                if not token.isdigit() or not 1 <= int(token) <= len(states):
                    self.echo(self.t("setup.checklist.invalid", value=token))
                    continue
                state = states[int(token) - 1]
                feature = state.feature
                if not state.available:
                    reason = self.t(feature.unavailable) if feature.unavailable else ""
                    self.echo(
                        self.t(
                            "setup.checklist.unavailable", label=self.label(feature), reason=reason
                        )
                    )
                elif state.done:
                    self.echo(
                        self.t(
                            "setup.checklist.done_already", label=self.label(feature), id=feature.id
                        )
                    )
                elif feature.id in selected:
                    selected.discard(feature.id)
                else:
                    selected.add(feature.id)
            self.echo()

    def _show_plan(self, snapshot: Snapshot, plan: InstallPlan, to_configure: list[str]) -> bool:
        if plan.added:
            self.echo(
                self.t(
                    "setup.plan.install",
                    packages=", ".join(plan.added),
                    version=snapshot.version,
                )
            )
        if to_configure:
            labels = [self.label(f) for fid in to_configure if (f := self.catalog.get(fid))]
            self.echo(self.t("setup.plan.configure", features=", ".join(labels)))
        if not plan.added and not to_configure:
            self.echo(self.t("setup.plan.nothing"))
            return True
        return self.confirm(self.t("setup.plan.confirm"), default=True)

    # -- installing -------------------------------------------------------------------------------

    def _install(
        self, snapshot: Snapshot, plan: InstallPlan, selection: list[str], fresh: list[str]
    ) -> bool:
        """Install ``plan``; ``True`` when the process was replaced (a fake ``execv`` in tests
        returns, and the wizard then stops as the real one would have)."""
        packages = ", ".join(plan.added)
        if self.no_install:
            self.echo(self.t("setup.install.skipped", packages=packages))
            self.notes.append(self.t("setup.install.skipped", packages=packages))
            return False
        if not snapshot.uv_tool:
            self.echo(self.t("setup.install.not_uv_tool", packages=packages))
            self.notes.append(self.t("setup.install.not_uv_tool", packages=packages))
            return False
        if plan.uv is None:
            self.echo(self.t("setup.install.uv_missing"), err=True)
            self.notes.append(self.t("setup.install.uv_missing"))
            return False
        self.echo(self.t("setup.install.running", command=command_text(plan.argv[1:])))
        try:
            code = self.host.run(plan.argv)
        except OSError as exc:
            code = 127
            self.echo(self.t("setup.fail.start", error=exc.strerror or exc), err=True)
        if code != 0:
            self.echo(self.t("setup.install.failed", code=code), err=True)
            self.notes.append(self.t("setup.install.failed", code=code))
            return False
        tau = new_tau(self.host, plan.uv)
        if tau is None:
            self.echo(self.t("setup.install.reexec_failed", error="tau not found"), err=True)
            return False
        state = write_state(
            {"language": self.language, "features": selection, "fresh": fresh, "yes": self.yes}
        )
        try:
            self.host.execv(tau, [tau, "setup", "--resume", str(state)])
        except OSError as exc:
            self.echo(self.t("setup.install.reexec_failed", error=exc.strerror or exc), err=True)
            try:
                read_state(state)  # removes it
            except ResumeError:
                pass
            return False
        return True

    def _remove(self, snapshot: Snapshot, feature_id: str) -> int:
        feature = self.catalog.get(feature_id)
        if feature is None:
            known = ", ".join(self.catalog.ids())
            self.echo(
                self.t("setup.error.unknown_feature", feature=feature_id, known=known), err=True
            )
            return 2
        state = snapshot.get(feature_id)
        assert state is not None
        if feature.package is None:
            self.echo(self.t("setup.remove.no_package", label=self.label(feature)), err=True)
            return 1
        if not state.installed:
            self.echo(self.t("setup.remove.not_installed", package=feature.package), err=True)
            return 1
        if feature.keep_while_configured and state.configured:
            self.echo(self.t(feature.keep_while_configured), err=True)
            return 1
        if not snapshot.uv_tool:
            self.echo(self.t("setup.install.not_uv_tool", packages=feature.package), err=True)
            return 1
        plan = install_plan(self.catalog, snapshot, self.host, remove=[feature_id])
        if plan.uv is None:
            self.echo(self.t("setup.install.uv_missing"), err=True)
            return 1
        text = self.t("setup.remove.confirm", label=self.label(feature), package=feature.package)
        if not self.confirm(text, default=False):
            self.echo(self.t("setup.quit"))
            return 0
        self.echo(self.t("setup.install.running", command=command_text(plan.argv[1:])))
        code = self._run_quietly_safe(plan.argv)
        if code != 0:
            self.echo(self.t("setup.install.failed", code=code), err=True)
            return 1
        self.echo(self.t("setup.remove.done", package=feature.package))
        return 0

    def _upgrade(self, snapshot: Snapshot) -> int:
        if not snapshot.uv_tool:
            self.echo(self.t("setup.install.not_uv_tool", packages="tau-core"), err=True)
            return 1
        plan = install_plan(self.catalog, snapshot, self.host, upgrade=True)
        if plan.uv is None:
            self.echo(self.t("setup.install.uv_missing"), err=True)
            return 1
        self.echo(self.t("setup.upgrade.running", command=command_text(plan.argv[1:])))
        code = self._run_quietly_safe(plan.argv)
        if code != 0:
            self.echo(self.t("setup.install.failed", code=code), err=True)
            return 1
        return 0

    def _run_quietly_safe(self, argv: Sequence[str]) -> int:
        try:
            return self.host.run(argv)
        except OSError as exc:
            self.echo(self.t("setup.fail.start", error=exc.strerror or exc), err=True)
            return 127

    # -- configuring ------------------------------------------------------------------------------

    def run_feature(self, feature_id: str) -> int:
        """``tau setup run FEATURE``: that feature's steps, asked like in the wizard, even when
        it is set up already (the owner asked for it by name)."""
        snapshot = self.snapshot()
        self.language = self._pick_language(snapshot)
        if not self.host.stdin_isatty():
            self.echo(self.t("setup.no_tty"), err=True)
            return 2
        self.header(snapshot)
        state = snapshot.get(feature_id)
        assert state is not None
        outcomes = self._feature(state, snapshot, again=True)
        for outcome in outcomes:
            if outcome.step == "-":
                self.echo(self.t("setup.step.skipped", label=outcome.label, reason=outcome.detail))
        return 1 if any(o.status == "failed" for o in outcomes) else 0

    def configure(self, selection: Sequence[str], fresh: Sequence[str] = ()) -> int:
        """Set up ``selection``. A feature in ``fresh`` was not set up when the owner chose it,
        so its steps run even when installing its package alone made it count as set up (the
        notes of sub-taus and cloud mode)."""
        outcomes: list[Outcome] = []
        snapshot = self.snapshot()
        if not snapshot.config:
            outcomes.append(self._init())
            snapshot = self.snapshot()
        if snapshot.config and not snapshot.about:
            outcomes.append(self._about(snapshot))
        for fid in self.catalog.with_requires(selection):
            state = snapshot.get(fid)
            assert state is not None
            outcomes += self._feature(state, snapshot, again=fid in fresh)
        outcomes.append(self._doctor())
        final = self.snapshot()
        self._summary(selection, outcomes, final)
        return 1 if any(o.status == "failed" for o in outcomes) else 0

    def _tau(self, *args: str) -> list[str]:
        return [*self.host.tau(), *args]

    def _run_step(self, argv: Sequence[str]) -> tuple[int | None, str | None]:
        """``(exit code, None)``, or ``(None, reason)`` when it did not run to the end."""
        try:
            return self.host.run(argv), None
        except OSError as exc:
            return None, self.t("setup.fail.start", error=exc.strerror or exc)
        except KeyboardInterrupt:
            self.echo()
            return None, self.t("setup.skip.interrupted")

    def _init(self) -> Outcome:
        label = self.t("setup.core.init")
        self.echo(self.t("setup.section", label=label))
        args = ["init", "--language", self.language] + (["--yes"] if self.yes else [])
        self.echo(self.t("setup.step.running", command=command_text(args)))
        code, problem = self._run_step(self._tau(*args))
        self.echo()
        if code == 0:
            return Outcome("setup", "init", label, "done")
        detail = problem or self.t("setup.fail.exit", code=code)
        return Outcome("setup", "init", label, "failed", "exit", detail, code)

    def _about(self, snapshot: Snapshot) -> Outcome:
        label = self.t("setup.core.about")
        path = snapshot.home / "persona" / "user.md"
        if self.yes:
            return Outcome(
                "setup", "about", label, "skipped", "optional", self.t("setup.skip.optional")
            )
        self.echo(self.t("setup.section", label=label))
        self.echo(self.t("setup.about.intro", path=path))
        name = str(click.prompt(self.t("setup.about.name"), default="", show_default=False)).strip()
        if not name:
            self.echo(self.t("setup.about.skipped", path=path))
            self.echo()
            return Outcome(
                "setup", "about", label, "skipped", "declined", self.t("setup.skip.declined")
            )
        address = click.prompt(self.t("setup.about.address"), default="", show_default=False)
        languages = click.prompt(self.t("setup.about.languages"), default="", show_default=False)
        text = render_user_md(name=name, address=str(address), languages=str(languages))
        try:
            written = write_user_md(snapshot.home, text)
        except OSError as exc:
            detail = self.t("setup.fail.start", error=exc.strerror or exc)
            self.echo(detail, err=True)
            return Outcome("setup", "about", label, "failed", "start", detail)
        self.echo(self.t("setup.about.written", path=written))
        self.echo()
        return Outcome("setup", "about", label, "done")

    def _doctor(self) -> Outcome:
        label = self.t("setup.core.doctor")
        self.echo(self.t("setup.section", label=label))
        self.echo(self.t("setup.step.running", command="doctor"))
        code, problem = self._run_step(self._tau("doctor"))
        self.echo()
        if code == 0:
            return Outcome("setup", "doctor", label, "done")
        if problem is None:
            self.echo(self.t("setup.doctor.problems"))
            self.echo()
        detail = problem or self.t("setup.fail.exit", code=code)
        return Outcome("setup", "doctor", label, "failed", "exit", detail, code)

    def _feature(
        self, state: FeatureState, snapshot: Snapshot, *, again: bool = False
    ) -> list[Outcome]:
        feature = state.feature
        label = self.label(feature)
        if not state.available:
            reason = self.t(feature.unavailable) if feature.unavailable else ""
            detail = self.t("setup.skip.unavailable", reason=reason)
            return [Outcome(feature.id, "-", label, "skipped", "unavailable", detail)]
        if state.done and not again:
            return [
                Outcome(
                    feature.id, "-", label, "skipped", "configured", self.t("setup.skip.configured")
                )
            ]
        if not state.installed:
            assert feature.package is not None
            detail = self.t("setup.skip.not_installed", package=feature.package)
            return [Outcome(feature.id, "-", label, "skipped", "not_installed", detail)]
        self.echo(self.t("setup.section", label=label))
        values: dict[str, str] = {}
        self._explained = set()
        outcomes = [self._step(feature, step, values, snapshot) for step in feature.steps]
        self.echo()
        return [o for o in outcomes if o is not None]

    def _step(
        self, feature: Feature, step: Step, values: dict[str, str], snapshot: Snapshot
    ) -> Outcome | None:
        label = self.t(step.label)
        if not step.applies_to(self.host.platform, feature.platforms):
            return None  # another platform's step: not shown at all
        skip = preflight(step, feature, self.host)
        if skip is not None:
            outcome = outcome_for_skip(feature, step, skip, self.language, self.host.platform)
            explained = skip.text_key is not None and skip.text_key in self._explained
            reason = outcome.brief if explained else outcome.detail
            self.echo(self.t("setup.step.skipped", label=label, reason=reason))
            if skip.text_key is not None:
                self._explained.add(skip.text_key)
            return outcome
        if step.kind == "note":
            self.echo(f"• {label}: {self.t(step.text or '')}")
            if step.url:
                self.echo(f"  {step.url}")
            return Outcome(feature.id, step.id, label, "info")
        command = command_text(step.command)
        if self.yes and step.optional:
            return self._skipped(feature, step, "optional", self.t("setup.skip.optional"))
        if step.check:
            if step.optional and not self.yes:
                ask = self.t("setup.step.ask", label=label, command=command)
                if not self.confirm(ask, default=False):
                    return self._skipped(feature, step, "declined", self.t("setup.skip.declined"))
            return self._check_step(feature, step, label)
        if self.yes and step.interactive:
            text = self.t("setup.skip.interactive", command=command)
            return self._skipped(feature, step, "interactive", text)
        if not self.yes and not self.confirm(
            self.t("setup.step.ask", label=label, command=command), default=not step.optional
        ):
            return self._skipped(feature, step, "declined", self.t("setup.skip.declined"))
        if not self.yes:
            self._ask_inputs(step, values)
        args, missing = step_argv(step, values, self.host.environ)
        if missing is not None:
            text = self.t("setup.skip.no_input", input=missing)
            return self._skipped(feature, step, "no_input", text)
        for name, written in store_secrets(step, values, snapshot.home):
            key = "setup.input.saved" if written else "setup.input.kept"
            self.echo(self.t(key, name=name, path=snapshot.home / ".env"))
        self.echo(self.t("setup.step.running", command=command_text(args)))
        code, problem = self._run_step(self._tau(*args))
        if code == 0:
            self.echo(self.t("setup.step.done", label=label))
            return Outcome(feature.id, step.id, label, "done", code=0)
        if code is not None and step.advisory:
            detail = self.t("setup.advisory", code=code)
            self.echo(self.t("setup.step.done", label=f"{label}: {detail}"))
            return Outcome(feature.id, step.id, label, "done", "advisory", detail, code)
        detail = problem or self.t("setup.fail.exit", code=code)
        self.echo(self.t("setup.step.failed", label=label, reason=detail))
        return Outcome(feature.id, step.id, label, "failed", "exit", detail, code)

    def _check_step(self, feature: Feature, step: Step, label: str) -> Outcome:
        """Check, show what the owner has to do, wait for "done" or "skip", check again. The
        action's command is shown, never run: it may need sudo, which only the owner types."""
        self.echo(self.t("setup.check.running", label=label))
        offered: set[str] = set()
        shown: Action | None = None
        while True:
            result, code = run_check(self.host, step.command)
            if result is None:
                detail = self.t("setup.check.invalid", code=code)
                self.echo(self.t("setup.step.failed", label=label, reason=detail))
                return Outcome(feature.id, step.id, label, "failed", "exit", detail, code)
            for line in render_checks(result.checks):
                self.echo(line)
            if result.ok:
                done = f"{label}: {result.summary}" if result.summary else label
                self.echo(self.t("setup.step.done", label=done))
                return Outcome(feature.id, step.id, label, "done", code=0)
            action = result.action
            if action is None:
                detail = result.summary or self.t("setup.fail.exit", code=code)
                self.echo(self.t("setup.step.failed", label=label, reason=detail))
                return Outcome(feature.id, step.id, label, "failed", "check", detail, code)
            if self.yes:
                detail = self.t("setup.skip.action", summary=result.summary, feature=feature.id)
                return self._skipped(feature, step, "action", detail)
            for line in render_action(action, self.language, brief=action == shown):
                self.echo(line)
            self.echo()
            shown = action
            if action.url and action.url not in offered:
                offered.add(action.url)
                if self.confirm(self.t("setup.check.open", url=action.url), default=False):
                    if not self.host.open_url(action.url):
                        self.echo(self.t("setup.check.open_failed", url=action.url))
            if not self._done_or_skip():
                return self._skipped(feature, step, "declined", self.t("setup.skip.declined"))
            self.echo(self.t("setup.check.again", label=label))

    def _done_or_skip(self) -> bool:
        """``True`` for "done" (or Enter): check again; ``False`` for "skip"."""
        done_words = set(self.t("setup.check.done_words").split(","))
        skip_words = set(self.t("setup.check.skip_words").split(","))
        while True:
            answer = click.prompt(self.t("setup.check.wait"), default="", show_default=False)
            answer = str(answer).strip().casefold()
            if not answer or answer in done_words:
                return True
            if answer in skip_words:
                return False
            self.echo(self.t("setup.check.wait_invalid"))

    def _skipped(self, feature: Feature, step: Step, reason: str, detail: str) -> Outcome:
        label = self.t(step.label)
        self.echo(self.t("setup.step.skipped", label=label, reason=detail))
        return Outcome(feature.id, step.id, label, "skipped", reason, detail)

    def _ask_inputs(self, step: Step, values: dict[str, str]) -> None:
        for item in step.inputs:
            if item.name in values:
                continue
            label = self.t(item.label)
            if item.secret:
                text = self.t("setup.input.secret", label=label)
                value = click.prompt(text, default="", show_default=False, hide_input=True)
            elif item.default:
                text = self.t("setup.input.prompt_default", label=label, default=item.default)
                value = click.prompt(text, default=item.default, show_default=False)
            elif item.required:
                value = click.prompt(label, default="", show_default=False)
            else:
                text = self.t("setup.input.prompt_optional", label=label)
                value = click.prompt(text, default="", show_default=False)
            values[item.name] = str(value).strip()

    # -- the summary ------------------------------------------------------------------------------

    def _summary(self, selection: Sequence[str], outcomes: list[Outcome], final: Snapshot) -> None:
        self.echo(self.t("setup.section", label=self.t("setup.summary.title")))
        rows: list[tuple[str, str, str]] = []
        for core in ("init", "about", "doctor"):
            for outcome in outcomes:
                if (
                    outcome.feature == "setup"
                    and outcome.step == core
                    and outcome.status == "failed"
                ):
                    rows.append(
                        ("✗", outcome.label, f"{self.t('setup.summary.failed')} · {outcome.detail}")
                    )
        chosen = set(self.catalog.with_requires(selection))
        for state in final.features:
            feature = state.feature
            mine = [o for o in outcomes if o.feature == feature.id]
            if not (state.done or feature.id in chosen):
                continue
            failed = [o for o in mine if o.status == "failed"]
            skipped = [o for o in mine if o.status == "skipped" and o.reason != "configured"]
            ran = [o for o in mine if o.status in ("done", "info")]
            if failed:
                first = failed[0]
                rows.append(
                    (
                        "✗",
                        self.label(feature),
                        f"{self.t('setup.summary.failed')} · {first.label}: {first.detail}",
                    )
                )
            elif state.done or (ran and not skipped):
                tail = ""
                if skipped:
                    labels = ", ".join(o.label for o in skipped)
                    tail = f" · {self.t('setup.summary.skipped')}: {labels}"
                rows.append(("✓", self.label(feature), self.t("setup.summary.on") + tail))
            elif ran:
                tail = ", ".join(f"{o.label}: {o.brief or o.detail}" for o in skipped)
                rows.append(
                    ("~", self.label(feature), f"{self.t('setup.summary.partly')} · {tail}")
                )
            else:
                detail = (skipped[0].brief or skipped[0].detail) if skipped else ""
                rows.append(
                    (
                        "–",
                        self.label(feature),
                        f"{self.t('setup.summary.skipped')} · {detail}".rstrip(" ·"),
                    )
                )
        width = max((len(label) for _, label, _ in rows), default=0)
        for mark, label, text in rows:
            self.echo(f"  {mark} {label:<{width}}  {text}")
        for note in self.notes:
            self.echo(f"  ! {note}")
        self.echo()
        self.echo(self.t("setup.summary.next"))
        if final.config:
            self.echo("  " + self.t("setup.summary.next_chat"))
            tui = final.get("tui")
            if tui is not None and tui.installed:
                self.echo("  " + self.t("setup.summary.next_tui"))
        self.echo("  " + self.t("setup.summary.next_doctor"))
        app = self.catalog.get("app")
        if app is not None and "app" in chosen and app.available_on(final.platform):
            url = next((step.url for step in app.steps if step.url), None)
            if url:
                self.echo("  " + self.t("setup.summary.next_app", url=url))
        self.echo(self.t("setup.summary.rerun"))
        prefix = "tr/" if self.language == "tr" else ""
        self.echo(self.t("setup.summary.docs", url=f"{self.catalog.docs}{prefix}reference/setup/"))
