from __future__ import annotations


from ..notifier import Notifier
from ..protocols import ReferencedNotifierHandle
from .component import ComponentHandle


class NotifierHandle(ComponentHandle[Notifier], ReferencedNotifierHandle):
    @classmethod
    def _get_component_type(cls) -> type[Notifier]:
        return Notifier
