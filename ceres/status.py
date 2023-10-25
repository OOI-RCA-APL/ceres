from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import DataObject


class Status(DataObject):
    address: Address
    running: bool
    enabled: bool | None = None
    connectivity: Connectivity | None = None
