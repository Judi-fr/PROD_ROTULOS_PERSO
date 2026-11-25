"""Los mails de seguridad de la cuenta: uno por función, todos con el mismo
diseño (``branded_html``) y un cuerpo de texto plano. Nunca a los usuarios
internos de los comercios (``teams.internal_users_q``). Un fallo de SMTP no
corta lo que los dispara: se registra y sigue."""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from apps.common.mail import branded_html

logger = logging.getLogger(__name__)

SECURITY_URL_PATH = "/seguridad.html"


def _security_url():
    return f"{settings.FRONTEND_URL.rstrip('/')}{SECURITY_URL_PATH}"


def _is_person(user):
    from .teams import internal_users_q

    return bool(user.email) and not get_user_model().objects.filter(internal_users_q(), pk=user.pk).exists()


def _send(user, *, subject, heading, paragraphs, footnote="Si no fuiste vos, cambiá tu contraseña y revisá tus sesiones abiertas."):
    if not _is_person(user):
        return False
    url = _security_url()
    text = "Hola,\n\n" + "\n\n".join(paragraphs) + f"\n\nSeguridad de tu cuenta: {url}\n\n{footnote}\n"
    try:
        send_mail(
            subject=f"{subject} — Human Log · Rótulos",
            message=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
            html_message=branded_html(
                heading=heading, paragraphs=paragraphs, action=("Ver la seguridad de mi cuenta", url), footnote=footnote
            ),
        )
        return True
    except Exception:  # noqa: BLE001 — el aviso no puede cortar el ingreso ni el cambio
        logger.exception("No se pudo mandar el aviso de seguridad", extra={"user_id": user.pk, "subject": subject})
        return False


def _when():
    return timezone.localtime().strftime("%d/%m/%Y %H:%M")


def recovery_code_used_mail(user, left: int):
    return _send(
        user,
        subject="Usaste un código de recuperación",
        heading="Entraste con un código de recuperación",
        paragraphs=[
            f"El {_when()} alguien entró a tu cuenta con uno de tus códigos de recuperación.",
            f"Te quedan {left}. Si ya no tenés el celular con la app, desactivá la verificación y volvé a activarla.",
        ],
    )


def mfa_enabled_mail(user, method_label: str):
    return _send(
        user,
        subject="Activaste la verificación en dos pasos",
        heading="Tu cuenta ahora pide un código al entrar",
        paragraphs=[f"El {_when()} activaste la verificación en dos pasos con: {method_label}."],
    )


def mfa_disabled_mail(user, *, by_admin: bool):
    if by_admin:
        paragraphs = [
            f"El {_when()} un administrador de la plataforma quitó la verificación en dos pasos de tu cuenta.",
            "Si no lo pediste, escribí a soporte desde Ayuda.",
        ]
    else:
        paragraphs = [f"El {_when()} desactivaste la verificación en dos pasos de tu cuenta."]
    return _send(
        user,
        subject="Se desactivó la verificación en dos pasos",
        heading="Tu cuenta ya no pide un código al entrar",
        paragraphs=paragraphs,
    )
