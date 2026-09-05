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

from cce.audit import (
    AuditRepository,
    MarketSnapshotMeta,
    get_connection,
    run_migrations,
)
from cce.audit.serialization import dumps
from cce.clock import market_today, utc_now
from cce.config import load_universe
from cce.contracts import MarketData, Policy, Universe, ValidationReport
from cce.data import load_market_data

__all__ = ["ServiceContext", "record_snapshot"]


def record_snapshot(
    repo: AuditRepository, market_data: MarketData, report: ValidationReport
) -> int:
    """Persist this panel's provenance and return its id.

    Get-or-create on ``(data_hash, universe_hash)``: analysing the same panel
    twice is the same snapshot, not a new one.
    """
    return repo.ensure_market_snapshot(MarketSnapshotMeta(
        captured_at=report.checked_at or utc_now(),
        as_of_date=market_data.as_of_date.isoformat(),
        provider=market_data.provider.value,
        universe_hash=market_data.universe_hash,
        data_hash=market_data.data_hash,
        row_count=len(market_data.returns),
        asset_count=len(market_data.returns.columns),
        validation_status=report.status.value,
        validation_json=dumps([
            {"code": f.code, "asset_id": f.asset_id,
             "severity": f.severity.value, "message": f.message}
            for f in report.findings
        ]),
    ))

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
        snapshot_id: int | None = None,
    ) -> ServiceContext:
        """Resolve configuration, data and persistence.

        Migrations run first: every other call assumes the schema and the
        seeded policy exist, and a missing seed is a setup failure rather
        than something to paper over with defaults.

        The panel's provenance is RECORDED, and the decisions built on this
        context reference that row. Pointing them at the seeded snapshot
        instead would leave the audit trail unable to say which price panel
        backed a verdict, which is the one question ``data_hash`` exists to
        answer (NFR-012). Pass ``snapshot_id`` only to pin an existing row.
        """
        run_migrations(db_path)
        repo = AuditRepository(get_connection(db_path))

        universe = load_universe()
        # Policy first: the data validator applies the DATA_FRESHNESS and
        # DATA_COMPLETENESS bands from it, and the CASH proxy accrues its
        # risk-free rate.
        policy = repo.get_current_policy()
        market_data, report = load_market_data(
            universe, end=as_of or market_today(), policy=policy
        )
        return cls(
            universe=universe,
            policy=policy,
            market_data=market_data,
            validation=report,
            repo=repo,
            snapshot_id=(
                snapshot_id
                if snapshot_id is not None
                else record_snapshot(repo, market_data, report)
            ),
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
