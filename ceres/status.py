from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import DataObject

__all__ = [
    "Status",
]


class Status(DataObject, slots=True):
    """Snapshot of a node's runtime status at a point in time."""

    address: Address
    """Address of the node this status describes."""
    running: bool
    """Whether the node is currently running."""
    enabled: bool | None = None
    """Whether the node is enabled, or `None` if the node has no enable/disable concept."""
    connectivity: Connectivity | None = None
    """Current transport connectivity state, or `None` if the node is not a connection."""
