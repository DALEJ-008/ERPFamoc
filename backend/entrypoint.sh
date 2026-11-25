#!/bin/sh
# Prepara la base de datos y arranca el servidor. Se ejecuta en cada inicio del
# contenedor; todos los pasos son idempotentes.
set -e

echo "==> Aplicando migraciones"
python manage.py migrate --noinput

echo "==> Configurando roles"
python manage.py configurar_roles

# Catálogo de ejemplo (solo si LOAD_SAMPLE_DATA=1).
if [ "${LOAD_SAMPLE_DATA:-0}" = "1" ]; then
    echo "==> Cargando catálogo de ejemplo"
    python manage.py cargar_muebles
fi

# Administrador inicial (si ADMIN_USERNAME y ADMIN_PASSWORD están definidos).
python manage.py crear_admin

echo "==> Iniciando servidor"
exec "$@"
