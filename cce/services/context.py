"""Shared dependencies for the service layer.

Spec: docs/02-ARCHITECTURE.md section 2, docs/06-DATA-CONTRACTS.md section 9.

Every service needs the same four things: the universe, the policy in force,
the current market data, and the repository. Loading them per service would
mean a decision cycle could optimize against one price panel and validate
against another — the two verdicts would not be about the same portfolio, and
the independence property would be lost to a data race rather than to a
design flaw.

So they are resolved ONCE, here, and passed in. The context is immutable; a
refresh builds a new one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from cce.audit import AuditRepository, get_connection, run_migrations
from cce.clock import market_today
from cce.config import load_universe
from cce.contracts import MarketData, Policy, Universe, ValidationReport
from cce.data import load_market_data

__all__ = ["ServiceContext"]

DEMO_PORTFOLIO_ID = "DEMO_100CR"


@dataclass(frozen=True)
class ServiceContext:
    """Everything the services share, resolved once."""

    universe: Universe
    policy: Policy
    market_data: MarketData
    validation: ValidationReport
    repo: AuditRepository
    snapshot_id: int
    portfolio_id: str = DEMO_PORTFOLIO_ID

    @classmethod
    def build(
        cls,
        db_path: str | None = None,
        as_of: date | None = None,
        portfolio_id: str = DEMO_PORTFOLIO_ID,
        snapshot_id: int = 1,
    ) -> ServiceContext:
        """Resolve configuration, data and persistence.

        Migrations run first: every other call assumes the schema and the
        seeded policy exist, and a missing seed is a setup failure rather
        than something to paper over with defaults.

        ``snapshot_id`` defaults to the seeded market snapshot so the demo
        starts from a coherent state without a network round trip. A live
        cycle records its own snapshot and passes the new id.
        """
        run_migrations(db_path)
        repo = AuditRepository(get_connection(db_path))

        universe = load_universe()
        market_data, report = load_market_data(
            universe, end=as_of or market_today()
        )
        return cls(
            universe=universe,
            policy=repo.get_current_policy(),
            market_data=market_data,
            validation=report,
            repo=repo,
            snapshot_id=snapshot_id,
            portfolio_id=portfolio_id,
        )

    def with_market_data(
        self, market_data: MarketData, validation: ValidationReport
    ) -> ServiceContext:
        """A context over fresher data. Used to re-check a stale candidate."""
        return replace(self, market_data=market_data, validation=validation)

    def close(self) -> None:
        self.repo.conn.close()

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------

    @property
    def policy_version_id(self) -> int:
        """The version id of the policy in force.

        Read from the store rather than from ``policy.version``: the audit
        column is a foreign key into ``policy_versions``, and the two are the
        same number only by convention.
        """
        return self.repo.get_current_policy_version_id()
