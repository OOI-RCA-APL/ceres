from ceres.address import Address
from ceres.data import ImmutableDataObject


class Store(ImmutableDataObject):
    address: Address
    enabled: bool = False
