from ceres.component import Component, query
from ceres.layout import Layout


class UI(Component):
    @query
    async def get_layout(self) -> Layout:
        ...
