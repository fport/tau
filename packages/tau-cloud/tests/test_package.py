"""Packaging rules: entry points, the public API, the message table, the language rule."""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import tau_cloud
import tau_cloud.testing
from tau_cloud.strings import CLOUD_MESSAGES
from tau_core import registry
from tau_core.i18n import LANGUAGES, MESSAGES


def test_entry_points() -> None:
    dist = metadata.distribution("tau-cloud")
    points = {(ep.group, ep.name): ep.value for ep in dist.entry_points}
    assert points == {
        ("tau.commands", "cloud"): "tau_cloud.cli:cloud",
        ("tau.sessions", "spine"): "tau_cloud.sessions:make_store",
    }
    assert metadata.version("tau-cloud") == tau_cloud.__version__
    assert "spine" in registry.session_backend_names()


def test_public_api_is_explicit() -> None:
    for module in (tau_cloud, tau_cloud.testing):
        assert sorted(module.__all__) == sorted(set(module.__all__))
        for name in module.__all__:
            assert hasattr(module, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in CLOUD_MESSAGES.items():
        assert key.startswith("cloud."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    source = Path(tau_cloud.__file__).parent
    for path in source.glob("*.py"):
        if path.name == "strings.py":
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


def test_the_image_installs_this_package() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "cloud" / "spine" / "container" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY packages/tau-cloud /src/tau-cloud" in dockerfile
    assert 'CMD ["tau", "cloud", "run"]' in dockerfile
    assert "EXPOSE 8080" in dockerfile
