"""Configuration resolution, merge semantics and hashing.

Acceptance criteria for milestone M1, per ``docs/PLAN.md`` and ``docs/TESTING.md`` section 3.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from mmlsa.config import MAX_EXTENDS_DEPTH, Config, ConfigError, load_config, resolve_extends
from mmlsa.settings import build_config, env_overrides, parse_set_options
from tests.conftest import CONFIGS_DIR

SHIPPED_CONFIGS = sorted(CONFIGS_DIR.glob("*.yaml"))


def _write(path: Path, mapping: dict) -> Path:
    """Write a mapping as YAML and return the path."""
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return path


# ------------------------------------------------------------------ every shipped config resolves


def test_shipped_configs_are_discovered() -> None:
    """A glob that silently matched nothing would make the parametrized test below vacuous."""
    assert len(SHIPPED_CONFIGS) >= 7


@pytest.mark.parametrize("config_path", SHIPPED_CONFIGS, ids=lambda p: p.name)
def test_shipped_config_resolves_and_validates(config_path: Path) -> None:
    """Catches a key added to a child config but never declared in the model."""
    config = build_config(config_path)
    assert isinstance(config, Config)
    assert len(config.config_hash()) == 64


@pytest.mark.parametrize("config_path", SHIPPED_CONFIGS, ids=lambda p: p.name)
def test_extends_never_reaches_the_model(config_path: Path) -> None:
    """``extends`` is a loader directive; the validated mapping must not contain it."""
    assert "extends" not in resolve_extends(config_path)
    assert "extends" not in build_config(config_path).to_dict()


# ----------------------------------------------------------------------------- inheritance chains


def test_two_level_chain_resolves_in_order() -> None:
    """sensitivity extends poc extends default: each level contributes what it declares.

    ``corpus.include_ids`` comes from poc, ``chunking.P`` from default, and ``run.M`` is the child's
    own value, which must beat both parents.
    """
    sensitivity = build_config(CONFIGS_DIR / "sensitivity.yaml")
    poc = build_config(CONFIGS_DIR / "poc.yaml")
    default = build_config(CONFIGS_DIR / "default.yaml")

    assert sensitivity.corpus.include_ids == poc.corpus.include_ids
    assert sensitivity.chunking.P == default.chunking.P
    assert sensitivity.run.M == 5
    assert poc.run.M == 3


def test_purification_chain_enables_only_what_it_declares() -> None:
    """purification extends full: the parent's pinned run settings survive the child's override."""
    purification = build_config(CONFIGS_DIR / "purification.yaml")
    full = build_config(CONFIGS_DIR / "full.yaml")

    assert purification.purification.enabled is True
    assert full.purification.enabled is False
    assert purification.corpus.expected_count == full.corpus.expected_count
    assert purification.chunking.P == full.chunking.P


# --------------------------------------------------------------------------------- merge semantics


def test_mapping_merge_leaves_sibling_keys_intact(tmp_path: Path) -> None:
    """A child setting one key inside a mapping must not erase the rest of that mapping."""
    parent = _write(tmp_path / "parent.yaml", {"chunking": {"P": 400, "min_chunk_words": 7}})
    child = _write(tmp_path / "child.yaml", {"extends": parent.name, "chunking": {"P": 200}})

    resolved = resolve_extends(child)
    assert resolved["chunking"] == {"P": 200, "min_chunk_words": 7}


def test_lists_replace_rather_than_concatenate(tmp_path: Path) -> None:
    """A merged include_ids would silently widen a run, so lists replace wholesale."""
    parent = _write(tmp_path / "parent.yaml", {"corpus": {"include_ids": ["a", "b"]}})
    child = _write(
        tmp_path / "child.yaml", {"extends": parent.name, "corpus": {"include_ids": ["c"]}}
    )

    assert resolve_extends(child)["corpus"]["include_ids"] == ["c"]


def test_null_is_a_value_not_an_absence(tmp_path: Path) -> None:
    """``include_ids: null`` in a child means the whole corpus and overrides a parent's subset."""
    parent = _write(tmp_path / "parent.yaml", {"corpus": {"include_ids": ["a", "b"]}})
    child = _write(
        tmp_path / "child.yaml", {"extends": parent.name, "corpus": {"include_ids": None}}
    )

    assert resolve_extends(child)["corpus"]["include_ids"] is None


# ------------------------------------------------------------------------------------------ hashing


def test_hash_is_a_function_of_resolved_values_not_of_the_path(tmp_path: Path) -> None:
    """Two configs that flatten to the same mapping hash identically, however they inherited."""
    flat = _write(tmp_path / "flat.yaml", {"chunking": {"P": 250}, "run": {"M": 4}})

    parent = _write(tmp_path / "parent.yaml", {"chunking": {"P": 250}})
    inherited = _write(tmp_path / "inherited.yaml", {"extends": parent.name, "run": {"M": 4}})

    assert load_config(flat).config_hash() == load_config(inherited).config_hash()


def test_omitting_a_key_that_equals_the_default_does_not_change_the_hash(tmp_path: Path) -> None:
    """The hash covers effective values, so a default written out explicitly is not a new config."""
    implicit = _write(tmp_path / "implicit.yaml", {"run": {"M": 3}})
    explicit = _write(tmp_path / "explicit.yaml", {"run": {"M": 3, "seed": 20260731}})

    assert load_config(implicit).config_hash() == load_config(explicit).config_hash()


@pytest.mark.parametrize(
    ("group", "key", "value"),
    [
        ("chunking", "P", 300),
        ("run", "M", 5),
        ("run", "seed", 1),
        ("llm", "provider", "fake"),
        ("llm", "temperature", 0.5),
        ("distance", "metric", "fw_freq_cosine"),
        ("classify", "method", "gmm_2"),
        ("aggregate", "std_ddof", 0),
        ("noise", "enabled", False),
        ("profile", "structured_output", False),
    ],
)
def test_changing_any_single_key_changes_the_hash(
    tmp_path: Path, group: str, key: str, value: object
) -> None:
    """Every effective key participates in the identity of a run."""
    baseline = load_config(_write(tmp_path / "base.yaml", {}))
    changed = load_config(_write(tmp_path / "changed.yaml", {group: {key: value}}))

    assert baseline.config_hash() != changed.config_hash()


def test_hash_is_independent_of_key_order(tmp_path: Path) -> None:
    """Canonical JSON, so YAML ordering cannot leak into the run id."""
    one = _write(tmp_path / "one.yaml", {"run": {"M": 4, "seed": 11}, "chunking": {"P": 250}})
    two = _write(tmp_path / "two.yaml", {"chunking": {"P": 250}, "run": {"seed": 11, "M": 4}})

    assert load_config(one).config_hash() == load_config(two).config_hash()


def test_snapshot_of_a_resolved_config_loads_without_its_parents(tmp_path: Path) -> None:
    """A run must be reproducible from its snapshot alone (ARCHITECTURE 7.1, rule 5)."""
    original = build_config(CONFIGS_DIR / "sensitivity.yaml")

    snapshot = tmp_path / "config.snapshot.yaml"
    snapshot.write_text(yaml.safe_dump(original.to_dict(), sort_keys=True), encoding="utf-8")

    assert load_config(snapshot).config_hash() == original.config_hash()


# -------------------------------------------------------------------------------------- failures


def test_direct_self_reference_is_a_startup_error(tmp_path: Path) -> None:
    """A config that extends itself must raise, not recurse until the stack ends."""
    path = tmp_path / "loop.yaml"
    _write(path, {"extends": "loop.yaml"})

    with pytest.raises(ConfigError, match="cyclic"):
        resolve_extends(path)


def test_transitive_cycle_reports_the_chain(tmp_path: Path) -> None:
    """The error names every file involved, so the loop is fixable without bisecting by hand."""
    _write(tmp_path / "a.yaml", {"extends": "b.yaml"})
    _write(tmp_path / "b.yaml", {"extends": "c.yaml"})
    _write(tmp_path / "c.yaml", {"extends": "a.yaml"})

    with pytest.raises(ConfigError) as excinfo:
        resolve_extends(tmp_path / "a.yaml")

    message = str(excinfo.value)
    assert all(name in message for name in ("a.yaml", "b.yaml", "c.yaml"))


def test_chain_deeper_than_the_cap_is_rejected(tmp_path: Path) -> None:
    """Depth is capped so a pathological chain fails with a message rather than a stack overflow."""
    depth = MAX_EXTENDS_DEPTH + 2
    for index in range(depth):
        parent = {"extends": f"level_{index + 1}.yaml"} if index + 1 < depth else {}
        _write(tmp_path / f"level_{index}.yaml", parent)

    with pytest.raises(ConfigError, match="deeper than"):
        resolve_extends(tmp_path / "level_0.yaml")


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """Extras are forbidden, so a typo fails at startup instead of being ignored for months."""
    path = _write(tmp_path / "typo.yaml", {"chunking": {"PP": 400}})

    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file_is_reported_by_name(tmp_path: Path) -> None:
    """The error says which file, which matters when the missing one is a parent."""
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_manual_threshold_without_a_value_is_rejected(tmp_path: Path) -> None:
    """A cross-field rule: selecting the manual classifier requires the threshold it will use."""
    path = _write(tmp_path / "manual.yaml", {"classify": {"method": "manual"}})

    with pytest.raises(ConfigError, match="manual_tau"):
        load_config(path)


def test_inverted_length_ratios_are_rejected(tmp_path: Path) -> None:
    """A validation band with its bounds the wrong way round rejects every rewrite silently."""
    path = _write(
        tmp_path / "ratios.yaml",
        {"rewrite": {"validation": {"min_length_ratio": 1.8, "max_length_ratio": 1.2}}},
    )

    with pytest.raises(ConfigError, match="min_length_ratio"):
        load_config(path)


# ------------------------------------------------------------------------------------- precedence


def test_cli_flag_beats_the_file() -> None:
    """CLI is the highest-precedence source."""
    from_file = build_config(CONFIGS_DIR / "default.yaml")
    overridden = build_config(CONFIGS_DIR / "default.yaml", provider="fake")

    assert from_file.llm.provider != "fake"
    assert overridden.llm.provider == "fake"


def test_environment_beats_the_file() -> None:
    """``MMLSA_RUN__M`` overrides the YAML value."""
    config = build_config(CONFIGS_DIR / "default.yaml", environ={"MMLSA_RUN__M": "5"})
    assert config.run.M == 5


def test_cli_beats_the_environment() -> None:
    """Both sources set the same key; the CLI wins."""
    config = build_config(
        CONFIGS_DIR / "default.yaml",
        seed=999,
        environ={"MMLSA_RUN__SEED": "111"},
    )
    assert config.run.seed == 999


def test_env_overrides_parse_scalars_by_type() -> None:
    """Values go through the YAML scalar parser, so types survive the environment."""
    parsed = env_overrides(
        {"MMLSA_RUN__M": "5", "MMLSA_NOISE__ENABLED": "false", "MMLSA_LLM__MODEL_ID": "null"}
    )
    assert parsed == {"run": {"M": 5}, "noise": {"enabled": False}, "llm": {"model_id": None}}


def test_api_keys_are_not_treated_as_configuration() -> None:
    """Secrets never enter the config model, the snapshot or the hash (R6)."""
    parsed = env_overrides({"GEMINI_API_KEY": "secret", "MMLSA_RUN__M": "4"})
    assert parsed == {"run": {"M": 4}}

    config = build_config(CONFIGS_DIR / "default.yaml", environ={"GEMINI_API_KEY": "secret"})
    assert "secret" not in yaml.safe_dump(config.to_dict())


def test_set_option_reaches_a_nested_key() -> None:
    """``--set`` addresses any key by dotted path, including ones with no dedicated flag."""
    assert parse_set_options(["rewrite.validation.min_length_ratio=0.4"]) == {
        "rewrite": {"validation": {"min_length_ratio": 0.4}}
    }

    config = build_config(
        CONFIGS_DIR / "default.yaml", set_options=["rewrite.validation.min_length_ratio=0.4"]
    )
    assert config.rewrite.validation.min_length_ratio == 0.4


def test_malformed_set_option_is_rejected() -> None:
    """A missing '=' is a mistake, not an empty override."""
    with pytest.raises(ConfigError, match=re.escape("dotted.key=value")):
        parse_set_options(["llm.provider"])


def test_override_keys_are_matched_case_insensitively() -> None:
    """``chunking.P`` and ``run.M`` are uppercase in the specification; overrides must reach them."""
    assert parse_set_options(["chunking.p=250"]) == {"chunking": {"P": 250}}
    assert env_overrides({"MMLSA_CHUNKING__P": "250"}) == {"chunking": {"P": 250}}
    assert build_config(CONFIGS_DIR / "default.yaml", set_options=["run.m=4"]).run.M == 4


def test_unknown_override_key_is_rejected_rather_than_ignored() -> None:
    """A typo in an override must fail; an ignored override looks like the flag did nothing."""
    with pytest.raises(ConfigError, match="unknown configuration key 'chnking'"):
        parse_set_options(["chnking.P=250"])

    with pytest.raises(ConfigError, match="unknown configuration key 'PP'"):
        env_overrides({"MMLSA_CHUNKING__PP": "250"})


def test_the_live_provider_guard_is_not_read_as_a_configuration_key() -> None:
    """``MMLSA_ALLOW_LIVE`` controls the process, not the configuration.

    The ``MMLSA_`` prefix does double duty. Rejecting an unknown key is right for a typo and wrong
    for a control variable, and this one is set by CI on every run: with it treated as a key, every
    test that builds a configuration failed there while passing on a developer's machine, where the
    variable is simply absent. Four pushes went red before anyone ran the suite the way CI does.
    """
    assert env_overrides({"MMLSA_ALLOW_LIVE": "0", "MMLSA_RUN__M": "4"}) == {"run": {"M": 4}}

    config = build_config(CONFIGS_DIR / "default.yaml", environ={"MMLSA_ALLOW_LIVE": "1"})
    assert config.run.M == 3


# ------------------------------------------------------------------------------------------ paths


def test_relative_paths_are_kept_relative_in_the_hash(tmp_path: Path) -> None:
    """An absolute path would make the hash machine-dependent and unreproducible across machines."""
    config = build_config(CONFIGS_DIR / "default.yaml")

    assert not Path(config.corpus.dir).is_absolute()
    assert str(config.root) not in yaml.safe_dump(config.to_dict())


def test_path_resolves_against_the_project_root() -> None:
    """Relative config paths resolve the same way whichever directory the command ran from."""
    config = build_config(CONFIGS_DIR / "default.yaml")
    resolved = config.path(config.corpus.dir)

    assert resolved.is_absolute()
    assert resolved == config.root / "data" / "corpus"
