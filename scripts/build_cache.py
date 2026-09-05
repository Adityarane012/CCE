"""Build the committed market-data cache.

Run this while a network is available. The parquet it writes is COMMITTED,
and is what lets the demo run disconnected (NFR-010).

    python scripts/build_cache.py [--years 3]

Prints the data_hash. Two runs over the same snapshot must produce identical
analysis (NFR-012), so record that hash when you commit.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cce.clock import market_today
from cce.config import load_policy, load_universe
from cce.data import (
    DEFAULT_CACHE_DIR,
    JugaadDataProvider,
    panel_hash,
    universe_hash,
    validate_panel,
    write_cache,
)

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s"
)
log = logging.getLogger("build_cache")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--end", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--out", type=Path, default=DEFAULT_CACHE_DIR)
    args = ap.parse_args()

    end = date.fromisoformat(args.end) if args.end else market_today()
    start = end - timedelta(days=365 * args.years + 10)

    universe = load_universe()
    policy = load_policy()

    log.info("fetching %d assets from %s to %s", len(universe.assets), start, end)
    provider = JugaadDataProvider(
        risk_free_rate=policy.risk_free_rate,
        trading_days=policy.trading_days_per_year,
    )
    prices = provider.fetch_prices(universe, start, end)

    if provider.excluded:
        log.warning("EXCLUDED instruments (no reproducible series):")
        for aid, why in sorted(provider.excluded.items()):
            log.warning("    %-10s %s", aid, why)
        log.warning(
            "These are dropped, not fabricated. Say so in the UI "
            "(docs/01-PRODUCT-SPECIFICATION.md section 6)."
        )

    report = validate_panel(prices, universe, as_of=end)
    log.info("validation: %s (%d finding(s))", report.status.value,
             len(report.findings))
    for f in report.findings:
        log.info("    [%s] %s", f.severity.value, f.message)

    path = write_cache(prices, args.out)

    print()
    print(f"  rows        : {len(prices)}")
    print(f"  assets      : {list(prices.columns)}")
    print(f"  date range  : {prices.index.min()} .. {prices.index.max()}")
    print(f"  data_hash   : {panel_hash(prices)}")
    print(f"  universe    : {universe_hash(universe)}")
    print(f"  written     : {path}")
    print()
    print("  Commit this parquet — the demo's reproducibility depends on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
