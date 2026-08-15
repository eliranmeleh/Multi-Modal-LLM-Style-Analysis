"""The six pipeline steps and the orchestrator that runs them.

Steps 2, 4, 5 and 6 contain no LLM calls and are unit-testable without a provider. Preserving that
separation is what keeps the project testable.
"""
