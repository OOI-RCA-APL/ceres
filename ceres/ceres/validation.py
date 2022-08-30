from __future__ import annotations

from pydantic import BaseModel, ValidationError


class ValidationProblem(BaseModel):
    location: list[str | int]
    message: str
    kind: str

    @classmethod
    def extract(cls, error: ValidationError) -> list[ValidationProblem]:
        return [
            ValidationProblem(
                location=list(error["loc"]),
                message=error["msg"],
                kind=error["type"],
            )
            for error in error.errors()
        ]
