from __future__ import annotations

from typing import Any, Sequence

from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject, simplify

with lazy_imports(__name__):
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError

_undefined = object()


class ValidationProblem(ImmutableDataObject):
    type: str
    location: Sequence[str | int]
    message: str

    @classmethod
    def extract(
        cls,
        error: ValidationError | RequestValidationError,
        source: object = _undefined,
    ) -> list[ValidationProblem]:
        data = simplify(source) if source is not _undefined else _undefined
        problems: list[ValidationProblem] = []

        for suberror in error.errors():
            default_location = list(segment for segment in suberror["loc"] if segment != "__root__")
            location: list[str | int] | None = []
            try:
                if source is not _undefined:
                    location = []
                    parent: object | None = None
                    current: Any = data
                    for segment in default_location:
                        if isinstance(current, dict):
                            current = current.get(segment)
                        elif isinstance(current, list):
                            current = current[int(segment)]

                        if (
                            isinstance(segment, int)
                            and isinstance(parent, list)
                            and isinstance(current, dict)
                            and "name" in current
                        ):
                            location.append(f"name: {current['name']}")
                        else:
                            location.append(segment)

                        parent = current
                else:
                    location = default_location
            except Exception:
                location = default_location

            problems.append(
                ValidationProblem(
                    type=suberror["type"],
                    location=location,
                    message=suberror["msg"],
                )
            )

        return problems
