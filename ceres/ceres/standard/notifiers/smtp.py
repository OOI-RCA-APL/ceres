from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import Field, SecretStr

from ...data import ImmutableDataObject
from ...notifier import Notification, Notifier


class SMTPLogin(ImmutableDataObject):
    email: str
    username: str | None = None
    password: SecretStr | None = None
    host: str
    port: int = Field(ge=0)
    use_tls: bool = False
    start_tls: bool = False


class SMTPNotifier(Notifier):
    class Parameters(Notifier.Parameters):
        login: SMTPLogin

    parameters: Parameters

    async def notify(
        self,
        notification: Notification,
        recipients: Sequence[str],
    ) -> None:
        message = EmailMessage()
        message["From"] = self.parameters.login.email
        message["To"] = ",".join(recipient.strip() for recipient in recipients)
        message["Subject"] = notification.subject
        message.set_type(notification.content_type)
        message.set_payload(notification.content, charset="utf-8")

        if self.parameters.login.username is not None:
            username = self.parameters.login.username
        else:
            username = self.parameters.login.email

        if self.parameters.login.password is not None:
            password = self.parameters.login.password.get_secret_value()
        else:
            password = None

        await aiosmtplib.send(
            message=message,
            hostname=self.parameters.login.host,
            port=self.parameters.login.port,
            username=username,
            password=password,
            use_tls=self.parameters.login.use_tls,
            start_tls=self.parameters.login.start_tls,
        )

        self.logger.info("Email notification sent successfully.")
