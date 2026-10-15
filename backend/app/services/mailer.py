"""
AUTH-01 — minimal outbound e-mail provider abstraction.

One provider today (SMTP, configured by environment), one interface, so a vendor
API can replace it later without touching the callers:

    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    SMTP_SECURITY   optional: "ssl" | "starttls" | "none"
                    (default: "ssl" on port 465, otherwise "starttls")
    APP_PUBLIC_URL  the browser origin of the app, e.g. https://work.begfull.bg

:func:`get_mail_provider` returns ``None`` when SMTP_HOST / SMTP_FROM are not
set. Callers must then say so in the server log, never pretend a message went
out. Nothing in this module logs a message body, a recipient's secret link or a
credential.
"""
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional, Protocol

logger = logging.getLogger("beg.mailer")

SMTP_TIMEOUT_SECONDS = 15


class MailProvider(Protocol):
    name: str

    def send(self, to: str, subject: str, text: str) -> None:
        """Deliver one plain-text message; raise on failure."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    security: str

    @classmethod
    def from_env(cls) -> Optional["SmtpConfig"]:
        host = os.environ.get("SMTP_HOST", "").strip()
        sender = os.environ.get("SMTP_FROM", "").strip()
        if not host or not sender:
            return None
        try:
            port = int(os.environ.get("SMTP_PORT", "").strip() or 587)
        except ValueError:
            logger.warning("SMTP_PORT is not a number; e-mail delivery disabled")
            return None
        security = os.environ.get("SMTP_SECURITY", "").strip().lower() \
            or ("ssl" if port == 465 else "starttls")
        if security not in ("ssl", "starttls", "none"):
            logger.warning("SMTP_SECURITY must be ssl, starttls or none; e-mail delivery disabled")
            return None
        return cls(host=host, port=port, user=os.environ.get("SMTP_USER", "").strip(),
                   password=os.environ.get("SMTP_PASSWORD", ""), sender=sender,
                   security=security)


class SmtpMailProvider:
    name = "smtp"

    def __init__(self, config: SmtpConfig):
        self.config = config

    def send(self, to: str, subject: str, text: str) -> None:
        c = self.config
        msg = EmailMessage()
        msg["From"] = c.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        context = ssl.create_default_context()
        if c.security == "ssl":
            server = smtplib.SMTP_SSL(c.host, c.port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(c.host, c.port, timeout=SMTP_TIMEOUT_SECONDS)
        with server:
            if c.security == "starttls":
                server.starttls(context=context)
            if c.user:
                server.login(c.user, c.password)
            server.send_message(msg)


def get_mail_provider() -> Optional[MailProvider]:
    """The configured provider, or ``None`` when outbound e-mail is not set up."""
    config = SmtpConfig.from_env()
    return SmtpMailProvider(config) if config else None


def app_public_url() -> Optional[str]:
    """``APP_PUBLIC_URL`` without a trailing slash; ``None`` unless it is http(s)."""
    url = os.environ.get("APP_PUBLIC_URL", "").strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        return None
    return url
