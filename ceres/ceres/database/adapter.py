from abc import ABC, abstractproperty
from typing import List


class DatabaseAdapter(ABC):
    @abstractproperty
    def ddl(self) -> List[str]:
        ...

    @abstractproperty
    def tables(self) -> str:
        ...
