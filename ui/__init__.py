"""Streamlit presentation layer.

**Imports ONLY ``cce.services``, ``cce.contracts`` and ``cce.exceptions``.**
No engines, no data providers, no repository — enforced by
``tests/test_architecture.py`` (INV-12).

There is no financial computation here. Every number rendered was computed
behind the service boundary; this package turns fractions into strings and
draws them. The Approve button reads ``candidate.eligible_for_approval``
rather than reimplementing the condition, and the service re-checks it
server-side regardless (INV-2).
"""
