from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from typing_extensions import Self

from ceres.data import EmailStr, ImmutableDataObject, PasswordHash, PasswordStr, UsernameStr
from ceres.internal.cli.plumbing import CLIOption
from ceres.internal.utilities import PriorityStrEnum, get_type_adapter


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class __UserFields(ImmutableDataObject):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    username: Annotated[UsernameStr, CLIOption(str)]
    email: Annotated[EmailStr, CLIOption(str)]
    password: Annotated[str, CLIOption(str, prompt=True, hide_input=True)]
    role: Annotated[UserRole, CLIOption(UserRole)] = UserRole.OPERATOR
    disabled: Annotated[bool, CLIOption(bool)] = False


class User(__UserFields):
    password: Annotated[PasswordHash, CLIOption(str, prompt=True, hide_input=True)]


class UserCreate(__UserFields):
    password: Annotated[PasswordStr, CLIOption(str, prompt=True, hide_input=True)]
    # password_is_hashed: Annotated[bool, CLIOption(bool)] = False
    password_is_hashed: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.password_is_hashed:
            try:
                get_type_adapter(PasswordHash).validate_python(self.password)
            except ValueError:
                raise ValueError(
                    "`password_is_hashed` is True, but `password` is not a valid bcrypt hash."
                )

        return self
