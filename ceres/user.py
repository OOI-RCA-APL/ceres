from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field
from typing_extensions import TypedDict

from ceres.data import (
    EmailStr,
    ImmutableDataObject,
    PasswordHash,
    PasswordStr,
    PriorityStrEnum,
    UsernameStr,
)
from ceres.internal.cli.plumbing import CLIOption


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserCreate(ImmutableDataObject):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    username: Annotated[UsernameStr, CLIOption(str)]
    email: Annotated[EmailStr, CLIOption(str)]
    password: Annotated[PasswordStr | PasswordHash, CLIOption(str, prompt=True, hide_input=True)]
    role: Annotated[UserRole, CLIOption(UserRole)] = UserRole.OPERATOR
    disabled: Annotated[bool, CLIOption(bool)] = False


class User(UserCreate):
    password: Annotated[PasswordHash, CLIOption(str, prompt=True, hide_input=True)]


class UserUpdate(TypedDict, total=False):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr | PasswordHash
    role: UserRole
    disabled: bool
