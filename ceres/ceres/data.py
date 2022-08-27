from __future__ import annotations

from pydantic import BaseModel
from pydantic.generics import GenericModel


class DataObject(BaseModel):
    pass


class GenericDataObject(GenericModel):
    pass
