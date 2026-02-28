from ceres.component import Component, query
from ceres.ui import Element

__all__ = [
    "Interface",
]


class Interface(Component):
    @query
    async def render(self) -> Element: ...
