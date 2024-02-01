from uuid import UUID, uuid4

from pydantic import Field

from ceres.data import EmailStr, ImmutableDataObject, UsernameStr
from ceres.internal.utilities import PriorityStrEnum


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class PrivateUser(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    username: UsernameStr
    email: EmailStr
    role: UserRole = UserRole.OPERATOR
    disabled: bool = False


class User(PrivateUser):
    hash: str


class UserCreate(PrivateUser):
    password: str
