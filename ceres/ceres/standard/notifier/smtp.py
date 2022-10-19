from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from sys import prefix

import aiosmtplib
from pydantic import SecretStr

from ...alert import Alert
from ...config import UserConfig
from ...internal.utilities import EmailStr, jsonify
from ...notifier import Notifier


@dataclass(kw_only=True, frozen=True)
class SMTPNotifierParameters:
    host: str
    port: int
    sender: EmailStr
    use_tls: bool = False
    start_tls: bool = False
    username: str | None = None
    password: SecretStr | None = None
    timeout: timedelta = timedelta(seconds=30)
    prefix: str | None = None


class SMTPNotifier(Notifier):
    def __init__(self, parameters: SMTPNotifierParameters) -> None:
        super().__init__()
        self._parameters = parameters

    @property
    def parameters(self) -> SMTPNotifierParameters:
        return self._parameters

    async def send(self, users: list[UserConfig], alerts: list[Alert]) -> None:
        recipients = sorted(set(user.email.strip() for user in users if user.email.strip()))
        if not recipients:
            return

        subject = f"{len(alerts)} Alert(s)"
        if prefix:
            subject = prefix + subject

        message = EmailMessage()
        message["From"] = self.parameters.sender
        message["To"] = ",".join(recipients)
        message["Subject"] = subject
        message.set_content(jsonify(alerts))

        if self.parameters.password is not None:
            password = self.parameters.password.get_secret_value()
        else:
            password = None

        await aiosmtplib.send(
            message=message,
            username=self.parameters.username,
            password=password,
            timeout=self.parameters.timeout.total_seconds(),
            use_tls=self.parameters.use_tls,
            start_tls=self.parameters.start_tls,
        )
