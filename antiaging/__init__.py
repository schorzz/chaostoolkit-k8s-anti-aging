from typing import List

from chaoslib.discovery.discover import discover_actions
from chaoslib.discovery.discover import initialize_discovery_result
from chaoslib.types import DiscoveredActivities
from chaoslib.types import Discovery
from logzero import logger


__version__ = "0.1.0"


def discover(discover_system: bool = True) -> Discovery:
    """
    Discover k8s anti-aging capabilities from this extension.
    """
    logger.info("Discovering capabilities from chaostoolkit-k8s-anti-aging")

    discovery = initialize_discovery_result("chaostoolkit-k8s-anti-aging", __version__, "kubernetes")
    discovery["activities"].extend(load_exported_activities())

    return discovery


def load_exported_activities() -> List[DiscoveredActivities]:
    """
    Extract metadata from actions and probes exposed by this extension.
    """
    activities = []
    activities.extend(discover_actions("antiaging.actions"))

    return activities
