from ..notifier import Notifier
from .component import ComponentHandle


class NotifierHandle(ComponentHandle[Notifier]):
    @classmethod
    def _get_component_type(cls) -> type[Notifier]:
        return Notifier
