"""The LLM layer: provider protocol, cache, ledger and runner.

Every call the pipeline makes passes through this package, and through the cache and the ledger
without exception (R2, R3). Nothing under ``src/mmlsa/pipeline/`` imports a concrete provider.
"""

from mmlsa.llm.base import (
    CacheMissError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, build_entry, read_ledger, summarize, validate_line
from mmlsa.llm.providers import available, build_provider
from mmlsa.llm.runner import Job, JobResult, Runner

__all__ = [
    "CacheMissError",
    "Job",
    "JobResult",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "Ledger",
    "PermanentProviderError",
    "ProviderError",
    "ResponseCache",
    "Runner",
    "TransientProviderError",
    "available",
    "build_entry",
    "build_provider",
    "read_ledger",
    "summarize",
    "validate_line",
]
