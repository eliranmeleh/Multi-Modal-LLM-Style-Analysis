"""Prompt neutrality.

No pipeline prompt may name the target author, a period or a dialect. This is what makes the method
unsupervised and transferable, and it is the single most important property to preserve: a prompt
that leaks a name turns the whole measurement into a test of what the model already knows.

The templates are rendered with realistic placeholder values before being scanned, because a
template that is neutral empty can still be made to name someone once it is filled — which is
exactly what would happen if a creation identifier were rendered into the extraction prompt.

The control experiment's Mode B is the one deliberate exception and is checked separately: it must
name the author, and must take the name from configuration rather than from any source file.
"""

from __future__ import annotations

import re

import pytest

from mmlsa import prompts
from mmlsa.pipeline.profile import build_extraction_request, build_merge_request, parse_profile
from tests.conftest import REPO_ROOT

FORBIDDEN_TERMS_FILE = REPO_ROOT / "tests" / "forbidden_terms.txt"


def forbidden_terms() -> list[str]:
    """The same list the source-tree check uses."""
    lines = FORBIDDEN_TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [stripped for line in lines if (stripped := line.split("#", 1)[0].strip().lower())]


def contains(text: str, term: str) -> bool:
    """Word-boundary, case-insensitive match."""
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


REALISTIC_VALUES = {
    "creations": "Creation 1: To be, or not to be, that is the question.",
    "partial_profiles": "Analysis 1:\nVocabulary: plain and concrete.",
    "profile": "Vocabulary: plain and concrete.\nPronouns: second person singular.",
    "passage": "Thou hast the letter, and thou dost not read it.",
    "author_label": "Shakespeare",
}


def render_realistically(name: str) -> str:
    """Render a template, supplying only the placeholders it actually declares."""
    body = prompts.load_template(name)
    needed = {key: value for key, value in REALISTIC_VALUES.items() if f"${key}" in body}
    return prompts.render(name, **needed)


# --------------------------------------------------------------------------------- the guarantee


def test_the_forbidden_list_and_the_templates_are_both_populated() -> None:
    """Guards against the whole check passing because it found nothing to scan."""
    assert len(forbidden_terms()) >= 10
    assert len(prompts.PIPELINE_TEMPLATES) >= 5


@pytest.mark.parametrize("template", prompts.PIPELINE_TEMPLATES)
def test_a_rendered_pipeline_prompt_names_nobody(template: str) -> None:
    """Every template the method itself uses, filled with realistic values."""
    rendered = render_realistically(template)
    offenders = [term for term in forbidden_terms() if contains(rendered, term)]

    assert not offenders, f"'{template}' leaks {offenders} once rendered:\n{rendered}"


def test_the_extraction_prompt_omits_creation_identifiers() -> None:
    """A creation identifier is as much of a cue as an author's name.

    The creations are rendered positionally, and the packing record in the run artifacts is what
    maps positions back to identifiers. This is the specific way a neutral template could have been
    made to leak.
    """
    request = build_extraction_request(
        [("hamlet", "To be, or not to be."), ("macbeth", "Is this a dagger which I see?")]
    )

    assert "Creation 1:" in request.prompt
    assert "Creation 2:" in request.prompt
    for identifier in ("hamlet", "macbeth"):
        assert not contains(request.prompt, identifier)


def test_the_merge_prompt_forbids_naming_anyone() -> None:
    """The merge call is an addition to the specified method, so it carries the rule explicitly."""
    body = prompts.load_template(prompts.PROFILE_MERGE)

    assert "Do not name any author, period, or literary tradition." in body


def test_the_merge_request_carries_no_forbidden_term() -> None:
    """Rendered with partial profiles, which are model output and could in principle name someone."""
    from mmlsa.pipeline.profile import StyleProfile

    partials = [
        StyleProfile(fields={"vocabulary": "plain and concrete", "pronouns": "second person"}),
        StyleProfile(fields={"vocabulary": "elevated and latinate", "pronouns": "first person"}),
    ]
    request = build_merge_request(partials)

    assert not [term for term in forbidden_terms() if contains(request.prompt, term)]


# ------------------------------------------------------------------------------- the exception


def test_mode_b_is_the_only_template_that_names_the_author() -> None:
    """The control experiment exists to invoke the memorized prior, so it must name the author."""
    rendered = prompts.render(
        prompts.REWRITE_GENERIC, author_label="Shakespeare", passage="a passage"
    )

    assert contains(rendered, "shakespeare")
    assert prompts.REWRITE_GENERIC not in prompts.PIPELINE_TEMPLATES
    assert prompts.REWRITE_GENERIC in prompts.CONTROL_TEMPLATES


def test_mode_b_takes_the_name_from_configuration_not_from_the_template() -> None:
    """No author name appears in any source file, including the template that has to use one."""
    body = prompts.load_template(prompts.REWRITE_GENERIC)

    assert "$author_label" in body
    assert not [term for term in forbidden_terms() if contains(body, term)]


# -------------------------------------------------------------------------------- the templates


def test_every_template_is_versioned() -> None:
    """The version forms part of the cache key; an unversioned template cannot be invalidated."""
    for name in [*prompts.PIPELINE_TEMPLATES, *prompts.CONTROL_TEMPLATES]:
        assert prompts.template_version(name) >= 1


def test_the_version_map_and_the_template_files_agree() -> None:
    """A template file with no version entry, or a version entry with no file, is a mistake."""
    for name in prompts.all_template_names():
        assert prompts.load_template(name).strip(), f"{name} is empty"


def test_the_extraction_template_is_the_books_own_text() -> None:
    """Verbatim from the approved book, section 5.2. Changing it is a change to the method."""
    body = prompts.load_template(prompts.PROFILE_EXTRACT)

    assert body.startswith("Analyze the dominant writing style in the following creations.")
    for bullet in (
        "- Word choice and vocabulary preferences",
        "- Pronoun usage patterns",
        "- Verb forms and conjugations",
        "- Sentence structure and length",
        "- Punctuation habits",
        "- Any other distinctive linguistic features",
    ):
        assert bullet in body
    assert "$creations" in body


def test_the_rewrite_template_is_the_books_own_text() -> None:
    """Verbatim from the approved book, section 5.2."""
    body = prompts.load_template(prompts.REWRITE)

    assert "Rewrite the following passage to match this style profile exactly." in body
    assert "Do not paraphrase or change content words." in body
    assert "$profile" in body
    assert "$passage" in body


def test_an_unfilled_placeholder_is_an_error_not_a_literal_dollar_sign() -> None:
    """A model would answer a prompt containing the literal text ``$passage`` without complaint."""
    with pytest.raises(prompts.PromptError, match="unfilled placeholder"):
        prompts.render(prompts.REWRITE, profile="a profile")


def test_an_unknown_template_is_reported_by_name() -> None:
    """So a typo fails at startup rather than as an empty prompt."""
    with pytest.raises(prompts.PromptError, match="no prompt template"):
        prompts.load_template("not_a_template")


# ------------------------------------------------------------------- profile serialization


def test_a_profile_renders_as_labelled_lines_not_raw_json() -> None:
    """Raw JSON would change the register of the instruction and leak key ordering into the key."""
    rendered = prompts.serialize_profile(
        {
            "vocabulary": "plain",
            "pronouns": "second person",
            "verb_forms": "older endings",
            "sentence_structure": "long clauses",
            "punctuation": "heavy commas",
            "other": "regular metre",
        }
    )

    assert rendered.startswith("Vocabulary: plain")
    assert "{" not in rendered
    assert '"vocabulary"' not in rendered


def test_profile_rendering_is_order_stable() -> None:
    """Two dictionaries with the same content must render identically, whatever their insertion order."""
    forward = {key: key.upper() for key in prompts.PROFILE_KEYS}
    backward = {key: key.upper() for key in reversed(prompts.PROFILE_KEYS)}

    assert prompts.serialize_profile(forward) == prompts.serialize_profile(backward)


def test_a_parsed_profile_round_trips_into_a_prompt() -> None:
    """The path a real profile takes: model output, parsed, rendered into the next call."""
    response = '{"vocabulary": "plain", "pronouns": "second person", "verb_forms": "older", '
    response += '"sentence_structure": "long", "punctuation": "commas", "other": "metre"}'

    profile = parse_profile(response)
    rendered = prompts.render(prompts.REWRITE, profile=profile.render(), passage="a passage")

    assert profile.structured
    assert "Vocabulary: plain" in rendered
    assert "a passage" in rendered
