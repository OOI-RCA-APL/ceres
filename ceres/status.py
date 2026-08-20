from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import DataObject, Field, Name

__all__ = [
    "ConnectionStatus",
    "Status",
]


class ConnectionStatus(DataObject, slots=True):
    """The connectivity state of a single named connection on a component."""

    name: Name
    """Name of the connection within its component."""
    label: str | None
    """Human-readable name for the connection, unset when it has none."""
    description: str | None
    """What the connection carries, unset when it has none."""
    uri: str
    """Where the connection's source reads from, such as `tcp://host:port`."""
    connectivity: Connectivity
    """Current transport connectivity state of the connection."""


class Status(DataObject, slots=True):
    """Snapshot of a node's runtime status at a point in time."""

    address: Address
    """Address of the node this status describes."""
    running: bool
    """Whether the node is currently running."""
    enabled: bool | None = None
    """Whether the node is enabled, or `None` if the node has no enable/disable concept."""
    connectivity: Connectivity | None = None
    """Overall connectivity when the component defines `__connectivity__`, otherwise `None`."""
    connections: list[ConnectionStatus] = Field(default_factory=list)
    """Per-connection connectivity states, empty when the component has no named connections."""
