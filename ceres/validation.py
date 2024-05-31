from __future__ import annotations

from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject

with lazy_imports(__name__):
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError


class ValidationProblem(ImmutableDataObject):
    type: str
    location: list[str | int]
    message: str

    @classmethod
    def extract(cls, error: ValidationError | RequestValidationError) -> list["ValidationProblem"]:
        return [
            ValidationProblem(
                type=error["type"],
                location=list(segment for segment in error["loc"] if segment != "__root__"),
                message=error["msg"],
            )
            for error in error.errors()
        ]
