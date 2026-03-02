from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import DataObject

__all__ = [
    "Status",
]


class Status(DataObject, slots=True):
    address: Address
    running: bool
    enabled: bool | None = None
    connectivity: Connectivity | None = None
