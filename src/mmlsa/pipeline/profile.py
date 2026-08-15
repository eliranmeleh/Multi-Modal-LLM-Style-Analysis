"""Step 1 — style-profile extraction.

The LLM receives the full text of every creation in the corpus and describes the dominant style.
Whole creations only: no truncation and no sampling. When the corpus exceeds the context window it
is split across several calls, each holding complete creations, and the partial profiles are then
consolidated by one merge call.

Three properties are load-bearing and each is tested:

*The prompt names nobody.* No author, period or dialect reaches the model. This is what makes the
method unsupervised and transferable, and it is why the creation identifiers are omitted from the
rendered prompt: a title is as much of a cue as a name.

*The packing is deterministic.* Two runs over the same corpus with the same budget produce the same
calls, so a difference between runs is a difference in the model, not in how the text was divided.

*The profile is re-extracted per run.* Each of the `M` runs gets its own independent profile, which
is what the averaging in Step 5 is cancelling.

See ``docs/SPEC.md`` section 3 Step 1, and ``docs/DECISIONS.md`` I3 and I4.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from mmlsa import prompts
from mmlsa.llm.base import LLMRequest
from mmlsa.llm.runner import Job, Runner
from mmlsa.utils.logging import get_logger
from mmlsa.utils.text import strip_code_fences
from mmlsa.utils.tokens import Bin, context_budget, estimate_tokens, pack_creations, packing_summary

logger = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class ProfileError(Exception):
    """Raised when a profile cannot be extracted or parsed."""


@dataclass
class StyleProfile:
    """One run's style profile, structured or free text."""

    fields: dict[str, str] = field(default_factory=dict)
    free_text: str = ""
    structured: bool = True

    def render(self) -> str:
        """The profile as it appears inside a rewrite prompt."""
        return prompts.serialize_profile(self.fields) if self.structured else self.free_text

    def to_dict(self) -> dict[str, Any]:
        """Plain data, for the run artifacts."""
        return {"structured": self.structured, "fields": self.fields, "free_text": self.free_text}

    @property
    def is_empty(self) -> bool:
        """Whether the profile carries nothing a rewrite could be conditioned on."""
        return not self.render().strip()


@dataclass
class ProfileResult:
    """Everything Step 1 produced for one run, written to ``runs/<run_id>/profiles/``."""

    run_index: int
    profile: StyleProfile
    partials: list[StyleProfile]
    packing: dict[str, Any]
    merged: bool
    noise_creation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Plain data, for the run artifacts."""
        return {
            "run_index": self.run_index,
            "merged": self.merged,
            "noise_creation_id": self.noise_creation_id,
            "packing": self.packing,
            "profile": self.profile.to_dict(),
            "partials": [partial.to_dict() for partial in self.partials],
        }


# ------------------------------------------------------------------------------------- parsing


def parse_profile(text: str, *, structured: bool = True) -> StyleProfile:
    """Parse a model's profile response.

    With ``structured`` set, a JSON object with the six documented keys is expected. A response that
    cannot be parsed **falls back to free text** rather than failing the run: the book's literal form
    is free text anyway, so a profile that does not parse is still a usable profile, and losing a
    whole run over a formatting slip would be a poor trade. The fallback is recorded so it is
    visible rather than silent.
    """
    cleaned = strip_code_fences(text)

    if not structured:
        return StyleProfile(free_text=cleaned, structured=False)

    candidate = cleaned
    if not candidate.startswith("{"):
        match = _JSON_BLOCK.search(cleaned)
        candidate = match.group(0) if match else ""

    if candidate:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            fields = {
                key: str(payload[key]).strip()
                for key in prompts.PROFILE_KEYS
                if isinstance(payload.get(key), str | int | float) and str(payload[key]).strip()
            }
            if fields:
                return StyleProfile(fields=fields, structured=True)

    logger.warning("profile.structured_parse_failed", chars=len(cleaned))
    return StyleProfile(free_text=cleaned, structured=False)


# -------------------------------------------------------------------------------------- packing


def plan_packing(
    texts: dict[str, str],
    *,
    context_window: int,
    budget_tokens: int | None = None,
    tokens_per_word: float = 1.35,
    context_fraction: float = 0.70,
) -> list[Bin]:
    """Decide how the corpus is divided across extraction calls.

    Pure and deterministic: no model is consulted, so a dry run can report the exact call count
    before anything is spent.
    """
    sizes = {name: estimate_tokens(text, tokens_per_word) for name, text in texts.items()}
    budget = budget_tokens or context_budget(context_window, context_fraction)
    overhead = estimate_tokens(prompts.load_template(prompts.PROFILE_EXTRACT), tokens_per_word)
    return pack_creations(sizes, budget, prompt_overhead_tokens=overhead)


# ----------------------------------------------------------------------------------- extraction


def build_extraction_request(
    creations: list[tuple[str, str]],
    *,
    structured: bool = True,
    max_output_tokens: int = 4096,
    temperature: float = 0.0,
) -> LLMRequest:
    """Render one extraction call.

    The creations are rendered positionally and their identifiers are omitted, so no title reaches
    the model. See the neutrality rule in ``docs/PROMPTS.md`` section 0.
    """
    prompt = prompts.render(prompts.PROFILE_EXTRACT, creations=prompts.render_creations(creations))
    version = prompts.template_version(prompts.PROFILE_EXTRACT)

    if structured:
        prompt += prompts.load_template(prompts.PROFILE_EXTRACT_SUFFIX)
        version += prompts.template_version(prompts.PROFILE_EXTRACT_SUFFIX)

    return LLMRequest(
        prompt=prompt,
        tag="profile",
        response_format="json" if structured else "text",
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        prompt_schema_version=version,
    )


def build_merge_request(
    partials: list[StyleProfile],
    *,
    max_output_tokens: int = 4096,
    temperature: float = 0.0,
) -> LLMRequest:
    """Render the consolidation call used when the corpus needed more than one extraction."""
    rendered = [p.fields if p.structured else p.render() for p in partials]
    return LLMRequest(
        prompt=prompts.render(
            prompts.PROFILE_MERGE, partial_profiles=prompts.render_partial_profiles(rendered)
        ),
        tag="profile_merge",
        response_format="json",
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        prompt_schema_version=prompts.template_version(prompts.PROFILE_MERGE),
    )


def extract_profile(
    texts: dict[str, str],
    runner: Runner,
    *,
    run_index: int = 1,
    structured: bool = True,
    budget_tokens: int | None = None,
    tokens_per_word: float = 1.35,
    context_fraction: float = 0.70,
    merge_when_multiple: bool = True,
    max_output_tokens: int = 4096,
    temperature: float = 0.0,
    noise_creation_id: str = "",
) -> ProfileResult:
    """Run Step 1 for one run and return the profile with its provenance.

    When the corpus fits one call the result is that call's profile. When it does not, each call
    yields a partial profile and one merge call consolidates them. The merge is an addition to the
    specified method, which describes the split but leaves the consolidation implicit; it is flagged
    for supervisor confirmation in ``docs/OPEN_QUESTIONS.md`` Q1.
    """
    if not texts:
        raise ProfileError("cannot extract a style profile from an empty corpus")

    bins = plan_packing(
        texts,
        context_window=runner.provider.context_window(),
        budget_tokens=budget_tokens,
        tokens_per_word=tokens_per_word,
        context_fraction=context_fraction,
    )
    packing = packing_summary(bins)

    logger.info(
        "profile.packing",
        run_index=run_index,
        n_calls=len(bins),
        n_creations=len(texts),
        total_tokens=packing["total_tokens"],
    )

    jobs = [
        Job(
            request=build_extraction_request(
                [(name, texts[name]) for name in b.creation_ids],
                structured=structured,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
            creation_id=f"__profile_bin_{b.index:03d}",
            run_index=run_index,
        )
        for b in bins
    ]

    results = runner.run(jobs)
    failures = [r for r in results if not r.ok]
    if failures:
        raise ProfileError(
            f"{len(failures)} of {len(jobs)} profile extraction calls failed in run {run_index}: "
            f"{failures[0].error}. Step 1 has no partial-failure mode: without a profile there is "
            "nothing to rewrite against."
        )

    partials = [
        parse_profile(r.response.text, structured=structured)
        for r in results
        if r.response is not None
    ]

    if len(partials) == 1 or not merge_when_multiple:
        return ProfileResult(
            run_index=run_index,
            profile=partials[0],
            partials=partials,
            packing=packing,
            merged=False,
            noise_creation_id=noise_creation_id,
        )

    merge = runner.complete(
        build_merge_request(partials, max_output_tokens=max_output_tokens, temperature=temperature),
        creation_id="__profile_merge",
        run_index=run_index,
    )
    if merge.response is None:
        raise ProfileError(f"the profile merge call failed in run {run_index}: {merge.error}")

    merged = parse_profile(merge.response.text, structured=structured)
    if merged.is_empty:
        raise ProfileError(
            f"the profile merge in run {run_index} returned nothing usable. Rewriting every chunk "
            "against an empty profile would measure nothing."
        )

    return ProfileResult(
        run_index=run_index,
        profile=merged,
        partials=partials,
        packing=packing,
        merged=True,
        noise_creation_id=noise_creation_id,
    )
