"""Policy inspection and versioned change.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/07-RISK-POLICY.md section 4.

A policy is never edited in place. Every change inserts a new version with
attribution, and loosening a hard limit requires an explicit acknowledgement
and a reason (INV-8). ``preview_change`` exists so a risk manager sees which
controls a change would weaken BEFORE it is applied (FR-084).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from cce.contracts import HumanActionRecord, Policy, Threshold
from cce.controls import PolicyChangePreview, diff_policies
from cce.exceptions import PolicyError

from .context import ServiceContext

__all__ = ["PolicyService"]


class PolicyService:
    """Reads the policy in force and records changes to it."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def get_current(self) -> Policy:
        """The policy version in force."""
        return self._ctx.repo.get_current_policy()

    def get_version(self, policy_version_id: int) -> Policy:
        """The policy a past decision was judged under (INV-8)."""
        return self._ctx.repo.get_policy_version(policy_version_id)

    def preview_change(self, changes: dict[str, dict[str, Any]]) -> PolicyChangePreview:
        """What a change would do, without applying it (FR-084).

        ``changes`` maps a control code to the fields being moved, e.g.
        ``{"RISK_VOL_ANNUAL": {"amber_max": 0.20}}``.
        """
        return diff_policies(self.get_current(), self._apply(changes))

    def apply_change(
        self,
        changes: dict[str, dict[str, Any]],
        actor: HumanActionRecord,
        change_summary: str | None = None,
    ) -> Policy:
        """Insert a new policy version (INV-8).

        Raises:
            PolicyError: If the change weakens a hard limit and the actor did
                not acknowledge it with a reason. The check lives here rather
                than only in the UI, for the same reason the approval gate
                does: a disabled button is convenience, not enforcement.
        """
        from cce.audit import PolicyChangeMeta

        proposed = self._apply(changes)
        preview = diff_policies(self.get_current(), proposed)
        weakening = preview.is_weakening

        if weakening and not (actor.override_reason and actor.is_override):
            raise PolicyError(
                "this change loosens a hard limit and requires an explicit "
                "acknowledgement with a reason (INV-8); affected controls: "
                + ", ".join(preview.weakened_controls)
            )

        self._ctx.repo.record_policy_version(
            proposed,
            PolicyChangeMeta(
                created_by=actor.user_identity,
                created_by_role=actor.user_role,
                source="UI_EDIT",
                parent_version_id=self._ctx.policy_version_id,
                change_summary=change_summary or preview.summary,
                is_weakening=weakening,
                weakening_ack_by=actor.user_identity if weakening else None,
                weakening_reason=actor.override_reason if weakening else None,
            ),
        )
        return proposed

    # ------------------------------------------------------------------

    def _apply(self, changes: dict[str, dict[str, Any]]) -> Policy:
        """Build the proposed policy. Pure — nothing is written."""
        current = self.get_current()
        by_code = {t.control_code: t for t in current.thresholds}

        unknown = [code for code in changes if code not in by_code]
        if unknown:
            raise PolicyError(
                f"no such control(s) in the policy: {', '.join(sorted(unknown))}"
            )

        updated: list[Threshold] = []
        for t in current.thresholds:
            fields = changes.get(t.control_code)
            if not fields:
                updated.append(t)
                continue
            try:
                updated.append(replace(t, **fields))
            except (ValueError, TypeError) as exc:
                # The Threshold contract refuses an incoherent band — a
                # green_max above amber_max would invert the control silently.
                # Re-raised as a PolicyError so the caller has one exception
                # type to handle, with the control named.
                raise PolicyError(
                    f"{t.control_code}: {exc}"
                ) from exc
        return replace(current, thresholds=tuple(updated))
