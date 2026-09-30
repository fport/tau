"""Workspace-wide test isolation.

Every test runs with a throwaway ``HOME``, so nothing reads or writes the owner's real
``~/.tau``, ``~/.local/share/tau`` (sessions, the guard's enrolment, the network store) or
other dot files, even when a fixture removes ``TAU_HOME`` or ``TAU_DATA_DIR`` to test the
defaults. A test that needs a particular home sets its own on top.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
