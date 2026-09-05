"""Exception hierarchy for CCE.

Every exception inherits :class:`CCEError` so a caller can catch the whole
family without resorting to a bare ``except``.

Engines never terminate the process (NFR-014); they raise these and let the
service layer decide. Nothing here is ever swallowed silently (NFR-013).
"""

from __future__ import annotations


class CCEError(Exception):
    """Base for every CCE error."""


class DataIntegrityError(CCEError):
    """Market data failed validation and MUST NOT be used for risk computation.

    Raised rather than substituting zeros. Missing data is not zero risk
    (INV-5).
    """


class InsufficientDataError(CCEError):
    """Too few observations to compute a metric honestly.

    Callers should surface ``None`` (renders as an em dash) rather than a
    misleading ``0.0``.
    """


class CovarianceError(CCEError):
    """Covariance matrix is not positive semi-definite and could not be repaired.

    A broken matrix MUST NOT be passed to the solver: it would return numbers,
    and they would be meaningless.
    """


class SolverError(CCEError):
    """The optimizer failed to converge or the problem was infeasible.

    Preserves the Last Approved Safe Allocation rather than inventing one
    (INV-4).
    """


class ApprovalNotPermitted(CCEError):
    """Attempted to approve a candidate that is not eligible.

    Enforced server-side. A disabled UI button is convenience, not enforcement
    (INV-2).
    """


class DecisionAlreadyClosed(CCEError):
    """A human action has already been recorded against this decision.

    The decision-closing transition is guarded and may fire exactly once
    (INV-6).
    """


class AuditWriteError(CCEError):
    """An audit record could not be persisted.

    Surfaces visibly. A failed write is NEVER reported as success (FR-125).
    """


class PolicyError(CCEError):
    """Policy configuration is invalid, or a policy change was rejected."""
