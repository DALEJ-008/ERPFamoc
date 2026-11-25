# ERP Famoc — Comercial e Inventarios

Sistema ERP web para Famoc Depanel. Esta versión cubre los módulos **Comercial**
(clientes, catálogo, cotizaciones) e **Inventarios** (existencias por sede y movimientos),
con **inicio de sesión con JWT, roles y bitácora**.

- **Backend:** Django + API REST propia (`/api/`), PostgreSQL, autenticación **JWT**.
- **Frontend:** React + Vite.
- **Despliegue:** **Docker Compose** (PostgreSQL + Django/gunicorn + nginx), listo para publicarse en la web.

## Arquitectura

```
Navegador ──► nginx (web, :80) ──┬─► archivos estáticos del frontend (React)
                                 ├─► /api/    ──► Django + gunicorn (backend :8000) ──► PostgreSQL (db)
                                 └─► /admin/  ──► Django (panel de administración)
```

Solo `web` publica un puerto; el backend y la base de datos quedan en la red interna de Docker.

## Funcionalidades

| Issue | Historia | Dónde |
|------|----------|-------|
| #11 | Ver el catálogo de muebles | Pestaña **Catálogo** |
| #10 | Registrar una cotización con varios muebles | Pestaña **Cotizaciones** |
| #12 | Consultar cotizaciones registradas | Pestaña **Cotizaciones** (tabla inferior) |
| #13 | Registrar y administrar clientes | Pestaña **Clientes** |
| RF-03 | Usuarios, roles, permisos y trazabilidad | Inicio de sesión (JWT), pestaña **Bitácora** |
| RF-04 | Módulo de Inventarios | Pestaña **Inventario** (existencias y movimientos por sede) |

Reglas de negocio en el servidor:

- El total y los precios de una cotización se calculan en Django; el precio queda guardado en cada ítem.
- No se puede eliminar un cliente con cotizaciones (responde 409).
- El stock solo cambia mediante movimientos (entrada, salida o ajuste) y nunca queda negativo.
  Cada movimiento se hace en una transacción con bloqueo de fila, así dos operaciones simultáneas
  no pueden leer el mismo saldo.
- Los ajustes exigen un motivo. Los movimientos quedan en la bitácora.
- Las cotizaciones **no descuentan stock**: una cotización no es una venta. Descontar inventario
  al vender requiere un módulo de pedidos o ventas, que está pendiente.

## Autenticación con JWT

El inicio de sesión usa dos tokens firmados (HS256):

| Token | Vida | Dónde vive | Para qué |
|-------|------|-----------|----------|
| **access** | 15 min (`JWT_ACCESS_MINUTES`) | Solo en la **memoria** del navegador | Se envía en cada petición: `Authorization: Bearer <token>` |
| **refresh** | 8 h (`JWT_REFRESH_HOURS`) | Cookie **`HttpOnly`**, `SameSite=Strict`, `Path=/api/` | Pedir un access nuevo en `POST /api/refresh/` |

Flujo: `POST /api/login/` devuelve el access token en el JSON y deja el refresh en la cookie.
Cuando el access vence, el frontend recibe un 401, llama a `/api/refresh/` y repite la petición
sin que el usuario lo note. Al recargar la página (la memoria se vacía) la sesión se recupera
con la cookie. `POST /api/logout/` borra la cookie.

Decisiones de seguridad:

- El access token **no se guarda en `localStorage`**: un script inyectado (XSS) no puede leerlo del almacenamiento. El refresh es `HttpOnly`, así que JavaScript tampoco puede leerlo.
- Cada token lleva su tipo: un refresh no sirve como access ni al revés. Solo se acepta HS256 (se rechaza `alg: none`).
- Los tokens dejan de valer si el usuario se **desactiva** o **cambia su contraseña**. Los **permisos se leen de la base de datos en cada petición**, así que un cambio de rol aplica de inmediato.
- La API **ignora la cookie de sesión de Django** (esa solo la usa `/admin/`). Como ninguna petición se autentica con una cookie que el navegador envíe solo, la API no necesita CSRF.
- En producción (`DJANGO_DEBUG=0`) el servidor **no arranca** sin una `DJANGO_SECRET_KEY` propia: con la clave de desarrollo cualquiera podría fabricar tokens.

Limitación conocida: los tokens son sin estado, así que un refresh robado sigue valiendo hasta
que vence (8 h) o el usuario cambia su contraseña. Para revocación inmediata habría que guardar
los refresh en la base de datos.

## Roles y permisos

Los permisos se asignan por rol. `python manage.py configurar_roles` crea estos roles:

| Rol | Puede |
|-----|-------|
| **Administrador** | Todo, incluida la bitácora y eliminar clientes |
| **Comercial** | Ver y registrar clientes; ver catálogo y existencias; crear y consultar cotizaciones |
| **Bodega** | Ver catálogo y existencias; registrar movimientos de inventario |
| **Consulta** | Solo consultar clientes, catálogo, cotizaciones y existencias |

La interfaz muestra solo las pestañas y botones que el usuario puede usar, y la API
los verifica de nuevo en cada petición. Las acciones quedan registradas en la bitácora
con el usuario que las hizo.

---

## Opción A — Ejecutar con Docker (recomendado)

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env
# Edita .env: define DJANGO_SECRET_KEY, DB_PASSWORD y ADMIN_PASSWORD
docker compose up -d --build
```

Genera una clave secreta aleatoria con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Abre **http://localhost** (o `http://localhost:<WEB_PORT>`) e inicia sesión con `ADMIN_USERNAME` /
`ADMIN_PASSWORD`. Al arrancar, el contenedor del backend aplica las migraciones, crea los roles,
carga el catálogo de ejemplo (si `LOAD_SAMPLE_DATA=1`) y crea el administrador (si no existe).
El panel de administración de Django queda en `/admin/`: ahí se crean más usuarios y se les
asigna un rol en el campo **Grupos**.

Comandos útiles:

```bash
docker compose logs -f backend            # ver registros
docker compose exec backend python manage.py test famocapp   # correr las pruebas (usa PostgreSQL)
docker compose down                       # detener (los datos se conservan en el volumen pgdata)
docker compose down -v                    # detener Y borrar la base de datos
docker compose exec db pg_dump -U postgres ERP_Famoc > respaldo.sql   # respaldo
```

## Publicarlo gratis en Render

Render construye la imagen por ti (`Dockerfile.render`) y crea la base de datos PostgreSQL
(`render.yaml`). En este modo un solo servicio entrega la página, la API y el admin.

1. Sube el proyecto a GitHub.
2. Crea una cuenta en [render.com](https://render.com) (puedes entrar con GitHub).
3. Pulsa **New + → Blueprint**, elige tu repositorio y Render leerá `render.yaml`.
4. Render te pedirá `ADMIN_PASSWORD`: escribe una contraseña segura (mínimo 8 caracteres, no común).
   Es la que usarás para entrar. Pulsa **Apply**.
5. Espera a que termine el despliegue (varios minutos la primera vez). La dirección será
   algo como `https://erp-famoc.onrender.com`. Entra con el usuario `admin` y tu contraseña.

Límites del plan gratis (revísalos en Render, pueden cambiar):

- El servicio **se duerme tras ~15 minutos sin visitas**; el primer acceso después tarda cerca de un minuto.
- La **base de datos gratis expira a los 30 días**. Antes de que venza, crea otra o respalda los datos.
- Tiene poca memoria (512 MB), suficiente para una demostración.

## Publicarlo en un servidor propio (VPS)

Necesitas un servidor con Docker (un VPS en DigitalOcean, Hetzner, AWS Lightsail, etc.) y un dominio
apuntando a su IP.

1. Clona el repositorio en el servidor y crea el `.env` como arriba, con estos valores adicionales:

   ```env
   WEB_PORT=8080
   DJANGO_ALLOWED_HOSTS=erp.midominio.com
   DJANGO_CSRF_TRUSTED_ORIGINS=https://erp.midominio.com
   DJANGO_HTTPS=1
   ```

2. `docker compose up -d --build`
3. Pon **HTTPS** delante. La forma más simple es [Caddy](https://caddyserver.com), que obtiene y
   renueva el certificado solo. Con este `Caddyfile`:

   ```
   erp.midominio.com {
       reverse_proxy localhost:8080
   }
   ```

> Con `DJANGO_HTTPS=1` las cookies se marcan como `Secure`, por lo que el inicio de sesión solo
> funciona por `https://` (o `http://localhost`). Sin HTTPS, deja `DJANGO_HTTPS=0`, pero entonces
> el inicio de sesión viaja sin cifrar: úsalo solo para pruebas.

---

## Opción B — Desarrollo local (sin Docker)

Requisitos: Python 3.12+, Node.js 18+, PostgreSQL 14+ (o SQLite para pruebas rápidas).

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Crea la base de datos `ERP_Famoc` en PostgreSQL y define la contraseña por variable de entorno
(o usa SQLite con `export DB_ENGINE=sqlite`):

```bash
export DB_PASSWORD="tu_contraseña"  # Windows (PowerShell): $env:DB_PASSWORD="..."
```

```bash
python manage.py migrate
python manage.py configurar_roles          # crea los roles
python manage.py cargar_muebles            # catálogo de ejemplo
python manage.py createsuperuser           # primer administrador (luego añádelo al grupo "Administrador")
python manage.py test famocapp             # pruebas automáticas
python manage.py runserver                 # http://127.0.0.1:8000
```

### Frontend

En otra terminal, desde la raíz del proyecto:

```bash
npm install
npm run dev                                # http://localhost:5173
```

Vite reenvía `/api` a Django en el puerto 8000 (ver `vite.config.js`); deja Django corriendo.

## Endpoints de la API

| Método | Ruta | Permiso | Descripción |
|-------|------|---------|-------------|
| POST | `/api/login/` | público | Inicia sesión `{usuario, clave}` → `access_token` + cookie refresh |
| POST | `/api/refresh/` | cookie refresh | Nuevo access token (y rota la cookie refresh) |
| POST | `/api/logout/` | — | Borra la cookie refresh |
| GET | `/api/sesion/` | público | Estado de la sesión según el token enviado |
| GET | `/api/muebles/` | view_mueble | Muebles activos del catálogo |
| GET | `/api/clientes/` | view_cliente | Lista de clientes |
| POST | `/api/clientes/` | add_cliente | Crea un cliente `{nombre, telefono, ciudad}` |
| DELETE | `/api/clientes/<id>/` | delete_cliente | Elimina un cliente (409 si tiene cotizaciones) |
| GET | `/api/cotizaciones/` | view_cotizacion | Cotizaciones con sus ítems |
| POST | `/api/cotizaciones/` | add_cotizacion | Crea una cotización `{cliente_id, items: [{mueble_id, cantidad}]}` |
| GET | `/api/bitacora/` | view_bitacora | Últimos 200 registros de actividad |
| GET | `/api/inventario/?sede=...` | view_existencia | Existencias por mueble y sede (sede opcional) |
| GET | `/api/movimientos/` | view_movimientoinventario | Últimos 200 movimientos de inventario |
| POST | `/api/movimientos/` | add_movimientoinventario | Registra `{mueble_id, sede, tipo, cantidad, motivo}`; tipo: `entrada`, `salida` o `ajuste` (cantidad con signo) |

Los endpoints protegidos requieren `Authorization: Bearer <access_token>`. Sin token válido,
la API responde 401; sin permiso, 403. Las sedes válidas para `ciudad` son: Bogotá, Medellín,
Barranquilla, Miami.

## Variables de entorno

Con Docker se definen en el archivo `.env` (ver `.env.example`).

| Variable | Por defecto | Uso |
|---------|-------------|-----|
| `DJANGO_SECRET_KEY` | valor de desarrollo | Firma de sesiones del admin y de los JWT. **Obligatoria en producción.** |
| `JWT_SECRET_KEY` | = `DJANGO_SECRET_KEY` | Clave propia para los JWT (opcional) |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_HOURS` | `15` / `8` | Vida de los tokens |
| `DJANGO_DEBUG` | `1` (local) / `0` (Docker) | Poner `0` en producción |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts permitidos, separados por coma |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Orígenes que pueden hacer POST al `/admin/` |
| `DJANGO_HTTPS` | `0` | `1` cuando el sitio use HTTPS (cookies `Secure`) |
| `DB_ENGINE` | `postgres` | `sqlite` para pruebas locales |
| `DB_NAME`, `DB_USER`, `DB_HOST`, `DB_PORT` | `ERP_Famoc`, `postgres`, `localhost`, `5432` | Conexión a PostgreSQL |
| `DB_PASSWORD` | vacío | Contraseña de PostgreSQL |
| `DATABASE_URL` | — | Conexión completa a PostgreSQL (la entrega Render); tiene prioridad sobre `DB_*` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` | vacío | Administrador inicial (Docker) |
| `LOAD_SAMPLE_DATA` | `0` | `1` carga el catálogo de ejemplo al arrancar (Docker) |
| `WEB_PORT` | `80` | Puerto público de la aplicación (Docker) |

## Estructura

```
docker-compose.yml     orquesta db + backend + web
Dockerfile.frontend    compila React y lo sirve con nginx (docker-compose)
Dockerfile.render      imagen única (Django + frontend) para Render
render.yaml            Blueprint de Render: servicio web + base de datos
nginx/default.conf     proxy de /api/ y /admin/ hacia Django
.env.example           plantilla de variables (copiar a .env)
backend/
  Dockerfile           imagen de Django con gunicorn
  entrypoint.sh        migra, crea roles/admin y arranca el servidor
  erpfamoc/            configuración del proyecto (settings, urls)
  famocapp/
    models.py          Cliente, Mueble, Cotizacion, CotizacionItem, Bitacora, Existencia, MovimientoInventario
    jwt_auth.py        creación y verificación de tokens JWT
    serializers.py     modelos → JSON
    views.py           API REST con autenticación JWT y permisos
    urls.py            rutas /api/
    admin.py           administración en /admin/ (bitácora de solo lectura)
    tests.py           pruebas de la API, JWT, roles e inventario
    management/commands/
      configurar_roles.py    crea los roles y sus permisos
      cargar_muebles.py      catálogo inicial
      crear_admin.py         administrador inicial desde variables de entorno
src/
  api.js               cliente HTTP: token en memoria, renovación automática
  App.jsx              sesión, navegación y estado
  components/          Login, Catalogo, Clientes, Cotizaciones, Inventario, Bitacora
```

## Pendiente (próximas etapas)

- **Seguridad adicional (RF-03):** recuperación de contraseña, bloqueo tras varios intentos fallidos, revocación inmediata de tokens y autenticación de dos factores.
- **Módulos restantes (RF-04):** Producción, Contabilidad, Administración y Alquileres.
- **Ventas y pedidos:** descontar inventario al confirmar una venta, a partir de una cotización aceptada.
- **Integración de módulos (RF-05)** y **respaldo e integraciones externas (RF-07)**.

## Nota sobre credenciales

Una versión anterior del repositorio tenía la contraseña de PostgreSQL escrita en
`settings.py`. Como el repositorio es público, esa contraseña sigue visible en el historial de Git
y debe considerarse expuesta: **cámbiala en PostgreSQL** y no la reutilices. Nunca subas el
archivo `.env` (ya está en `.gitignore`).
