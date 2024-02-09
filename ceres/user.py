from typing import TYPE_CHECKING, Annotated
from uuid import UUID, uuid4

from pydantic import Field
from typing_extensions import TypedDict

from ceres.data import EmailStr, ImmutableDataObject, PasswordHash, PasswordStr, UsernameStr
from ceres.internal.cli.plumbing import CLIOption
from ceres.internal.utilities import PriorityStrEnum


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
    password: Annotated[
        PasswordHash if TYPE_CHECKING else str, CLIOption(str, prompt=True, hide_input=True)
    ]


class UserCreate(__UserFields):
    password: Annotated[PasswordStr | PasswordHash, CLIOption(str, prompt=True, hide_input=True)]


class UserUpdate(TypedDict, total=False):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr | PasswordHash
    role: UserRole
    disabled: bool
