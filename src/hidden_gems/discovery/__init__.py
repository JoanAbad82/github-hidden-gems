"""Discovery Engine: five bounded routes into GitHub (SPEC_V1 section 3)."""

from .engine import DiscoveryResult, build_query_plan, run_discovery
from .queries import DiscoveryQuery, QueryPlan

__all__ = [
    "DiscoveryQuery",
    "QueryPlan",
    "DiscoveryResult",
    "build_query_plan",
    "run_discovery",
]
