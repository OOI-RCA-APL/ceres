from datetime import timedelta
from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import SecretStr
from pydantic.dataclasses import dataclass as validated_dataclass

from ...alert import Alert
from ...config import UserConfig
from ...internal.utilities import EmailStr, jsonify, show_td
from ...notifier import Notifier, NotifierContext, NotifierParameters


@validated_dataclass(kw_only=True, frozen=True)
class SMTPNotifierParameters(NotifierParameters):
    host: str
    port: int
    sender: EmailStr
    use_tls: bool = False
    start_tls: bool = False
    username: str | None = None
    password: SecretStr | None = None
    timeout: timedelta = timedelta(seconds=30)
    prefix: str | None = None


@validated_dataclass(kw_only=True, frozen=True)
class SMTPNotifierContext(NotifierContext):
    pass


@validated_dataclass
class SMTPNotifier(Notifier):
    parameters: SMTPNotifierParameters
    context: SMTPNotifierContext

    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        self.logger.info(f"Sending email notification to {len(users)} user(s).")
        recipients = sorted(set(user.email.strip() for user in users if user.email.strip()))

        subject = f"{len(alerts)} alert(s) reported in the last {show_td(self.parameters.lookback)}"
        if self.parameters.prefix:
            subject = self.parameters.prefix + subject

        message = EmailMessage()
        message["From"] = self.parameters.sender
        message["To"] = ",".join(recipients)
        message["Subject"] = subject
        message.set_content(jsonify(alerts))

        if self.parameters.password is not None:
            password = self.parameters.password.get_secret_value()
        else:
            password = None

        if not recipients:
            return

        self.logger.info(f"Sending email '{subject}'...")

        try:
            await aiosmtplib.send(
                hostname=self.parameters.host,
                port=self.parameters.port,
                message=message,
                username=self.parameters.username,
                password=password,
                timeout=self.parameters.timeout.total_seconds(),
                use_tls=self.parameters.use_tls,
                start_tls=self.parameters.start_tls,
            )
        except Exception as exception:
            if error := str(exception).strip():
                self.logger.error(error)

            self.logger.error("Failed to send email notification.")
            return

        self.logger.error("Email notification sent successfully.")
