"""
Crea el administrador inicial a partir de variables de entorno.

Uso:  ADMIN_USERNAME=admin ADMIN_PASSWORD=... python manage.py crear_admin

Pensado para el arranque en Docker (ver entrypoint.sh). Es idempotente: si el
usuario ya existe no hace nada, y si faltan las variables se omite sin error.
El usuario queda como superusuario y en el rol "Administrador".
La contraseña debe pasar los validadores de Django (largo mínimo, no común, etc.).
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea el usuario administrador inicial desde ADMIN_USERNAME y ADMIN_PASSWORD."

    def handle(self, *args, **options):
        nombre = os.environ.get("ADMIN_USERNAME", "").strip()
        clave = os.environ.get("ADMIN_PASSWORD", "")
        correo = os.environ.get("ADMIN_EMAIL", "").strip()

        if not nombre or not clave:
            self.stdout.write("ADMIN_USERNAME/ADMIN_PASSWORD no definidos: no se crea administrador.")
            return

        Usuario = get_user_model()
        if Usuario.objects.filter(username=nombre).exists():
            self.stdout.write(f"El usuario '{nombre}' ya existe: no se modifica.")
            return

        try:
            validate_password(clave)
        except ValidationError as error:
            raise CommandError("ADMIN_PASSWORD no es segura: " + " ".join(error.messages))

        usuario = Usuario.objects.create_superuser(username=nombre, email=correo, password=clave)
        grupo = Group.objects.filter(name="Administrador").first()
        if grupo:
            usuario.groups.add(grupo)
        self.stdout.write(self.style.SUCCESS(f"Administrador '{nombre}' creado."))
