from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.exceptions import RequestValidationError as __RequestValidationError__
    from pydantic import ValidationError as __ValidationError__

from ceres.data import ImmutableDataObject


class ValidationProblem(ImmutableDataObject):
    type: str
    location: list[str | int]
    message: str

    @classmethod
    def extract(
        cls, error: "__ValidationError__ | __RequestValidationError__"
    ) -> list["ValidationProblem"]:
        return [
            ValidationProblem(
                type=error["type"],
                location=list(segment for segment in error["loc"] if segment != "__root__"),
                message=error["msg"],
            )
            for error in error.errors()
        ]
