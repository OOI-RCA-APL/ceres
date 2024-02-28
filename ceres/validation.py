from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from ceres.data import ImmutableDataObject


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
