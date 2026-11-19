"""Run the formatter over Kconfiglib's test corpus (tests/kconfiglib submodule).

Kconfiglib itself is the oracle: formatting must not change what it parses.
"""

import shutil
import sys
from pathlib import Path

import pytest

from kconfigstyle import KconfigFormatter, KconfigParser, LinterConfig

KCONFIGLIB_ROOT = Path(__file__).parent / "kconfiglib"

if not (KCONFIGLIB_ROOT / "kconfiglib.py").exists():
    pytest.skip(
        "Kconfiglib submodule missing (git submodule update --init)",
        allow_module_level=True,
    )

# Zephyr's fork, not the PyPI release: the corpus uses fork-only syntax
# like 'depends on X if Y'.
sys.path.insert(0, str(KCONFIGLIB_ROOT))
import kconfiglib  # noqa: E402

CORPUS = sorted(
    p.relative_to(KCONFIGLIB_ROOT).as_posix()
    for p in (KCONFIGLIB_ROOT / "tests").rglob("K*")
    if p.is_file() and not p.is_symlink()
)

PRESETS = {
    "zephyr": LinterConfig.zephyr_preset,
    "espidf": LinterConfig.espidf_preset,
}

# Mirrors the environment Kconfiglib's testsuite.py sets up
CORPUS_ENV = {
    "TESTS_DIR_FROM_ENV": "tests",
    "SUB_DIR_FROM_ENV": "sub",
    "_SOURCED": "_sourced",
    "_RSOURCED": "_rsourced",
    "_GSOURCED": "_gsourced",
    "_GRSOURCED": "_grsourced",
    "ENV_1": "env_1",
    "ENV_2": "env_2",
    "ENV_3": "env_3",
    "ENV_4": "env_4",
    "ENV_5": "n",
    "ENV_6": "tests/empty",
    "ENV_7": "env_7",
    "ENV_VAR": "ENV_VAR value",
    "FOO": "bar baz",
}

# Help text lines indented deeper than the first are flattened
HELP_RELATIVE_INDENT = {"tests/Khelp", "tests/Klocation", "tests/Kstr"}
# An empty 'help' followed by an indented entry: the entry becomes help text
EMPTY_HELP_SWALLOWS_ENTRY = {("tests/Klocation", "espidf")}


def _format(text: str, config: LinterConfig) -> str:
    ast = KconfigParser().parse(text)
    return "".join(line + "\n" for line in KconfigFormatter(config).format(ast))


def _fingerprint(filename: str) -> list[str]:
    """Kconfiglib's normalized view of every menu node in the tree."""
    kconf = kconfiglib.Kconfig(filename, warn=False)
    return [kconf.mainmenu_text] + [str(node) for node in kconf.node_iter()]


@pytest.fixture(scope="module", params=PRESETS)
def formatted_tree(request, tmp_path_factory) -> tuple[str, Path]:
    """A copy of the corpus with every Kconfig file formatted."""
    root = tmp_path_factory.mktemp(f"kconfiglib-{request.param}")
    shutil.copytree(KCONFIGLIB_ROOT / "tests", root / "tests", symlinks=True)
    config = PRESETS[request.param]()
    for rel in CORPUS:
        path = root / rel
        path.write_text(_format(path.read_text(), config))
    return request.param, root


@pytest.fixture
def corpus_env(monkeypatch):
    for key, value in CORPUS_ENV.items():
        monkeypatch.setenv(key, value)
    # For Kuserfunctions' KCONFIG_FUNCTIONS module
    monkeypatch.syspath_prepend(str(KCONFIGLIB_ROOT / "tests"))


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("filename", CORPUS)
def test_format_is_idempotent(filename, preset, request):
    if (filename, preset) in EMPTY_HELP_SWALLOWS_ENTRY:
        request.applymarker(
            pytest.mark.xfail(reason="empty help swallows next entry", strict=True)
        )
    config = PRESETS[preset]()
    once = _format((KCONFIGLIB_ROOT / filename).read_text(), config)
    assert _format(once, config) == once


@pytest.mark.parametrize("filename", CORPUS)
def test_format_preserves_semantics(
    filename, formatted_tree, corpus_env, monkeypatch, request
):
    _, root = formatted_tree
    if filename in HELP_RELATIVE_INDENT:
        request.applymarker(
            pytest.mark.xfail(reason="help text relative indent lost", strict=True)
        )

    def load(srctree: Path) -> list[str]:
        monkeypatch.setenv("srctree", str(srctree))
        monkeypatch.chdir(srctree)
        return _fingerprint(filename)

    try:
        expected = load(KCONFIGLIB_ROOT)
    except (kconfiglib.KconfigError, OSError) as e:
        # Some corpus files are deliberately broken (dependency loops,
        # missing sources) or need a different srctree
        pytest.skip(f"Kconfiglib rejects the original: {str(e).splitlines()[0]}")

    assert load(root) == expected
