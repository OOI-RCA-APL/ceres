from datetime import timedelta
from email.message import EmailMessage
from typing import Sequence

import aiosmtplib
from pydantic import SecretStr

from ...alert import Alert
from ...data import jsonify
from ...internal.utilities import EmailStr, frozenlist, show_td
from ...notifier import Notifier


class SMTPNotifier(Notifier):
    class Parameters(Notifier.Parameters):
        host: str
        port: int
        sender: EmailStr
        recipients: frozenlist[EmailStr]
        use_tls: bool = False
        start_tls: bool = False
        username: str | None = None
        password: SecretStr | None = None
        timeout: timedelta = timedelta(seconds=30)
        prefix: str | None = None

    class Context(Notifier.Context):
        pass

    parameters: Parameters
    context: Context

    async def send(self, alerts: Sequence[Alert]) -> None:
        self.logger.info(
            f"Sending email notification to {len(self.parameters.recipients)} recipients(s)."
        )

        subject = f"{len(alerts)} alert(s) reported in the last {show_td(self.parameters.lookback)}"
        if self.parameters.prefix:
            subject = self.parameters.prefix + subject

        message = EmailMessage()
        message["From"] = self.parameters.sender
        message["To"] = ",".join(self.parameters.recipients)
        message["Subject"] = subject
        message.set_content(jsonify(alerts))

        if self.parameters.password is not None:
            password = self.parameters.password.get_secret_value()
        else:
            password = None

        if not self.parameters.recipients:
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
