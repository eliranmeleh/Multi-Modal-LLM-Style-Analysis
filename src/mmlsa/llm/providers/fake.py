"""A deterministic offline provider, for development and for every test.

The temptation is to echo the input. Resist it: a fake that returns its argument makes every delta
exactly zero, and then the chunking, the distance, the aggregation and the threshold all appear to
work while measuring nothing. Every integration test downstream would pass on a pipeline that was
silently broken (``docs/TESTING.md`` section 4).

So this provider does something small but real. It seeds a random generator from the hash of the
prompt and substitutes function words at a rate that also derives from that hash. The result is:

* **deterministic** - the same prompt always produces the same rewrite, on any machine;
* **non-trivial** - the deltas are not zero;
* **varied** - different chunks get different rates, so the scores spread out and a threshold has
  something to separate.

The substitution table is pairs of ordinary English function words. It encodes no author, period or
dialect, and `tests/test_no_hardcoded_author.py` enforces that.
"""

from __future__ import annotations

import random
import time
from typing import Any

from mmlsa.llm.base import LLMRequest, LLMResponse

SUBSTITUTIONS: dict[str, str] = {
    "you": "thou",
    "your": "thy",
    "yours": "thine",
    "are": "art",
    "have": "hast",
    "has": "hath",
    "do": "dost",
    "does": "doth",
    "did": "didst",
    "shall": "shalt",
    "will": "wilt",
    "can": "canst",
    "would": "wouldst",
    "should": "shouldst",
    "could": "couldst",
    "were": "wert",
    "upon": "on",
    "unto": "to",
    "among": "amongst",
    "while": "whilst",
}
"""Modern form to older form. Chosen so that a rewrite changes the function-word sequence, which is
the only thing the distance metric reads."""

MIN_RATE = 0.05
MAX_RATE = 0.45
"""The substitution rate varies within this band, derived from the prompt hash.

A single fixed rate would give every chunk almost the same delta, and the sorted scatter would be a
flat line with no gap for a threshold to find. Varying it produces a spread that exercises the
classifier for real.
"""

DEFAULT_CONTEXT_WINDOW = 1_000_000

PASSAGE_MARKER = "Passage to rewrite:"
"""Where the rewrite prompt's payload begins. See ``docs/PROMPTS.md`` section 3."""

FAKE_PROFILE = {
    "vocabulary": "A mid-length, largely concrete vocabulary with frequent doubling of near-synonyms.",
    "pronouns": "Second-person singular forms predominate over their modern equivalents.",
    "verb_forms": "Older inflected endings appear consistently in the second and third person.",
    "sentence_structure": "Long coordinated clauses, frequent inversion of subject and verb.",
    "punctuation": "Heavy use of the comma and the semicolon; few full stops within a speech.",
    "other": "A regular five-beat line, with frequent elision to preserve the count.",
}
"""A plausible structured profile, so that Step 1 can be exercised without a provider."""


class FakeProvider:
    """Deterministic, offline, and deliberately not an echo."""

    name = "fake"

    def __init__(self, model_id: str | None = None, **_: Any) -> None:
        self.model_id = model_id or "fake-1"
        self.calls = 0

    def context_window(self) -> int:
        """Large, so that packing logic can be exercised without artificial splitting."""
        return DEFAULT_CONTEXT_WINDOW

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Produce a deterministic response derived from the prompt."""
        started = time.perf_counter()
        self.calls += 1

        if request.response_format == "json" or request.tag in {"profile", "profile_merge"}:
            text = self._profile_response()
        else:
            text = self._rewrite(request.prompt)

        return LLMResponse(
            text=text,
            model_id=self.model_id,
            model_version=f"{self.model_id}-deterministic",
            input_tokens=len(request.prompt.split()),
            output_tokens=len(text.split()),
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason="stop",
            raw={"provider": self.name, "deterministic": True},
        )

    # -- response construction -----------------------------------------------------------------

    @staticmethod
    def _seed(prompt: str) -> int:
        """A stable integer seed derived from the prompt.

        Python's ``hash`` is salted per process and would make this provider non-reproducible across
        runs, which is the one property it exists to have.
        """
        from mmlsa.utils.hashing import hash_text

        return int(hash_text(prompt)[:16], 16)

    @staticmethod
    def _payload(prompt: str) -> str:
        """The passage to rewrite, if the prompt carries one, otherwise the whole prompt."""
        marker = prompt.rfind(PASSAGE_MARKER)
        return prompt[marker + len(PASSAGE_MARKER) :].strip() if marker >= 0 else prompt

    def _rewrite(self, prompt: str) -> str:
        """Substitute function words at a prompt-determined rate, preserving everything else."""
        seed = self._seed(prompt)
        rng = random.Random(seed)
        rate = MIN_RATE + (seed % 1000) / 1000 * (MAX_RATE - MIN_RATE)

        rewritten = []
        for token in self._payload(prompt).split():
            stripped = token.strip(".,;:!?\"'()[]").lower()
            replacement = SUBSTITUTIONS.get(stripped)
            if replacement is not None and rng.random() < rate:
                rewritten.append(token.lower().replace(stripped, replacement))
            else:
                rewritten.append(token)

        return " ".join(rewritten)

    @staticmethod
    def _profile_response() -> str:
        """A structured profile with the six keys the specification names."""
        import json

        return json.dumps(FAKE_PROFILE, indent=2)
