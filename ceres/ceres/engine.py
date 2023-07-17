from typing import final

from typing_extensions import override

from ceres.component import Component
from ceres.database import Database


@final
class Engine(Component):
    @property
    @override
    def database(self) -> Database:
        if self.local_database is not None:
            return self.local_database

        return super().database
