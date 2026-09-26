"""BEG_WORK read-only web dashboard.

A projection of the control protocol published on ``codex/claude-queue``.
Per CLAUDE.md section 2 rule 12 this package is a projection and an interface,
never a second source of truth: it performs no GitHub write of any kind and
never emits an operational record.
"""

__all__ = ["__version__"]

__version__ = "0.2.0-c02"
