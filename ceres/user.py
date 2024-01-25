from uuid import UUID, uuid4

from pydantic import Field

from ceres.data import EmailStr, ImmutableDataObject, UsernameStr
from ceres.internal.utilities import PriorityStrEnum


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class PublicUser(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    username: UsernameStr
    role: UserRole = UserRole.OPERATOR
    disabled: bool = False


class PrivateUser(PublicUser):
    email: EmailStr


class User(PrivateUser):
    hash: str
