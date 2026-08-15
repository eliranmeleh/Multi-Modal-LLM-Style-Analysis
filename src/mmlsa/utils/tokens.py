"""Token estimation, and the deterministic packing of whole creations into calls.

The running corpus is roughly 1.065 million words, about 1.4 million tokens, so it does not fit any
current context window in one call. Splitting is therefore the **normal path**, not a rare fallback
(``docs/DECISIONS.md`` I3), and the way it splits has to be reproducible: if two runs packed the
creations differently, their profiles would differ for reasons that have nothing to do with the
method.

See ``docs/SPEC.md`` section 3 Step 1, and ``docs/DATA.md`` section 7.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TOKENS_PER_WORD = 1.35
"""Words to tokens, deliberately conservative.

Archaic orthography, elision and unusual proper nouns all tokenize worse than plain contemporary
prose, and under-estimating here would overfill a call and truncate a creation, which the
specification forbids outright. Overshooting merely costs one extra call.
"""

DEFAULT_CONTEXT_FRACTION = 0.70
"""Share of the context window available for input, leaving room for the response."""


class PackingError(Exception):
    """Raised when the creations cannot be packed under the configured budget."""


def estimate_tokens(text: str, tokens_per_word: float = DEFAULT_TOKENS_PER_WORD) -> int:
    """Estimate the token count of a text from its word count.

    Used when the provider offers no counting endpoint. Counts are cached in the manifest so that
    packing is stable across runs rather than being re-estimated each time.
    """
    return int(len(text.split()) * tokens_per_word)


def context_budget(context_window: int, fraction: float = DEFAULT_CONTEXT_FRACTION) -> int:
    """How many input tokens one call may carry, given a model's context window."""
    return int(context_window * fraction)


@dataclass(frozen=True)
class Bin:
    """One extraction call: the creations it carries and their total estimated size."""

    index: int
    creation_ids: tuple[str, ...]
    tokens: int

    @property
    def size(self) -> int:
        """How many creations are in this call."""
        return len(self.creation_ids)


def pack_creations(
    sizes: dict[str, int],
    budget: int,
    *,
    prompt_overhead_tokens: int = 0,
) -> list[Bin]:
    """Pack whole creations into as few calls as possible, deterministically.

    First-fit-decreasing: creations are ordered by estimated size descending, ties broken by
    identifier ascending, and each is placed into the first call that still has room. This is the
    order the specification names, and it is fully determined by the inputs, so the same corpus and
    the same budget always produce the same packing on any machine.

    **No creation is ever split.** The specification is explicit that a call holds complete
    creations and that there is no truncation and no sampling: an extra call is cheaper than losing
    text integrity (``docs/DECISIONS.md`` S5). A creation that cannot fit a call on its own is
    therefore an error, not something to trim.
    """
    if budget <= 0:
        raise PackingError(f"context budget must be positive, got {budget}")

    usable = budget - prompt_overhead_tokens
    if usable <= 0:
        raise PackingError(
            f"the prompt template alone needs {prompt_overhead_tokens} tokens, which exceeds the "
            f"budget of {budget}"
        )

    oversized = {name: size for name, size in sizes.items() if size > usable}
    if oversized:
        detail = ", ".join(f"{name} ({size:,} tokens)" for name, size in sorted(oversized.items()))
        raise PackingError(
            f"these creations do not fit a single call of {usable:,} tokens: {detail}. "
            "The specification forbids truncating a creation, so either the context budget must "
            "rise or a model with a larger window must be used."
        )

    ordered = sorted(sizes.items(), key=lambda item: (-item[1], item[0]))

    bins: list[list[str]] = []
    loads: list[int] = []
    for creation_id, size in ordered:
        for index, load in enumerate(loads):
            if load + size <= usable:
                bins[index].append(creation_id)
                loads[index] = load + size
                break
        else:
            bins.append([creation_id])
            loads.append(size)

    # Within a call, present creations in identifier order. The assignment is fixed by the
    # first-fit-decreasing pass above; ordering inside the call is a separate, equally deterministic
    # choice, and identifier order is the one a reader can predict.
    return [
        Bin(index=index, creation_ids=tuple(sorted(members)), tokens=load)
        for index, (members, load) in enumerate(zip(bins, loads, strict=True))
    ]


def packing_summary(bins: list[Bin]) -> dict[str, object]:
    """A record of a packing, for the run artifacts."""
    return {
        "n_calls": len(bins),
        "bins": [
            {
                "index": b.index,
                "n_creations": b.size,
                "tokens": b.tokens,
                "creation_ids": list(b.creation_ids),
            }
            for b in bins
        ],
        "total_tokens": sum(b.tokens for b in bins),
    }
