from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import Field, SecretStr
from typing_extensions import override

from ceres.roles.notifier import Notification, Notifier


class SMTPNotifier(Notifier):
    host: str
    port: int = Field(ge=0)
    sender: str | None = None
    username: str | None = None
    password: SecretStr | None = None
    use_tls: bool = False
    use_starttls: bool = False

    @override
    async def notify(
        self,
        notification: Notification,
        recipients: Sequence[str],
    ) -> None:
        message = EmailMessage()
        if self.sender is not None:
            message["From"] = self.sender
        message["To"] = ",".join(recipient.strip() for recipient in recipients)
        message["Subject"] = notification.subject
        message.set_type(notification.content_type)
        message.set_payload(notification.content, charset="utf-8")

        if self.password is not None:
            password = self.password.get_secret_value()
        else:
            password = None

        await aiosmtplib.send(
            message=message,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=password,
            use_tls=self.use_tls,
            start_tls=self.use_starttls,
        )

        self.logger.info("Email notification sent successfully.")
