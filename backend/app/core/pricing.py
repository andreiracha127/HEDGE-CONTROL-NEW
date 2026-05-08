"""Canonical pricing primitives shared by RFQ ingestion and ranking.

The accepted set is intentionally limited to what
``RFQService.canonicalize_fixed_price_unit`` can normalize for ranking
comparability. Adding a unit here without extending the canonicalizer
would silently produce non-rankable quotes that block awarding.
"""

CANONICAL_PRICE_UNITS = frozenset({"USD/MT"})
