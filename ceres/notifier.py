from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from typing import override

from pydantic import Field, NonNegativeInt, SecretStr

from ceres.component import Component, action
from ceres.data import DataObject, NonBlankStr


class Notification(DataObject):
    subject: NonBlankStr
    content: str | None = None
    content_type: NonBlankStr = "text/plain"


class Notifier(Component):
    @abstractmethod
    @action
    async def notify(
        self,
        notification: Notification,
        recipients: Iterable[NonBlankStr],
    ) -> None: ...


class SMTPNotifier(Notifier):
    host: NonBlankStr
    port: NonNegativeInt
    sender: NonBlankStr
    username: NonBlankStr | None = None
    password: SecretStr | None = Field(None, min_length=1)
    use_tls: bool = False
    use_starttls: bool = False

    @override
    async def notify(
        self,
        notification: Notification,
        recipients: Iterable[NonBlankStr],
    ) -> None:
        recipients = list(recipients)
        if not recipients:
            self.system.log.warning("No recipients specified, skipping notification.")
            return

        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = ",".join(recipient.strip() for recipient in recipients)
        message["Subject"] = notification.subject
        message.set_type(notification.content_type)
        message.set_payload(notification.content or "", charset="utf-8")

        if self.password is not None:
            password = self.password.get_secret_value()
        else:
            password = None

        from aiosmtplib import send

        await send(
            message,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=password,
            use_tls=self.use_tls,
            start_tls=self.use_starttls,
        )

        self.system.log.info("Email notification sent successfully.")
