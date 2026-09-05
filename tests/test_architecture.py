"""Static architecture guards.

Spec: docs/11-TESTING-STRATEGY.md section 12, docs/02-ARCHITECTURE.md section 2.

These make the layer rules EXECUTABLE rather than aspirational. They pass
trivially for packages that do not exist yet, and start biting the moment a
phase creates one — which is why this file is built in Phase 0 rather than
discovered at Phase 10 when violations are expensive to unwind.

The single most important assertion here is that ``cce/controls/`` never
imports ``cce.optimizer``. That is the structural form of the product's
central claim: the component that proposes an allocation cannot be the
component that approves it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# package path -> modules it MUST NOT import
FORBIDDEN: dict[str, list[str]] = {
    "ui": [
        "cce.risk", "cce.optimizer", "cce.controls", "cce.stress",
        "cce.audit", "cce.data", "cce.backtest", "jugaad_data",
    ],
    "cce/controls": ["cce.optimizer", "cce.services", "ui"],
    "cce/risk": ["cce.services", "cce.optimizer", "cce.controls", "ui"],
    "cce/optimizer": ["cce.services", "cce.controls", "ui"],
    "cce/stress": ["cce.services", "ui"],
    "cce/contracts": [
        "cce.risk", "cce.optimizer", "cce.controls", "cce.services",
        "cce.data", "cce.audit", "cce.stress", "cce.backtest", "ui",
    ],
    "cce/data": ["cce.services", "cce.optimizer", "cce.controls", "ui"],
    "cce/audit": ["cce.services", "cce.optimizer", "cce.controls", "ui"],
    "cce/decisions": ["cce.services", "cce.optimizer", "cce.controls", "ui"],
}


def _imports(path: Path) -> set[str]:
    """Every module name imported by a file, absolute and relative resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    pkg = path.relative_to(ROOT).parent.as_posix().replace("/", ".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import -> resolve against this package
                parts = pkg.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                found.add(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                found.add(node.module)
    return found


def _py_files(package: str) -> list[Path]:
    d = ROOT / package
    if not d.exists():
        return []
    return [p for p in d.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize(("package", "forbidden"), sorted(FORBIDDEN.items()))
def test_layer_dependencies(package: str, forbidden: list[str]) -> None:
    """No module may import across a forbidden layer boundary."""
    violations: list[str] = []
    for f in _py_files(package):
        for imported in _imports(f):
            for bad in forbidden:
                if imported == bad or imported.startswith(bad + "."):
                    violations.append(
                        f"{f.relative_to(ROOT).as_posix()} imports {imported}"
                    )
    assert not violations, (
        f"{package} violates its layer contract (docs/02-ARCHITECTURE.md "
        f"section 2):\n  " + "\n  ".join(violations)
    )


def test_controls_never_import_the_optimizer() -> None:
    """INV-2, structural. The safety property in one assertion.

    If the validator could read the optimizer's own numbers, an optimistic
    solver would pass straight through the safety gate. Independent
    re-derivation turns an optimizer bug into a REJECTION.
    """
    offenders = [
        f.relative_to(ROOT).as_posix()
        for f in _py_files("cce/controls")
        if re.search(r"\b(from|import)\s+cce\.optimizer|from cce import optimizer",
                     f.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "cce/controls must never import cce.optimizer: " + ", ".join(offenders)
    )


def test_ui_contains_no_financial_computation() -> None:
    """INV-12. The UI renders; it does not calculate."""
    banned = re.compile(
        r"\bnp\.(std|var|cov|percentile|mean)\b|\.pct_change\(|\bsqrt\(252\)|"
        r"\bcvxpy\b|\bimport cvxpy\b"
    )
    offenders = [
        f"{f.relative_to(ROOT).as_posix()}:{i}"
        for f in _py_files("ui")
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if banned.search(line)
    ]
    assert not offenders, (
        "financial computation found in ui/ (INV-12): " + ", ".join(offenders)
    )


def test_no_policy_thresholds_inlined_outside_controls() -> None:
    """INV-11. Threshold values live in config, compared only in cce/controls."""
    literals = re.compile(
        r"(?<![\w.])(0\.12|0\.15|0\.06|0\.08|0\.30|0\.40|0\.25|0\.35|0\.10)"
        r"\s*(<=|>=|<|>)"
    )
    offenders = [
        f"{f.relative_to(ROOT).as_posix()}:{i}"
        for pkg in ("ui", "cce/risk", "cce/optimizer", "cce/services")
        for f in _py_files(pkg)
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if literals.search(line) and "noqa: threshold" not in line
    ]
    assert not offenders, (
        "policy threshold compared outside cce/controls (INV-11): "
        + ", ".join(offenders)
    )


def test_no_swallowed_exceptions() -> None:
    """NFR-013. Every except handles meaningfully or re-raises.

    A metric defaulting to 0.0 in an except block converts an error into a
    false safety signal - the exact failure INV-5 exists to prevent.
    """
    offenders: list[str] = []
    for pkg in ("cce", "ui"):
        for f in _py_files(pkg):
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        offenders.append(
                            f"{f.relative_to(ROOT).as_posix()}:{node.lineno} bare except"
                        )
                    elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        offenders.append(
                            f"{f.relative_to(ROOT).as_posix()}:{node.lineno} except: pass"
                        )
    assert not offenders, "swallowed exceptions (NFR-013): " + ", ".join(offenders)


def test_no_unsafe_constructs() -> None:
    """NFR-031. No eval/exec, no yaml.load without a safe loader, no pickle."""
    banned = re.compile(r"\beval\(|\bexec\(|pickle\.load|yaml\.load\((?!.*Safe)")
    offenders = [
        f"{f.relative_to(ROOT).as_posix()}:{i}"
        for pkg in ("cce", "ui")
        for f in _py_files(pkg)
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if banned.search(line) and not line.lstrip().startswith("#")
    ]
    assert not offenders, "unsafe construct (NFR-031): " + ", ".join(offenders)


def test_only_the_audit_package_touches_the_database() -> None:
    """docs/02-ARCHITECTURE.md section 2: cce/audit/ is the ONLY DB access.

    This guard exists because it was breached: cce/decisions/replay.py was
    written with its own cursor and its own SELECT. Nothing caught it, because
    the layer rules were expressed as import checks and raw SQL is not an
    import.

    A second module holding a connection is how an append-only guarantee
    quietly stops being one — the repository can refuse an UPDATE, but it
    cannot refuse one issued behind its back.
    """
    # Per-line: a connection or a cursor being obtained at all.
    handle = re.compile(r"\bimport\s+sqlite3\b|\bsqlite3\.connect\b|\.cursor\(\)")
    # Whole-file: execute(...) opening onto a SQL keyword, triple-quoted or not.
    # Matched across newlines because the SQL in this codebase is written as a
    # block starting on the line after the call.
    statement = re.compile(
        r"\bexecute(?:many|script)?\s*\(\s*[\"']{1,3}\s*"
        r"(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|BEGIN|COMMIT)\b",
        re.IGNORECASE,
    )

    offenders: list[str] = []
    for pkg in ("cce", "ui"):
        for f in _py_files(pkg):
            rel = f.relative_to(ROOT).as_posix()
            if rel.startswith("cce/audit/"):
                continue
            text = f.read_text(encoding="utf-8")
            offenders.extend(
                f"{rel}:{i}"
                for i, line in enumerate(text.splitlines(), 1)
                if handle.search(line)
            )
            if statement.search(text):
                offenders.append(f"{rel} (raw SQL statement)")
    assert not offenders, (
        "database access outside cce/audit/ (docs/02-ARCHITECTURE.md section 2): "
        + ", ".join(offenders)
    )


def test_every_package_is_a_real_package() -> None:
    """Every cce subpackage has an __init__.py.

    Namespace packages work until something needs the package docstring, an
    explicit export list, or a tool that walks __init__ files - and then they
    fail in a way that looks like a missing module rather than a missing file.
    """
    missing = [
        d.relative_to(ROOT).as_posix()
        for d in sorted((ROOT / "cce").iterdir())
        if d.is_dir()
        and d.name != "__pycache__"
        and any(p.suffix == ".py" for p in d.iterdir())
        and not (d / "__init__.py").exists()
    ]
    assert not missing, "package without __init__.py: " + ", ".join(missing)
