"""Exception hierarchy for CADEN.

The spec says: no silent fallbacks; failures should be loud and diagnosable.
Every subsystem raises a subclass of CadenError with a clear, actionable message.
Nothing in CADEN is allowed to catch these and pretend the failure didn't happen.
"""

from __future__ import annotations


class CadenError(Exception):
    """Base class for every expected failure in CADEN.

    A CadenError in a log or crash means: we predicted this could go wrong,
    here is what happened, here is what to check.
    """


class ConfigError(CadenError):
    """Config is missing, malformed, or points somewhere invalid."""


class BootError(CadenError):
    """A boot-sequence precondition is not satisfied."""


class DBError(CadenError):
    """Sqlite / sqlite-vec / schema / migration problem."""


class EmbedError(CadenError):
    """Embedding model (nomic-embed-text via ollama) failed."""


class LLMError(CadenError):
    """Ollama chat / generate call failed, or repair ultimately failed."""


class LLMRepairError(LLMError):
    """Repair layer could not recover the required shape from the model."""


class RaterError(CadenError):
    """Rater could not produce a valid rating."""


class GoogleSyncError(CadenError):
    """Google Calendar / Tasks sync problem."""


class SchedulerError(CadenError):
    """Scheduling, prediction, or residual computation failed."""
