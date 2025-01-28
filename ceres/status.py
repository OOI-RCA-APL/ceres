from __future__ import annotations

from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import DataObject, DeferBuild


class Status(DataObject, DeferBuild):
    address: Address
    running: bool
    enabled: bool | None = None
    connectivity: Connectivity | None = None
