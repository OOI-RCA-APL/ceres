from ceres.component import Component, query
from ceres.ui import Element


class Interface(Component):
    @query
    async def render(self) -> Element: ...
