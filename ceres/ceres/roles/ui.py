# from abc import abstractmethod
from ceres.component import Component
from ceres.layout import Layout
from ceres.procedure import query


class UI(Component):
    @query
    async def get_layout(self) -> Layout:
        ...
