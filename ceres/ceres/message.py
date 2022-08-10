from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    connection: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content: str
