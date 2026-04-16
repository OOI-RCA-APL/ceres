from abc import abstractmethod
from collections.abc import Iterable
from typing import override

from pydantic import Field, NonNegativeInt, SecretStr

from ceres.component import Component, action
from ceres.data import DataObject, NonBlankStr

__all__ = [
    "Notification",
    "Notifier",
    "SMTPNotifier",
]


class Notification(DataObject):
    """Message payload delivered by a `Notifier` to one or more recipients."""

    subject: NonBlankStr
    """Short summary line shown as the notification's subject."""
    content: str | None = None
    """Body of the notification, or `None` for a subject-only message."""
    content_type: NonBlankStr = "text/plain"
    """MIME type describing how to interpret `content`."""


class Notifier(Component):
    """Component that delivers `Notification` payloads to external recipients.

    Subclasses implement `notify()` to dispatch through a specific transport such as
    SMTP, SMS, or a chat service.
    """

    @abstractmethod
    @action
    async def notify(
        self,
        notification: Notification,
        recipients: Iterable[NonBlankStr],
    ) -> None:
        """Deliver a notification to the given recipients.

        Args:
            notification: Notification payload to deliver.
            recipients: Addresses to deliver the notification to.
        """
        ...


class SMTPNotifier(Notifier):
    """`Notifier` that delivers notifications as email messages over SMTP."""

    host: NonBlankStr
    """Hostname of the SMTP server to connect to."""
    port: NonNegativeInt
    """TCP port of the SMTP server."""
    sender: NonBlankStr
    """Address used as the `From` header on outgoing messages."""
    username: NonBlankStr | None = None
    """Optional username for SMTP authentication."""
    password: SecretStr | None = Field(None, min_length=1)
    """Optional password for SMTP authentication."""
    use_tls: bool = False
    """Connect with TLS immediately when opening the SMTP connection."""
    use_starttls: bool = False
    """Upgrade the SMTP connection to TLS via STARTTLS after the initial handshake."""

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
