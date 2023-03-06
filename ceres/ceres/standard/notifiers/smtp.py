from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import Field, SecretStr
from typing_extensions import override

from ceres.roles.notifier import Notification, Notifier


class SMTPNotifier(Notifier):
    email: str
    username: str | None = None
    password: SecretStr | None = None
    host: str
    port: int = Field(ge=0)
    use_tls: bool = False
    use_starttls: bool = False

    @override
    async def notify(
        self,
        notification: Notification,
        recipients: Sequence[str],
    ) -> None:
        message = EmailMessage()
        message["From"] = self.email
        message["To"] = ",".join(recipient.strip() for recipient in recipients)
        message["Subject"] = notification.subject
        message.set_type(notification.content_type)
        message.set_payload(notification.content, charset="utf-8")

        if self.username is not None:
            username = self.username
        else:
            username = self.email

        if self.password is not None:
            password = self.password.get_secret_value()
        else:
            password = None

        await aiosmtplib.send(
            message=message,
            hostname=self.host,
            port=self.port,
            username=username,
            password=password,
            use_tls=self.use_tls,
            start_tls=self.use_starttls,
        )

        self.logger.info("Email notification sent successfully.")
