"""
Autenticación con JWT para la API del ERP Famoc.

Dos tokens firmados con HS256:

* access  — vida corta (15 min por defecto). El frontend lo guarda solo en
            memoria y lo envía en `Authorization: Bearer <token>`.
* refresh — vida larga (8 h por defecto). Viaja en una cookie httpOnly con
            SameSite=Strict, así que JavaScript no puede leerla. Sirve únicamente
            para pedir un access nuevo en POST /api/refresh/.

Cada token lleva el tipo (`type`), de modo que un refresh no se puede usar como
access ni al revés, y una huella de la contraseña (`pwd`): si el usuario cambia
su contraseña o es desactivado, todos sus tokens dejan de valer.
"""

import hashlib
import hmac
import time
import uuid

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model

ALGORITMO = "HS256"
COOKIE_REFRESH = "refresh_token"
TIPO_ACCESS = "access"
TIPO_REFRESH = "refresh"


class TokenInvalido(Exception):
    """El token falta, está mal formado, expiró o ya no corresponde a un usuario válido."""


def _huella_clave(usuario):
    # Parte del hash de la contraseña: cambia cuando el usuario cambia su clave.
    return hashlib.sha256(usuario.password.encode()).hexdigest()[:16]


def _crear(usuario, tipo, vida_segundos):
    ahora = int(time.time())
    carga = {
        "sub": str(usuario.pk),
        "type": tipo,
        "iat": ahora,
        "exp": ahora + vida_segundos,
        "jti": uuid.uuid4().hex,
        "pwd": _huella_clave(usuario),
    }
    return jwt.encode(carga, settings.JWT_SECRET_KEY, algorithm=ALGORITMO)


def vida_access():
    return settings.JWT_ACCESS_MINUTES * 60


def vida_refresh():
    return settings.JWT_REFRESH_HOURS * 3600


def crear_access(usuario):
    return _crear(usuario, TIPO_ACCESS, vida_access())


def crear_refresh(usuario):
    return _crear(usuario, TIPO_REFRESH, vida_refresh())


def verificar(token, tipo):
    """Devuelve el usuario dueño del token o lanza TokenInvalido."""
    if not token:
        raise TokenInvalido("Falta el token.")
    try:
        carga = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            # Lista explícita: nunca se acepta el algoritmo que declare el token (p. ej. "none").
            algorithms=[ALGORITMO],
            options={"require": ["exp", "iat", "sub", "type", "pwd"]},
        )
    except jwt.InvalidTokenError as exc:  # incluye expirado, firma inválida, mal formado
        raise TokenInvalido(str(exc)) from exc

    if carga["type"] != tipo:
        raise TokenInvalido("Tipo de token incorrecto.")

    try:
        usuario = get_user_model().objects.filter(pk=carga["sub"], is_active=True).first()
    except (ValueError, TypeError):
        usuario = None
    if usuario is None:
        raise TokenInvalido("El usuario no existe o está inactivo.")
    if not hmac.compare_digest(str(carga["pwd"]), _huella_clave(usuario)):
        raise TokenInvalido("La contraseña cambió; inicia sesión de nuevo.")
    return usuario


def usuario_desde_cabecera(request):
    """Usuario del header `Authorization: Bearer <access>`, o None si no hay uno válido."""
    cabecera = request.META.get("HTTP_AUTHORIZATION", "")
    partes = cabecera.split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    try:
        return verificar(partes[1].strip(), TIPO_ACCESS)
    except TokenInvalido:
        return None


def usuario_desde_cookie_refresh(request):
    """Usuario de la cookie de refresh, o None si no hay una válida."""
    try:
        return verificar(request.COOKIES.get(COOKIE_REFRESH), TIPO_REFRESH)
    except TokenInvalido:
        return None


def poner_cookie_refresh(respuesta, token):
    respuesta.set_cookie(
        COOKIE_REFRESH,
        token,
        max_age=vida_refresh(),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite="Strict",
        path="/api/",
    )


def borrar_cookie_refresh(respuesta):
    respuesta.delete_cookie(COOKIE_REFRESH, path="/api/", samesite="Strict")
