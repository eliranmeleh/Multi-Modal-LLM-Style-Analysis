"""Configuration model and loader.

One Pydantic model, one YAML file, CLI overrides on top.
Precedence: CLI > environment > YAML > model defaults.

Two properties matter more than the field list, and both are tested:

*Unknown keys are an error.* Every model forbids extras, so a key added to a child config but never
declared here fails at startup instead of being silently ignored for the rest of the project.

*The hash identifies the effective values, not the inheritance path.* Two configs that resolve to the
same mapping produce the same hash and therefore the same run id, whichever files they inherited
from. Paths are kept relative for exactly this reason: an absolute path would make the hash
machine-dependent and no two people could reproduce each other's run id.

See ``docs/ARCHITECTURE.md`` section 7 and ``docs/DECISIONS.md`` I16.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from mmlsa.utils.hashing import hash_payload

MAX_EXTENDS_DEPTH = 8
"""Hard cap on the ``extends`` chain, so a mistake surfaces as an error rather than a recursion."""


class ConfigError(Exception):
    """Raised for any malformed configuration. Always fatal, always at startup."""


class _Base(BaseModel):
    """Common model settings: unknown keys are rejected, values are validated on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------------------- groups


class CorpusConfig(_Base):
    """The texts under analysis. ``author_label`` is for output labels and Mode B only (R1, I9)."""

    author_label: str = "Author"
    dir: str = "data/corpus"
    sources: str = "data/corpus_sources.yaml"
    manifest: str = "data/manifest.json"
    expected_count: int = Field(default=49, ge=1)
    include_ids: list[str] | None = None
    exclude_ids: list[str] = Field(default_factory=list)


class ChunkingConfig(_Base):
    """Step 2. ``P`` is the chunk length in words; the spec range is 200 to 600."""

    P: int = Field(default=400, ge=1)
    merge_short_tail: bool = False
    min_chunk_words: int = Field(default=1, ge=1)


class ProfileConfig(_Base):
    """Step 1. ``context_budget_tokens`` of None means 0.70 of the provider's context window."""

    structured_output: bool = True
    context_budget_tokens: int | None = Field(default=None, ge=1)
    tokens_per_word: float = Field(default=1.35, gt=0)
    merge_when_multiple: bool = True
    max_output_tokens: int = Field(default=4096, ge=1)


class RewriteValidationConfig(_Base):
    """Thresholds for accepting a rewrite. See ``docs/SPEC.md`` Step 3 and ``DECISIONS.md`` I5."""

    min_length_ratio: float = Field(default=0.60, ge=0)
    max_length_ratio: float = Field(default=1.60, gt=0)
    min_content_retention: float = Field(default=0.50, ge=0, le=1)
    strip_preamble: bool = True
    strip_code_fences: bool = True

    @model_validator(mode="after")
    def _ratios_ordered(self) -> RewriteValidationConfig:
        if self.min_length_ratio >= self.max_length_ratio:
            raise ValueError(
                f"rewrite.validation.min_length_ratio ({self.min_length_ratio}) must be below "
                f"max_length_ratio ({self.max_length_ratio})"
            )
        return self


class RewriteConfig(_Base):
    """Step 3. ``max_retries`` counts content-validation retries only; transport retries are separate."""

    max_output_tokens: int = Field(default=2048, ge=1)
    max_retries: int = Field(default=2, ge=0)
    validation: RewriteValidationConfig = Field(default_factory=RewriteValidationConfig)
    max_failed_fraction: float = Field(default=0.02, ge=0, le=1)


class DistanceConfig(_Base):
    """Step 4. The metric is chosen through the registry; ``fwed`` is the one the method uses."""

    metric: Literal["fwed", "fw_freq_cosine", "fw_freq_manhattan", "signal"] = "fwed"
    function_words: str = "data/function_words/en_core_v1.txt"
    store_edit_detail_sample: int = Field(default=200, ge=0)


class AggregateConfig(_Base):
    """Step 5. ``std_ddof`` of 1 is the sample standard deviation the spec asks for."""

    chunk_reduce: Literal["mean"] = "mean"
    run_reduce: Literal["mean"] = "mean"
    std_ddof: int = Field(default=1, ge=0)
    report_length_weighted: bool = True


class ClassifyConfig(_Base):
    """Step 6. ``otsu_exact`` enumerates the N-1 splits rather than binning (I2)."""

    method: Literal["otsu_exact", "otsu_skimage", "gmm_2", "manual"] = "otsu_exact"
    cross_check_skimage: bool = True
    otsu_agreement_tol: float = Field(default=0.005, ge=0)
    borderline_band: float = Field(default=0.01, ge=0)
    manual_tau: float | None = None
    bimodality_min_separability: float = Field(default=0.5, ge=0, le=1)
    bimodality_min_gap_ratio: float = Field(default=0.5, ge=0)

    @model_validator(mode="after")
    def _manual_needs_tau(self) -> ClassifyConfig:
        if self.method == "manual" and self.manual_tau is None:
            raise ValueError("classify.method is 'manual' but classify.manual_tau is not set")
        return self


class NoiseConfig(_Base):
    """The main proposal: one different foreign creation per run from run 2 onward, non-cumulative."""

    enabled: bool = True
    pool_dir: str = "data/noise_pool"
    first_run_plain: bool = True
    cumulative: bool = False
    score_injected_text: bool = True


class LLMConfig(_Base):
    """The provider is one key (R4). No API key ever appears here; keys come from the environment."""

    provider: Literal["gemini", "openai", "anthropic", "fake", "replay"] = "gemini"
    model_id: str | None = None
    temperature: float = Field(default=0.0, ge=0)
    mode: Literal["live", "replay", "refresh"] = "live"
    cache_dir: str = "cache"
    concurrency: int = Field(default=8, ge=1)
    requests_per_minute: int = Field(default=240, ge=1)
    tokens_per_minute: int = Field(default=1_000_000, ge=1)
    max_transient_retries: int = Field(default=5, ge=0)
    timeout_seconds: int = Field(default=120, ge=1)


class RunConfig(_Base):
    """``M`` independent runs; the spec range is 3 to 5. ``seed`` drives every sampling decision (R8)."""

    M: int = Field(default=3, ge=1)
    seed: int = 20260731
    out_dir: str = "runs"
    tag: str = ""


class ReportConfig(_Base):
    """Reporting inputs. The prior findings are a comparison target only, never a pipeline input."""

    figures: bool = True
    compare_to_prior: str = "data/prior_findings.yaml"
    consensus_cases: str = "data/consensus_cases.yaml"
    formats: list[Literal["csv", "md"]] = Field(
        default_factory=lambda: cast("list[Literal['csv', 'md']]", ["csv", "md"])
    )


class PurificationConfig(_Base):
    """Optional Stage 4. Not part of the Phase A method, which is single round (S1)."""

    enabled: bool = False
    T_max: int = Field(default=5, ge=1)
    stop_when_unchanged_for: int = Field(default=1, ge=1)
    report_set_differences: bool = True


class ControlExperimentConfig(_Base):
    """Stage 5, Mode A against Mode B, paired by chunk."""

    sample_chunks: int = Field(default=300, ge=1)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    stratify: bool = True
    report_power: bool = True


class SensitivityExperimentConfig(_Base):
    """Stage 2. Each ``P`` value invalidates the rewrite cache, so the sweep is priced deliberately."""

    P_values: list[int] = Field(default_factory=lambda: [200, 300, 400, 500, 600])
    M_values: list[int] = Field(default_factory=lambda: [3, 5])


class MixtureExperimentConfig(_Base):
    """The synthetic mixture test: foreign passages spliced at known positions."""

    n_splices: int = Field(default=3, ge=1)
    splice_words: int = Field(default=800, ge=1)


class CalibrationExperimentConfig(_Base):
    """The reproducibility check: repeat rewrites of the same chunks and measure the spread."""

    sample_chunks: int = Field(default=100, ge=1)
    repeats: int = Field(default=5, ge=2)
    max_cv: float = Field(default=0.15, gt=0)


class ExperimentConfig(_Base):
    """Parameters for the validation experiments in ``docs/EXPERIMENTS.md``."""

    control: ControlExperimentConfig = Field(default_factory=ControlExperimentConfig)
    sensitivity: SensitivityExperimentConfig = Field(default_factory=SensitivityExperimentConfig)
    mixture: MixtureExperimentConfig = Field(default_factory=MixtureExperimentConfig)
    calibration: CalibrationExperimentConfig = Field(default_factory=CalibrationExperimentConfig)


# ------------------------------------------------------------------------------------ root model


class Config(_Base):
    """The fully resolved configuration. Only this flattened form is validated, hashed and snapshotted."""

    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    rewrite: RewriteConfig = Field(default_factory=RewriteConfig)
    distance: DistanceConfig = Field(default_factory=DistanceConfig)
    aggregate: AggregateConfig = Field(default_factory=AggregateConfig)
    classify: ClassifyConfig = Field(default_factory=ClassifyConfig)
    noise: NoiseConfig = Field(default_factory=NoiseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    purification: PurificationConfig = Field(default_factory=PurificationConfig)
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)

    _root: Path = PrivateAttr(default_factory=Path.cwd)
    _source: Path | None = PrivateAttr(default=None)

    # -- identity -------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The resolved configuration as plain data, with defaults expanded."""
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        """sha256 over the resolved configuration. Two equivalent configs hash identically."""
        return hash_payload(self.to_dict())

    # -- paths ----------------------------------------------------------------------------------

    @property
    def root(self) -> Path:
        """The project root that relative paths in this config are resolved against."""
        return self._root

    def path(self, relative: str) -> Path:
        """Resolve a config path value against the project root.

        Paths are stored relative so that the config hash is identical on every machine; they become
        absolute only here, at the point of use.
        """
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else (self._root / candidate)

    def bind_root(self, root: Path) -> Config:
        """Attach the project root. Returns self for chaining."""
        self._root = root
        return self


# ---------------------------------------------------------------------------------------- loader


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge ``override`` onto ``base``: mappings merge, everything else replaces.

    Lists replace rather than concatenate, deliberately. A merged ``include_ids`` would silently
    widen a run, which is the kind of error that is only noticed after the compute is spent.
    ``None`` is a value: ``include_ids: null`` in a child means the whole corpus and overrides a
    parent's subset.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping, with a readable error for anything that is not one."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(
            f"{path} must contain a mapping at the top level, got {type(loaded).__name__}"
        )
    return loaded


def resolve_extends(path: Path, _chain: list[Path] | None = None) -> dict[str, Any]:
    """Resolve a config file and its ``extends`` ancestry into one flat mapping.

    ``extends`` is a loader directive, not a config field: it is stripped here and never reaches the
    model. Parents are resolved fully before the child is applied, so chains work to any depth up to
    ``MAX_EXTENDS_DEPTH``. A cycle is a startup error reporting the full chain.
    """
    chain = list(_chain or [])
    resolved_path = path.resolve()

    if resolved_path in chain:
        loop = " -> ".join(p.name for p in [*chain, resolved_path])
        raise ConfigError(f"cyclic 'extends' in configuration: {loop}")
    if len(chain) >= MAX_EXTENDS_DEPTH:
        loop = " -> ".join(p.name for p in [*chain, resolved_path])
        raise ConfigError(f"'extends' chain deeper than {MAX_EXTENDS_DEPTH}: {loop}")

    mapping = _read_yaml(resolved_path)
    parent_ref = mapping.pop("extends", None)
    if parent_ref is None:
        return mapping

    if not isinstance(parent_ref, str):
        raise ConfigError(
            f"{resolved_path}: 'extends' must be a filename, got {type(parent_ref).__name__}"
        )

    parent_path = (resolved_path.parent / parent_ref).resolve()
    parent = resolve_extends(parent_path, [*chain, resolved_path])
    return _deep_merge(parent, mapping)


def find_project_root(start: Path) -> Path:
    """Walk upward from ``start`` to the directory holding ``pyproject.toml``.

    Relative paths in a config are interpreted against this directory, so a run behaves the same
    whichever subdirectory it was launched from.
    """
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return start


def load_config(
    path: str | Path,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """Load, resolve, override and validate a configuration file.

    ``overrides`` carries CLI and environment values as a nested mapping and is applied last, so the
    precedence is CLI > environment > YAML > model defaults.
    """
    config_path = Path(path).resolve()
    mapping = resolve_extends(config_path)

    if overrides:
        mapping = _deep_merge(mapping, overrides)

    try:
        config = Config.model_validate(mapping)
    except Exception as exc:  # pydantic ValidationError, re-raised with the file that caused it
        raise ConfigError(f"invalid configuration in {config_path}:\n{exc}") from exc

    root = find_project_root(config_path.parent)
    config.bind_root(root)
    config._source = config_path
    return config
