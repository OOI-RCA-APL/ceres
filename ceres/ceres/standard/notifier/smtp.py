from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import SecretStr

from ...alert import Alert
from ...config import UserConfig
from ...internal.utilities import EmailStr, jsonify, show_td
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

    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        recipients = sorted(set(user.email.strip() for user in users if user.email.strip()))

        subject = f"{len(alerts)} alert(s) reported"

        if self.config:
            subject += f" in the last {show_td(self.config.lookback)}"
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
