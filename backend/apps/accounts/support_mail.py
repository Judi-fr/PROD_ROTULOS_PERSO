"""Aviso por mail de cada mensaje nuevo del form de contacto ("Ayuda/Soporte").

El mensaje siempre se guarda y se ve en la bandeja de Soporte del admin
(``soporte_admin.html``); el mail es un aviso extra para no tener que entrar a
mirarla. Va a ``SUPPORT_NOTIFY_EMAILS`` (vacío = no se manda nada) con
``Reply-To`` del usuario, así contestar desde la casilla le llega a él. Un
fallo de SMTP no corta el envío del mensaje: se registra y sigue.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from apps.common.mail import branded_html

logger = logging.getLogger(__name__)

INBOX_URL_PATH = "/soporte_admin.html"


def notify_new_support_message(message) -> bool:
    recipients = [email for email in settings.SUPPORT_NOTIFY_EMAILS if email]
    if not recipients:
        return False

    sender = message.user.email or ""
    inbox_url = f"{settings.FRONTEND_URL.rstrip('/')}{INBOX_URL_PATH}"
    heading = "Nuevo mensaje de soporte"
    paragraphs = [
        f"De: {sender or 'usuario sin email'}",
        f"Asunto: {message.subject}",
        message.message,
    ]
    footnote = "Respondiendo este mail le contestás directo a quien escribió."
    text = "\n\n".join([heading, *paragraphs, f"Bandeja de soporte: {inbox_url}", footnote]) + "\n"

    mail = EmailMultiAlternatives(
        # Sin saltos de línea: el asunto lo escribió el usuario y va a una cabecera.
        subject=f"[Soporte] {' '.join(message.subject.split())}"[:200],
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        reply_to=[sender] if sender else None,
    )
    mail.attach_alternative(
        branded_html(
            heading=heading,
            paragraphs=paragraphs,
            action=("Abrir la bandeja de soporte", inbox_url),
            footnote=footnote,
        ),
        "text/html",
    )
    try:
        mail.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001 — el aviso no puede cortar el envío del mensaje
        logger.exception("No se pudo mandar el aviso de soporte", extra={"support_message_id": message.pk})
        return False
