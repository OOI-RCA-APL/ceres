from pydantic import ValidationError
from typing_extensions import Self

from ceres.data import ImmutableDataObject


class ValidationProblem(ImmutableDataObject):
    location: list[str | int]
    message: str
    type: str

    @classmethod
    def extract(cls, error: ValidationError) -> list[Self]:
        return [
            ValidationProblem(
                location=list(segment for segment in error["loc"] if segment != "__root__"),
                message=error["msg"],
                type=error["type"],
            )
            for error in error.errors()
        ]
