"""Configuration loading.

Reads ``.env`` plus the three YAML files into typed contracts.
Spec: docs/03-TRD.md section 4, docs/07-RISK-POLICY.md section 4.

``yaml.safe_load`` only (NFR-031). No secret is ever logged or returned in a
representation (NFR-033).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .contracts import (
    Asset,
    Comparator,
    Constraints,
    DataProvider,
    ModelParams,
    Policy,
    Scenario,
    Scope,
    Threshold,
    Universe,
)
from .exceptions import PolicyError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

__all__ = [
    "Settings",
    "get_settings",
    "load_policy",
    "load_scenarios",
    "load_universe",
]


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path(key: str, default: str) -> Path:
    raw = _env(key, default) or default
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Never rendered in the UI, never logged."""

    data_provider: DataProvider
    db_path: Path
    policy_file: Path
    universe_file: Path
    scenarios_file: Path
    random_seed: int
    llm_enabled: bool
    llm_api_key: str | None
    log_level: str

    def __repr__(self) -> str:  # never leak the key
        return (
            f"Settings(data_provider={self.data_provider.value!r}, "
            f"db_path={str(self.db_path)!r}, llm_enabled={self.llm_enabled!r}, "
            f"llm_api_key={'<set>' if self.llm_api_key else None!r})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    provider_raw = (_env("CCE_DATA_PROVIDER", "cached") or "cached").upper()
    try:
        provider = DataProvider[provider_raw]
    except KeyError:
        raise PolicyError(
            f"CCE_DATA_PROVIDER must be one of "
            f"{[d.name.lower() for d in DataProvider]}, got {provider_raw!r}"
        ) from None

    llm_enabled = _env_bool("CCE_LLM_ENABLED", False)
    llm_key = _env("CCE_LLM_API_KEY") or None

    # FR-146: the system works fully with no API key. Warn, never raise.
    if llm_enabled and not llm_key:
        logger.warning(
            "CCE_LLM_ENABLED is true but no CCE_LLM_API_KEY is set. "
            "Falling back to the deterministic narrator."
        )

    return Settings(
        data_provider=provider,
        db_path=_path("CCE_DB_PATH", "./data/cce.db"),
        policy_file=_path("CCE_POLICY_FILE", "./config/policy.yaml"),
        universe_file=_path("CCE_UNIVERSE_FILE", "./config/universe.yaml"),
        scenarios_file=_path("CCE_SCENARIOS_FILE", "./config/scenarios.yaml"),
        random_seed=int(_env("CCE_RANDOM_SEED", "42") or 42),
        llm_enabled=llm_enabled,
        llm_api_key=llm_key,
        log_level=(_env("CCE_LOG_LEVEL", "INFO") or "INFO").upper(),
    )


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise PolicyError(f"configuration file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise PolicyError(f"{path} must contain a YAML mapping")
    return data


def load_universe(path: Path | None = None) -> Universe:
    """Build the :class:`Universe` from ``config/universe.yaml``."""
    path = path or get_settings().universe_file
    raw = _read_yaml(path)
    defaults = raw.get("defaults", {}) or {}
    entries = raw.get("assets") or []
    if not entries:
        raise PolicyError(f"{path} defines no assets")

    assets: list[Asset] = []
    for e in entries:
        assets.append(
            Asset(
                asset_id=e["asset_id"],
                ticker=e["ticker"],
                name=e["name"],
                asset_class=e["asset_class"],
                sector=e["sector"],
                is_liquid=bool(e["is_liquid"]),
                min_weight=float(e.get("min_weight", defaults.get("min_weight", 0.0))),
                max_weight=float(e.get("max_weight", defaults.get("max_weight", 0.30))),
                txn_cost_rate=float(
                    e.get("txn_cost_rate", defaults.get("txn_cost_rate", 0.0010))
                ),
                adv_paise=e.get("adv_paise", defaults.get("adv_paise")),
                source=str(e.get("source", defaults.get("source", "stock"))),
                synthetic=bool(e.get("synthetic", False)),
            )
        )
    return Universe(assets=tuple(assets))


def load_policy(path: Path | None = None) -> Policy:
    """Build the :class:`Policy` from ``config/policy.yaml``."""
    path = path or get_settings().policy_file
    raw = _read_yaml(path)

    model = ModelParams(**(raw.get("model") or {}))

    thresholds: list[Threshold] = []
    for t in raw.get("thresholds") or []:
        thresholds.append(
            Threshold(
                control_code=t["code"],
                label=t["label"],
                scope=Scope[t["scope"]],
                comparator=Comparator[t["comparator"]],
                is_hard=bool(t["is_hard"]),
                green_max=t.get("green_max"),
                amber_max=t.get("amber_max"),
                green_min=t.get("green_min"),
                amber_min=t.get("amber_min"),
            )
        )
    if not thresholds:
        raise PolicyError(f"{path} defines no thresholds")

    c = raw.get("constraints") or {}
    universe = load_universe()
    default_min = float(c.get("min_weight_default", 0.0))
    default_max = float(c.get("max_weight_default", 0.30))

    constraints = Constraints(
        min_weights={a.asset_id: a.min_weight or default_min for a in universe.assets},
        max_weights={a.asset_id: a.max_weight or default_max for a in universe.assets},
        sector_max={k: float(v) for k, v in (c.get("sector_max") or {}).items()},
        asset_class_max={
            k: float(v) for k, v in (c.get("asset_class_max") or {}).items()
        },
        min_liquid_share=float(c.get("min_liquid_share", 0.0)),
        min_cash_share=float(c.get("min_cash_share", 0.0)),
        max_turnover=float(c.get("max_turnover", 1.0)),
        long_only=bool(c.get("long_only", True)),
        include_txn_cost=bool(c.get("include_txn_cost", True)),
    )

    return Policy(
        version=int(raw.get("version", 1)),
        label=str(raw.get("label", "unnamed policy")),
        thresholds=tuple(thresholds),
        model=model,
        constraints=constraints,
        stress_loss_limit=float(raw.get("stress_loss_limit", 0.18)),
        recovery_max_turnover=float(raw.get("recovery_max_turnover", 0.10)),
    )


def load_scenarios(path: Path | None = None) -> tuple[Scenario, ...]:
    """Load the default stress scenarios.

    The single loader for ``config/scenarios.yaml``. ``cce.stress.scenarios``
    re-exports this rather than parsing the file a second time.
    """
    path = path or get_settings().scenarios_file
    raw = _read_yaml(path)
    out: list[Scenario] = []
    for s in raw.get("scenarios") or []:
        out.append(
            Scenario(
                code=s["code"],
                label=s["label"],
                shocks={k: float(v) for k, v in (s.get("shocks") or {}).items()},
            )
        )
    if not out:
        raise PolicyError(f"{path} defines no scenarios")
    return tuple(out)
