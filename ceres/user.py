from uuid import UUID, uuid4

from pydantic import Field

from ceres.data import EmailStr, ImmutableDataObject, UsernameStr
from ceres.internal.utilities import PriorityStrEnum


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class User(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    username: UsernameStr
    hash: str
    role: UserRole = UserRole.OPERATOR
    disabled: bool = False
    email: EmailStr
