"""Collector package exports.

Keep package import lightweight.  Importing the orchestrator eagerly pulls in every
collector and media services, which has filesystem side effects at import time
(/app/data/media).  Submodules such as app.collectors.rss_collector should be
importable in tests and scripts without booting the full collector stack.
"""

from .rss_collector import RSSCollector
from .x_collector import XCollector

__all__ = ["RSSCollector", "XCollector", "CollectorOrchestrator", "orchestrator"]


def __getattr__(name: str):
    if name in {"orchestrator", "CollectorOrchestrator"}:
        from .orchestrator import CollectorOrchestrator, orchestrator

        return orchestrator if name == "orchestrator" else CollectorOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
