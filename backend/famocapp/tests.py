import json
import time

import jwt
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import Client, TestCase

from . import jwt_auth
from .models import Bitacora, Cliente, Cotizacion, Existencia, Mueble, MovimientoInventario

PASSWORD = "Clave-segura-2026"


class _ApiTestCase(TestCase):
    def setUp(self):
        call_command("configurar_roles", verbosity=0)

    def crear_usuario(self, rol, nombre):
        usuario = User.objects.create_user(username=nombre, password=PASSWORD)
        usuario.groups.add(Group.objects.get(name=rol))
        return usuario

    def entrar_como(self, rol, nombre):
        """Crea el usuario y hace que el cliente de pruebas envíe su access token JWT."""
        usuario = self.crear_usuario(rol, nombre)
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {jwt_auth.crear_access(usuario)}"
        return usuario

    def login(self, nombre, clave=PASSWORD, cliente=None):
        return self._post("/api/login/", {"usuario": nombre, "clave": clave}, cliente=cliente)

    def _post(self, url, datos, cliente=None):
        cliente = cliente or self.client
        return cliente.post(url, data=json.dumps(datos), content_type="application/json")


class ClientesApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        self.comercial = self.entrar_como("Comercial", "comercial")

    def test_crear_y_listar_cliente(self):
        r = self._post("/api/clientes/", {"nombre": "Ana Pérez", "telefono": "300", "ciudad": "Bogotá"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["nombre"], "Ana Pérez")
        self.assertEqual(Cliente.objects.get().creado_por, self.comercial)

        r = self.client.get("/api/clientes/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)

    def test_nombre_obligatorio(self):
        r = self._post("/api/clientes/", {"nombre": "   "})
        self.assertEqual(r.status_code, 400)

    def test_ciudad_debe_ser_una_sede(self):
        r = self._post("/api/clientes/", {"nombre": "Ana", "ciudad": "Cali"})
        self.assertEqual(r.status_code, 400)

    def test_json_invalido(self):
        r = self.client.post("/api/clientes/", data="{no es json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_comercial_no_puede_eliminar_clientes(self):
        cliente = Cliente.objects.create(nombre="Luis")
        r = self.client.delete(f"/api/clientes/{cliente.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Cliente.objects.filter(pk=cliente.id).exists())

    def test_eliminar_cliente_con_cotizaciones_devuelve_409(self):
        mueble = Mueble.objects.create(nombre="Silla", categoria="Sillas", precio=100)
        cliente = Cliente.objects.create(nombre="Luis")
        self._post(
            "/api/cotizaciones/",
            {"cliente_id": cliente.id, "items": [{"mueble_id": mueble.id, "cantidad": 1}]},
        )
        self.entrar_como("Administrador", "admin")
        r = self.client.delete(f"/api/clientes/{cliente.id}/")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Cliente.objects.filter(pk=cliente.id).exists())

    def test_administrador_elimina_cliente_sin_cotizaciones(self):
        self.entrar_como("Administrador", "admin")
        cliente = Cliente.objects.create(nombre="Marta")
        r = self.client.delete(f"/api/clientes/{cliente.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Cliente.objects.filter(pk=cliente.id).exists())


class AutenticacionTests(_ApiTestCase):
    def test_sin_sesion_los_endpoints_responden_401(self):
        self.assertEqual(self.client.get("/api/clientes/").status_code, 401)
        self.assertEqual(self.client.get("/api/cotizaciones/").status_code, 401)
        self.assertEqual(self.client.get("/api/muebles/").status_code, 401)

    def test_sesion_sin_token_no_esta_autenticada(self):
        r = self.client.get("/api/sesion/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["autenticado"])

    def test_login_correcto_devuelve_roles_permisos_y_tokens(self):
        self.crear_usuario("Comercial", "ana")
        r = self.login("ana")
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertTrue(datos["autenticado"])
        self.assertIn("Comercial", datos["roles"])
        self.assertIn("famocapp.add_cliente", datos["permisos"])
        self.assertTrue(datos["access_token"])
        self.assertEqual(datos["expires_in"], settings.JWT_ACCESS_MINUTES * 60)

        # El refresh token NO va en el JSON: solo en una cookie httpOnly y SameSite=Strict.
        self.assertNotIn("refresh_token", datos)
        cookie = r.cookies[jwt_auth.COOKIE_REFRESH]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/")

    def test_login_incorrecto_responde_401_sin_tokens(self):
        self.crear_usuario("Comercial", "ana")
        r = self.login("ana", clave="otra")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("access_token", r.json())
        self.assertNotIn(jwt_auth.COOKIE_REFRESH, r.cookies)
        self.assertTrue(Bitacora.objects.filter(accion="login_fallido").exists())

    def test_login_de_usuario_inactivo_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        usuario.is_active = False
        usuario.save()
        self.assertEqual(self.login("ana").status_code, 401)

    def test_access_token_del_login_sirve_para_la_api(self):
        self.crear_usuario("Comercial", "ana")
        token = self.login("ana").json()["access_token"]
        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)

    def test_token_malformado_o_esquema_incorrecto_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        for cabecera in ("Bearer basura", "Bearer", "Basic abc", jwt_auth.crear_access(usuario)):
            r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=cabecera)
            self.assertEqual(r.status_code, 401, cabecera)

    def test_token_expirado_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        vencido = jwt_auth._crear(usuario, jwt_auth.TIPO_ACCESS, -10)
        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {vencido}")
        self.assertEqual(r.status_code, 401)

    def test_token_firmado_con_otra_clave_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        ahora = int(time.time())
        falso = jwt.encode(
            {"sub": str(usuario.pk), "type": "access", "iat": ahora, "exp": ahora + 600,
             "pwd": jwt_auth._huella_clave(usuario)},
            "clave-del-atacante-que-no-es-la-real-0123456789",
            algorithm="HS256",
        )
        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {falso}")
        self.assertEqual(r.status_code, 401)

    def test_token_con_algoritmo_none_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        ahora = int(time.time())
        sin_firma = jwt.encode(
            {"sub": str(usuario.pk), "type": "access", "iat": ahora, "exp": ahora + 600,
             "pwd": jwt_auth._huella_clave(usuario)},
            None,
            algorithm="none",
        )
        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {sin_firma}")
        self.assertEqual(r.status_code, 401)

    def test_refresh_token_no_sirve_como_access_token(self):
        usuario = self.crear_usuario("Comercial", "ana")
        refresh = jwt_auth.crear_refresh(usuario)
        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {refresh}")
        self.assertEqual(r.status_code, 401)

    def test_access_token_no_sirve_como_refresh_token(self):
        usuario = self.crear_usuario("Comercial", "ana")
        self.client.cookies[jwt_auth.COOKIE_REFRESH] = jwt_auth.crear_access(usuario)
        self.assertEqual(self._post("/api/refresh/", {}).status_code, 401)

    def test_usuario_desactivado_pierde_acceso_aunque_el_token_no_haya_vencido(self):
        usuario = self.entrar_como("Comercial", "ana")
        self.assertEqual(self.client.get("/api/clientes/").status_code, 200)
        usuario.is_active = False
        usuario.save()
        self.assertEqual(self.client.get("/api/clientes/").status_code, 401)

    def test_cambiar_la_contrasena_invalida_los_tokens_anteriores(self):
        usuario = self.entrar_como("Comercial", "ana")
        self.assertEqual(self.client.get("/api/clientes/").status_code, 200)
        usuario.set_password("Otra-clave-2026")
        usuario.save()
        self.assertEqual(self.client.get("/api/clientes/").status_code, 401)

    def test_cambio_de_rol_se_aplica_de_inmediato(self):
        usuario = self.entrar_como("Comercial", "ana")
        self.assertEqual(self._post("/api/clientes/", {"nombre": "Ana"}).status_code, 201)
        usuario.groups.set([Group.objects.get(name="Consulta")])
        self.assertEqual(self._post("/api/clientes/", {"nombre": "Luis"}).status_code, 403)

    def test_refresh_con_cookie_entrega_nuevo_access_y_rota_el_refresh(self):
        self.crear_usuario("Comercial", "ana")
        self.login("ana")
        antes = self.client.cookies[jwt_auth.COOKIE_REFRESH].value

        r = self._post("/api/refresh/", {})
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertTrue(datos["autenticado"])
        self.assertTrue(datos["access_token"])
        self.assertNotEqual(self.client.cookies[jwt_auth.COOKIE_REFRESH].value, antes)

        r = self.client.get("/api/clientes/", HTTP_AUTHORIZATION=f"Bearer {datos['access_token']}")
        self.assertEqual(r.status_code, 200)

    def test_refresh_sin_cookie_responde_401(self):
        self.assertEqual(self._post("/api/refresh/", {}).status_code, 401)

    def test_refresh_con_cookie_vencida_responde_401(self):
        usuario = self.crear_usuario("Comercial", "ana")
        self.client.cookies[jwt_auth.COOKIE_REFRESH] = jwt_auth._crear(usuario, jwt_auth.TIPO_REFRESH, -10)
        self.assertEqual(self._post("/api/refresh/", {}).status_code, 401)

    def test_la_cookie_de_sesion_de_django_no_autentica_la_api(self):
        usuario = self.crear_usuario("Administrador", "admin")
        self.client.force_login(usuario)  # sesión de Django (la del /admin/)
        self.assertEqual(self.client.get("/api/clientes/").status_code, 401)

    def test_la_api_no_necesita_csrf_porque_usa_bearer(self):
        usuario = self.crear_usuario("Comercial", "ana")
        cliente = Client(enforce_csrf_checks=True)
        cliente.defaults["HTTP_AUTHORIZATION"] = f"Bearer {jwt_auth.crear_access(usuario)}"
        r = self._post("/api/clientes/", {"nombre": "Ana"}, cliente=cliente)
        self.assertEqual(r.status_code, 201)

    def test_logout_borra_la_cookie_refresh_y_deja_registro(self):
        self.crear_usuario("Comercial", "ana")
        self.login("ana")
        r = self._post("/api/logout/", {})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["autenticado"])
        self.assertEqual(r.cookies[jwt_auth.COOKIE_REFRESH].value, "")
        self.assertTrue(Bitacora.objects.filter(accion="logout", usuario__username="ana").exists())
        # Sin cookie ya no se puede renovar.
        self.assertEqual(self._post("/api/refresh/", {}).status_code, 401)

    def test_consulta_no_puede_crear_clientes(self):
        self.entrar_como("Consulta", "consulta")
        r = self._post("/api/clientes/", {"nombre": "Ana"})
        self.assertEqual(r.status_code, 403)

    def test_consulta_puede_ver_muebles(self):
        self.entrar_como("Consulta", "consulta")
        self.assertEqual(self.client.get("/api/muebles/").status_code, 200)

    def test_bitacora_solo_para_administradores(self):
        self.entrar_como("Comercial", "ana")
        self.assertEqual(self.client.get("/api/bitacora/").status_code, 403)

        self.entrar_como("Administrador", "admin")
        self.assertEqual(self.client.get("/api/bitacora/").status_code, 200)

    def test_bitacora_registra_altas(self):
        self.entrar_como("Comercial", "ana")
        self._post("/api/clientes/", {"nombre": "Ana"})

        self.entrar_como("Administrador", "admin")
        acciones = [r["accion"] for r in self.client.get("/api/bitacora/").json()]
        self.assertIn("cliente_creado", acciones)


class MueblesApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        self.entrar_como("Consulta", "consulta")

    def test_solo_muestra_muebles_activos(self):
        Mueble.objects.create(nombre="Activo", categoria="Sillas", precio=10)
        Mueble.objects.create(nombre="Inactivo", categoria="Sillas", precio=10, activo=False)
        r = self.client.get("/api/muebles/")
        nombres = [m["nombre"] for m in r.json()]
        self.assertEqual(nombres, ["Activo"])


class CotizacionesApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        self.comercial = self.entrar_como("Comercial", "comercial")
        self.cliente = Cliente.objects.create(nombre="Carlos")
        self.escritorio = Mueble.objects.create(nombre="Escritorio", categoria="Escritorios", precio=1000)
        self.silla = Mueble.objects.create(nombre="Silla", categoria="Sillas", precio=500)

    def test_total_se_calcula_en_el_servidor(self):
        r = self._post(
            "/api/cotizaciones/",
            {
                "cliente_id": self.cliente.id,
                "items": [
                    {"mueble_id": self.escritorio.id, "cantidad": 2},
                    {"mueble_id": self.silla.id, "cantidad": 1},
                ],
            },
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["total"], 2500)
        self.assertEqual(Cotizacion.objects.get().total, 2500)

    def test_precio_enviado_por_el_cliente_se_ignora(self):
        r = self._post(
            "/api/cotizaciones/",
            {
                "cliente_id": self.cliente.id,
                "items": [{"mueble_id": self.silla.id, "cantidad": 1, "precio": 1}],
            },
        )
        self.assertEqual(r.json()["total"], 500)

    def test_sin_items_es_error(self):
        r = self._post("/api/cotizaciones/", {"cliente_id": self.cliente.id, "items": []})
        self.assertEqual(r.status_code, 400)

    def test_mueble_inexistente_es_error(self):
        r = self._post(
            "/api/cotizaciones/",
            {"cliente_id": self.cliente.id, "items": [{"mueble_id": 999999, "cantidad": 1}]},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Cotizacion.objects.count(), 0)

    def test_cantidad_debe_ser_positiva(self):
        r = self._post(
            "/api/cotizaciones/",
            {"cliente_id": self.cliente.id, "items": [{"mueble_id": self.silla.id, "cantidad": 0}]},
        )
        self.assertEqual(r.status_code, 400)

    def test_cliente_inexistente_es_error(self):
        r = self._post(
            "/api/cotizaciones/",
            {"cliente_id": 999999, "items": [{"mueble_id": self.silla.id, "cantidad": 1}]},
        )
        self.assertEqual(r.status_code, 400)

    def test_listar_cotizaciones_incluye_items_y_autor(self):
        self._post(
            "/api/cotizaciones/",
            {"cliente_id": self.cliente.id, "items": [{"mueble_id": self.silla.id, "cantidad": 2}]},
        )
        r = self.client.get("/api/cotizaciones/")
        self.assertEqual(len(r.json()), 1)
        cotizacion = r.json()[0]
        self.assertEqual(cotizacion["cliente_nombre"], "Carlos")
        self.assertEqual(cotizacion["creado_por"], "comercial")
        self.assertEqual(cotizacion["items"][0]["subtotal"], 1000)

    def test_cotizacion_queda_registrada_en_bitacora(self):
        self._post(
            "/api/cotizaciones/",
            {"cliente_id": self.cliente.id, "items": [{"mueble_id": self.silla.id, "cantidad": 1}]},
        )
        self.assertTrue(Bitacora.objects.filter(accion="cotizacion_creada").exists())

    def test_consulta_no_puede_crear_cotizaciones(self):
        self.entrar_como("Consulta", "consulta")
        r = self._post(
            "/api/cotizaciones/",
            {"cliente_id": self.cliente.id, "items": [{"mueble_id": self.silla.id, "cantidad": 1}]},
        )
        self.assertEqual(r.status_code, 403)



class InventarioApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        self.bodega = self.entrar_como("Bodega", "bodega")
        self.silla = Mueble.objects.create(nombre="Silla", categoria="Sillas", precio=500)

    def _movimiento(self, tipo, cantidad, sede="Bogotá", motivo="", mueble=None):
        return self._post(
            "/api/movimientos/",
            {
                "mueble_id": (mueble or self.silla).id,
                "sede": sede,
                "tipo": tipo,
                "cantidad": cantidad,
                "motivo": motivo,
            },
        )

    def test_entrada_suma_existencia(self):
        r = self._movimiento("entrada", 10)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["existencia"]["cantidad"], 10)
        self.assertEqual(r.json()["movimiento"]["delta"], 10)

    def test_salida_resta_existencia(self):
        self._movimiento("entrada", 10)
        r = self._movimiento("salida", 4)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["existencia"]["cantidad"], 6)
        self.assertEqual(r.json()["movimiento"]["delta"], -4)
        self.assertEqual(r.json()["movimiento"]["saldo"], 6)

    def test_salida_sin_stock_se_rechaza_sin_dejar_rastro(self):
        r = self._movimiento("salida", 1)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(MovimientoInventario.objects.count(), 0)
        self.assertEqual(Existencia.objects.count(), 0)

    def test_ajuste_negativo_no_deja_saldo_negativo(self):
        self._movimiento("entrada", 3)
        r = self._movimiento("ajuste", -5, motivo="conteo físico")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Existencia.objects.get().cantidad, 3)

    def test_ajuste_requiere_motivo(self):
        r = self._movimiento("ajuste", 2)
        self.assertEqual(r.status_code, 400)

    def test_ajuste_con_motivo_positivo_funciona(self):
        r = self._movimiento("ajuste", 2, motivo="sobrante en conteo")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Existencia.objects.get().cantidad, 2)

    def test_cantidad_debe_ser_positiva_en_entradas_y_salidas(self):
        self.assertEqual(self._movimiento("entrada", 0).status_code, 400)
        self.assertEqual(self._movimiento("salida", -2).status_code, 400)

    def test_sede_invalida(self):
        r = self._movimiento("entrada", 1, sede="Cali")
        self.assertEqual(r.status_code, 400)

    def test_tipo_invalido(self):
        r = self._movimiento("prestamo", 1)
        self.assertEqual(r.status_code, 400)

    def test_saldo_coincide_con_suma_de_movimientos(self):
        self._movimiento("entrada", 10)
        self._movimiento("salida", 3)
        self._movimiento("ajuste", 2, motivo="conteo")
        existencia = Existencia.objects.get()
        suma = sum(m.delta for m in MovimientoInventario.objects.all())
        self.assertEqual(existencia.cantidad, 9)
        self.assertEqual(suma, existencia.cantidad)

    def test_stock_se_separa_por_sede(self):
        self._movimiento("entrada", 5, sede="Bogotá")
        self._movimiento("entrada", 2, sede="Miami")
        r = self.client.get("/api/inventario/?sede=Miami")
        self.assertEqual([e["cantidad"] for e in r.json()], [2])

    def test_movimiento_queda_en_bitacora(self):
        self._movimiento("entrada", 1)
        self.assertTrue(Bitacora.objects.filter(accion="movimiento_inventario").exists())

    def test_comercial_puede_consultar_pero_no_registrar(self):
        self._movimiento("entrada", 4)
        self.entrar_como("Comercial", "comercial")
        self.assertEqual(self.client.get("/api/inventario/").status_code, 200)
        self.assertEqual(self.client.get("/api/movimientos/").status_code, 403)
        self.assertEqual(self._movimiento("entrada", 1).status_code, 403)

    def test_consulta_no_puede_registrar(self):
        self.entrar_como("Consulta", "consulta")
        self.assertEqual(self._movimiento("entrada", 1).status_code, 403)


class CrearAdminTests(TestCase):
    def setUp(self):
        call_command("configurar_roles", verbosity=0)

    def _ejecutar(self, **entorno):
        from unittest import mock

        with mock.patch.dict("os.environ", entorno, clear=False):
            call_command("crear_admin", verbosity=0)

    def test_crea_superusuario_con_rol_administrador(self):
        self._ejecutar(ADMIN_USERNAME="jefe", ADMIN_PASSWORD="Clave-segura-2026")
        usuario = User.objects.get(username="jefe")
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.groups.filter(name="Administrador").exists())
        self.assertTrue(usuario.check_password("Clave-segura-2026"))

    def test_es_idempotente_y_no_cambia_la_clave_existente(self):
        self._ejecutar(ADMIN_USERNAME="jefe", ADMIN_PASSWORD="Clave-segura-2026")
        self._ejecutar(ADMIN_USERNAME="jefe", ADMIN_PASSWORD="Otra-clave-2026")
        self.assertEqual(User.objects.filter(username="jefe").count(), 1)
        self.assertTrue(User.objects.get(username="jefe").check_password("Clave-segura-2026"))

    def test_rechaza_contrasena_debil(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._ejecutar(ADMIN_USERNAME="jefe", ADMIN_PASSWORD="1234")
        self.assertFalse(User.objects.filter(username="jefe").exists())

    def test_sin_variables_no_hace_nada(self):
        from unittest import mock

        with mock.patch.dict("os.environ", {}, clear=True):
            call_command("crear_admin", verbosity=0)
        self.assertFalse(User.objects.exists())

    def test_admin_creado_puede_iniciar_sesion_en_la_api(self):
        self._ejecutar(ADMIN_USERNAME="jefe", ADMIN_PASSWORD="Clave-segura-2026")
        r = self.client.post(
            "/api/login/",
            data=json.dumps({"usuario": "jefe", "clave": "Clave-segura-2026"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("Administrador", r.json()["roles"])
        self.assertIn("famocapp.view_bitacora", r.json()["permisos"])


class ConfiguracionJwtTests(TestCase):
    def test_clave_jwt_nunca_esta_vacia(self):
        # Compose pasa JWT_SECRET_KEY="" cuando no se define: debe usarse SECRET_KEY.
        import importlib
        import os
        from unittest import mock

        from erpfamoc import settings as ajustes

        with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": "", "DJANGO_SECRET_KEY": "una-clave-propia-larga"}):
            recargado = importlib.reload(ajustes)
            self.assertEqual(recargado.JWT_SECRET_KEY, "una-clave-propia-larga")
        importlib.reload(ajustes)

    def test_produccion_exige_clave_propia(self):
        import importlib
        import os
        from unittest import mock

        from django.core.exceptions import ImproperlyConfigured

        from erpfamoc import settings as ajustes

        entorno = {"DJANGO_DEBUG": "0"}
        with mock.patch.dict(os.environ, entorno):
            os.environ.pop("DJANGO_SECRET_KEY", None)
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(ajustes)
        importlib.reload(ajustes)


class BaseDeDatosDesdeUrlTests(TestCase):
    def test_interpreta_la_url_de_render(self):
        from erpfamoc.settings import _base_desde_url

        c = _base_desde_url("postgresql://erp_user:p%40ss%2Fw@dpg-abc-a:5432/erp_famoc")
        self.assertEqual(c["USER"], "erp_user")
        self.assertEqual(c["PASSWORD"], "p@ss/w")  # caracteres especiales decodificados
        self.assertEqual(c["HOST"], "dpg-abc-a")
        self.assertEqual(c["PORT"], "5432")
        self.assertEqual(c["NAME"], "erp_famoc")
        self.assertIn("postgresql", c["ENGINE"])

    def test_rechaza_otros_esquemas(self):
        from django.core.exceptions import ImproperlyConfigured

        from erpfamoc.settings import _base_desde_url

        with self.assertRaises(ImproperlyConfigured):
            _base_desde_url("mysql://u:p@h/db")
