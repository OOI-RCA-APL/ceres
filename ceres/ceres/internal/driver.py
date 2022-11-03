from ..driver import Driver
from .component import ComponentHandle


class DriverHandle(ComponentHandle[Driver]):
    @classmethod
    def _get_component_type(cls) -> type[Driver]:
        return Driver
