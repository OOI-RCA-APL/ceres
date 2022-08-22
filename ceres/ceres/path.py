from ceres.data import DataObject


class UnitPath(DataObject):
    class Config:
        frozen = True

    unit: str

    @classmethod
    def create(cls, unit: str) -> "UnitPath":
        return UnitPath(unit=unit)

    def __str__(self) -> str:
        return f"@{self.unit}"


class ConnectionPath(DataObject):
    class Config:
        frozen = True

    unit: str
    connection: str

    @classmethod
    def create(cls, unit: str, connection: str) -> "ConnectionPath":
        return ConnectionPath(unit=unit, connection=connection)

    def __str__(self) -> str:
        return f"@{self.unit}.connections.{self.connection}"
