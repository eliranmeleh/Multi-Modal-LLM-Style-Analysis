"""Assembling the effective configuration from all four sources.

Precedence, highest first: CLI flags, environment variables, the YAML file (with its ``extends``
ancestry), model defaults.

Environment overrides use ``MMLSA_<GROUP>__<KEY>``, double underscore between levels, for example
``MMLSA_LLM__PROVIDER=fake`` or ``MMLSA_RUN__M=5``. Values are parsed as YAML scalars, so ``5`` is an
integer, ``true`` is a boolean and ``null`` is None.

**API keys are not configuration.** They are read from the environment at the point of use by the
provider that needs them, and never enter the config model, the snapshot, the hash or a log line (R6).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from mmlsa.config import Config, ConfigError, load_config

ENV_PREFIX = "MMLSA_"
_LEVEL_SEPARATOR = "__"

SECRET_ENV_VARS = frozenset({"GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"})
"""Read directly by providers. Never placed in the config model, and never logged."""

RESERVED_ENV_VARS = frozenset({"MMLSA_ALLOW_LIVE"})
"""``MMLSA_``-prefixed variables that control the process rather than the configuration.

The prefix does double duty: ``MMLSA_RUN__M`` is an override, ``MMLSA_ALLOW_LIVE`` is a switch the
test harness reads. Without this set the second kind is parsed as a config key, found to match no
field, and rejected — which is the right behaviour for a typo and the wrong one for a control
variable. Anything added here must be a name no configuration key could ever take."""


def _field_model(model: type[BaseModel], field_name: str) -> type[BaseModel] | None:
    """Return the nested model type of a field, or None if the field is a leaf."""
    annotation = model.model_fields[field_name].annotation
    return (
        annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None
    )


def canonical_key_path(segments: list[str]) -> list[str]:
    """Match a dotted key path against the config model's real field names, ignoring case.

    Two keys in the specification are single uppercase letters, ``chunking.P`` and ``run.M``, because
    that is how the book names them. An override source that simply lowercased its input would miss
    both, so the path is resolved against the model instead of being case-normalized blindly.
    An unknown segment is an error here rather than a silently ignored override.
    """
    canonical: list[str] = []
    model: type[BaseModel] | None = Config

    for index, segment in enumerate(segments):
        if model is None:
            canonical.extend(segments[index:])
            break

        matches = [name for name in model.model_fields if name.lower() == segment.lower()]
        if not matches:
            location = ".".join(canonical) or "the top level"
            known = ", ".join(sorted(model.model_fields))
            raise ConfigError(
                f"unknown configuration key '{segment}' under {location}. Known: {known}"
            )

        name = matches[0]
        canonical.append(name)
        model = _field_model(model, name)

    return canonical


def _assign(target: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a nested key path in a mapping, creating intermediate mappings as needed."""
    cursor = target
    for key in keys[:-1]:
        nested = cursor.setdefault(key, {})
        if not isinstance(nested, dict):
            raise ConfigError(f"override path conflicts with a scalar at '{key}'")
        cursor = nested
    cursor[keys[-1]] = value


def env_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Collect ``MMLSA_*`` environment variables into a nested override mapping."""
    source = environ if environ is not None else dict(os.environ)
    overrides: dict[str, Any] = {}

    for name, raw in source.items():
        if not name.startswith(ENV_PREFIX) or name in SECRET_ENV_VARS or name in RESERVED_ENV_VARS:
            continue
        path = name[len(ENV_PREFIX) :].split(_LEVEL_SEPARATOR)
        if not all(path):
            raise ConfigError(f"malformed environment override: {name}")
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{name} is not a valid value: {exc}") from exc
        _assign(overrides, canonical_key_path(path), value)

    return overrides


def parse_set_options(assignments: list[str] | None) -> dict[str, Any]:
    """Turn ``--set llm.provider=fake`` style assignments into a nested override mapping."""
    overrides: dict[str, Any] = {}
    for assignment in assignments or []:
        key, separator, raw = assignment.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"--set expects 'dotted.key=value', got '{assignment}'")
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ConfigError(f"--set {key}: value is not valid: {exc}") from exc
        _assign(overrides, canonical_key_path(key.strip().split(".")), value)
    return overrides


def build_config(
    config_path: str | Path,
    *,
    provider: str | None = None,
    mode: str | None = None,
    seed: int | None = None,
    set_options: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> Config:
    """Resolve the configuration from every source, in precedence order.

    Named CLI flags and ``--set`` are both CLI-level; ``--set`` is applied last so that it can reach
    keys that have no dedicated flag.
    """
    overrides = env_overrides(environ)

    cli: dict[str, Any] = {}
    if provider is not None:
        _assign(cli, ["llm", "provider"], provider)
    if mode is not None:
        _assign(cli, ["llm", "mode"], mode)
    if seed is not None:
        _assign(cli, ["run", "seed"], seed)

    for layer in (cli, parse_set_options(set_options)):
        overrides = _merge(overrides, layer)

    return load_config(config_path, overrides)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two override mappings, matching the loader's semantics."""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge(existing, value)
        else:
            merged[key] = value
    return merged
