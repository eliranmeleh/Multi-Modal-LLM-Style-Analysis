"""Prompt templates: loading, versioning and deterministic rendering.

The templates are the approved book's own text (section 5.2), reproduced verbatim as files rather
than as string literals inside logic, so that they are reviewable, diffable and hashable. Nothing in
this package edits them; it only fills placeholders.

Two properties matter and are tested:

*Neutrality.* No pipeline prompt may name the target author, a period or a dialect. That is what
makes the method unsupervised and transferable, and it is the single most important property to
preserve. The control experiment's Mode B is the one deliberate exception, and it takes the name
from configuration at render time rather than from any source file.

*Versioning.* Each template carries a version in ``versions.json`` which becomes part of the LLM
cache key. Editing a template without bumping its version would silently serve responses generated
by the old wording, which is the kind of error that never surfaces as a failure, only as a number.

See ``docs/PROMPTS.md``.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from string import Template

PROFILE_EXTRACT = "profile_extract"
PROFILE_EXTRACT_SUFFIX = "profile_extract_structured_suffix"
PROFILE_MERGE = "profile_merge"
REWRITE = "rewrite"
REWRITE_RETRY = "rewrite_retry"
REWRITE_GENERIC = "rewrite_generic"

PIPELINE_TEMPLATES = (
    PROFILE_EXTRACT,
    PROFILE_EXTRACT_SUFFIX,
    PROFILE_MERGE,
    REWRITE,
    REWRITE_RETRY,
)
"""Templates used by the method itself. Every one must pass the neutrality test."""

CONTROL_TEMPLATES = (REWRITE_GENERIC,)
"""Mode B of the control experiment. Names the author on purpose; excluded from neutrality."""

PROFILE_KEYS = (
    "vocabulary",
    "pronouns",
    "verb_forms",
    "sentence_structure",
    "punctuation",
    "other",
)
"""The six keys, in the order of the book's own prompt bullets. Order is fixed so that rendering a
profile into a rewrite prompt is deterministic and cannot leak nondeterminism into the cache key."""


class PromptError(Exception):
    """Raised for a missing template, an unknown version, or an unfilled placeholder."""


@cache
def _versions() -> dict[str, int]:
    """The template version map, read once."""
    payload = json.loads(
        resources.files(__package__).joinpath("versions.json").read_text(encoding="utf-8")
    )
    return {name: value for name, value in payload.items() if not name.startswith("_")}


@cache
def load_template(name: str) -> str:
    """Read one template file verbatim."""
    try:
        return resources.files(__package__).joinpath(f"{name}.txt").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptError(f"no prompt template named '{name}'") from exc


def template_version(name: str) -> int:
    """The version of one template, which forms part of the cache key."""
    versions = _versions()
    if name not in versions:
        raise PromptError(
            f"template '{name}' has no recorded version. Every template must be versioned in "
            "src/mmlsa/prompts/versions.json; see docs/PROMPTS.md section 0."
        )
    return versions[name]


def all_template_names() -> tuple[str, ...]:
    """Every versioned template."""
    return tuple(sorted(_versions()))


def render(name: str, **values: str) -> str:
    """Fill a template's placeholders.

    Uses ``substitute`` rather than ``safe_substitute``: an unfilled placeholder is a bug that would
    otherwise reach a model as the literal text ``$passage``, and the model would answer anyway.
    """
    try:
        return Template(load_template(name)).substitute(**values)
    except KeyError as exc:
        raise PromptError(f"template '{name}' has an unfilled placeholder: {exc}") from exc


def render_creations(creations: list[tuple[str, str]]) -> str:
    """Render the ``$creations`` block for the extraction prompt.

    Numbered from one within the call, matching the book's illustration. The identifier is **not**
    included: a creation id such as a play's title would put the author's work back into a prompt
    that is required to name nothing. The packing record in the run artifacts is what maps positions
    back to creations.
    """
    return "\n\n".join(
        f"Creation {position}: {text}" for position, (_, text) in enumerate(creations, start=1)
    )


def render_partial_profiles(profiles: list[dict[str, str] | str]) -> str:
    """Render the ``$partial_profiles`` block for the merge call."""
    blocks = []
    for position, profile in enumerate(profiles, start=1):
        body = profile if isinstance(profile, str) else serialize_profile(profile)
        blocks.append(f"Analysis {position}:\n{body}")
    return "\n\n".join(blocks)


def serialize_profile(profile: dict[str, str]) -> str:
    """Render a structured profile as stable labelled lines.

    Never dump raw JSON into a rewrite prompt: it changes the register of the instruction, and key
    ordering would leak nondeterminism into the cache key. Fixed key order, human-readable labels.
    """
    labels = {
        "vocabulary": "Vocabulary",
        "pronouns": "Pronouns",
        "verb_forms": "Verb forms",
        "sentence_structure": "Sentence structure",
        "punctuation": "Punctuation",
        "other": "Other features",
    }
    return "\n".join(f"{labels[key]}: {profile[key]}" for key in PROFILE_KEYS if profile.get(key))
