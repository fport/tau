"""A fake :class:`~tau_core.setup.host.Host` for the ``tau setup`` tests.

Nothing here runs a program: ``run`` records the argv and answers from a table (and can
simulate what a step does, e.g. ``tau init`` writing ``tau.toml``), ``execv`` records the
re-execution and returns, ``capture`` answers ``--help`` probes and ``uv tool dir --bin`` and
plays check objects (``checks``) back in order, ``open_url`` records the page.
The environment is a plain dict with ``TAU_HOME``, ``TAU_DATA_DIR`` and ``HOME`` under
``tmp_path``, so no test sees ``~/.tau``, the real data dir or the real uv tool dir.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from tau_core.builder import KeyCheck
from tau_core.setup.host import Host, LineSink

TAU = "tau-under-test"
UV = "/fake/bin/uv"

Effect = Callable[[Sequence[str]], None]


class FakeHost(Host):
    def __init__(
        self,
        tmp_path: Path,
        *,
        platform: str = "darwin",
        installed: Mapping[str, str] | None = None,
        uv_tool: bool = True,
        receipt: str | None = None,
        tty: bool = True,
        ssh: bool = False,
        commands: Sequence[Sequence[str]] = (),
        programs: Sequence[str] = ("uv",),
        codes: Mapping[tuple[str, ...], int] | None = None,
        effects: Mapping[tuple[str, ...], Effect] | None = None,
        output: Mapping[tuple[str, ...], Sequence[str]] | None = None,
        checks: Mapping[tuple[str, ...], Sequence[tuple[int, str]]] | None = None,
        key_answer: KeyCheck | None = None,
        stdin: str = "",
        environ: Mapping[str, str] | None = None,
    ):
        self.tmp = tmp_path
        self.platform = platform
        self.home = tmp_path / "tau-home"
        self.data = tmp_path / "tau-data"
        self.user = tmp_path / "user"
        self.user.mkdir(exist_ok=True)
        self.environ = {
            "TAU_HOME": str(self.home),
            "TAU_DATA_DIR": str(self.data),
            "HOME": str(self.user),
            "PATH": "/fake/bin",
            **(environ or {}),
        }
        if ssh:
            self.environ["SSH_CONNECTION"] = "100.x.y.z 51000 100.x.y.z 22"
        self.root = tmp_path / "root"
        self.prefix = tmp_path / "env"
        self.prefix.mkdir(exist_ok=True)
        if uv_tool:
            (self.prefix / "uv-receipt.toml").write_text(
                receipt or '[tool]\nrequirements = [{ name = "tau-core" }]\n', encoding="utf-8"
            )
        self.installed = {"tau-core": "0.4.0", **(installed or {})}
        self.tty = tty
        self.commands = {tuple(c) for c in commands}
        self.programs = set(programs)
        # Remote access is not set up unless a test says so (`tau remote status` exits 0).
        self.codes = {("remote", "status"): 1, **(codes or {})}
        self.effects = dict(effects or {})
        self.output = dict(output or {})
        self.checks = {key: list(answers) for key, answers in (checks or {}).items()}
        """``tau <command> --json`` of a check step: the answers in order, the last one repeats."""
        self.captures: list[list[str]] = []
        self.opened: list[str] = []
        self.key_answer = key_answer or KeyCheck("ok", status=200)
        self.key_calls: list[tuple[str, str]] = []
        self.stdin = stdin
        self.runs: list[tuple[list[str], bool]] = []
        """``(argv, captured)`` for every ``run``."""
        self.execs: list[tuple[str, list[str]]] = []
        self.bin = tmp_path / "tool-bin"
        self.bin.mkdir(exist_ok=True)
        (self.bin / "tau").write_text("#!/bin/sh\n", encoding="utf-8")

    # -- the Host API ----------------------------------------------------------------------------

    def tau(self) -> list[str]:
        return [TAU]

    def which(self, program: str) -> str | None:
        return f"/fake/bin/{program}" if program in self.programs else None

    def version_of(self, distribution: str) -> str | None:
        return self.installed.get(distribution)

    def _key(self, argv: Sequence[str]) -> tuple[str, ...]:
        words = list(argv[1:]) if argv and argv[0] == TAU else list(argv)
        return tuple(words)

    def _lookup(self, table: Mapping[tuple[str, ...], object], argv: Sequence[str]) -> object:
        key = self._key(argv)
        for length in range(len(key), 0, -1):
            if key[:length] in table:
                return table[key[:length]]
        return None

    def run(
        self,
        argv: Sequence[str],
        *,
        on_line: LineSink | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        self.runs.append((list(argv), on_line is not None))
        effect = self._lookup(self.effects, argv)
        if effect is not None:
            effect(argv)  # type: ignore[operator]
        lines = self._lookup(self.output, argv) or ()
        if on_line is not None:
            for line in lines:  # type: ignore[union-attr]
                on_line(line)
        code = self._lookup(self.codes, argv)
        return int(code) if code is not None else 0  # type: ignore[call-overload]

    def capture(self, argv: Sequence[str]) -> tuple[int, str]:
        self.captures.append(list(argv))
        key = self._key(argv)
        if key and key[-1] == "--json" and key[:-1] in self.checks:
            answers = self.checks[key[:-1]]
            return answers.pop(0) if len(answers) > 1 else answers[0]
        if list(argv[:4]) == [UV, "tool", "dir", "--bin"]:
            return 0, f"{self.bin}\n"
        if argv and argv[0] == TAU and argv[-1] == "--help":
            return (0, "") if tuple(argv[1:-1]) in self.commands else (2, "")
        if argv and argv[0] == TAU:
            code = self._lookup(self.codes, argv)
            lines = self._lookup(self.output, argv) or ()
            text = "\n".join(lines)  # type: ignore[arg-type]
            return (int(code) if code is not None else 0), text  # type: ignore[call-overload]
        return 127, ""

    def execv(self, path: str, argv: Sequence[str]) -> None:
        self.execs.append((path, list(argv)))

    def key_check(self, provider: str, key: str) -> KeyCheck:
        self.key_calls.append((provider, key))
        return self.key_answer

    def stdin_isatty(self) -> bool:
        return self.tty

    def read_stdin(self, limit: int) -> str:
        return self.stdin[: limit + 1]

    def open_url(self, url: str) -> bool:
        self.opened.append(url)
        return True

    # -- helpers for the tests -------------------------------------------------------------------

    def tau_runs(self) -> list[list[str]]:
        """The argv after ``tau`` of every step that ran."""
        return [argv[1:] for argv, _ in self.runs if argv and argv[0] == TAU]

    def uv_runs(self) -> list[list[str]]:
        return [argv for argv, _ in self.runs if argv and argv[0] == UV]

    def write_config(self, language: str = "en") -> None:
        (self.home / "persona").mkdir(parents=True, exist_ok=True)
        (self.home / "tau.toml").write_text(f'[ui]\nlanguage = "{language}"\n', encoding="utf-8")

    def init_effect(self, argv: Sequence[str]) -> None:
        """What ``tau init`` leaves behind: ``tau.toml`` and the example ``user.md``."""
        from tau_core.builder import template_text

        language = "en"
        if "--language" in argv:
            language = argv[list(argv).index("--language") + 1]
        self.write_config(language)
        (self.home / "persona" / "user.md").write_text(
            template_text("user.example.md"), encoding="utf-8"
        )
