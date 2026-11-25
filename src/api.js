// Cliente HTTP para la API de Django (prefijo /api).
//
// Autenticación con JWT:
//  - El access token (corto) vive SOLO en memoria: no se guarda en localStorage,
//    así un script inyectado (XSS) no puede robarlo del almacenamiento.
//  - El refresh token es una cookie httpOnly que el navegador envía solo a /api/;
//    JavaScript no puede leerla. Se usa para pedir un access nuevo.

const BASE_URL = '/api'
const SIN_SESION = { autenticado: false, permisos: [], roles: [] }

let tokenAcceso = null
// Si varias peticiones reciben 401 a la vez, comparten una sola renovación.
let renovacionEnCurso = null

async function leerRespuesta(respuesta) {
  const datos = await respuesta.json().catch(() => null)
  if (!respuesta.ok) {
    const error = new Error(datos?.error || `El servidor respondió con error ${respuesta.status}.`)
    error.status = respuesta.status
    throw error
  }
  return datos
}

async function enviar(ruta, { method = 'GET', body } = {}) {
  const cabeceras = {}
  if (body !== undefined) cabeceras['Content-Type'] = 'application/json'
  if (tokenAcceso) cabeceras['Authorization'] = `Bearer ${tokenAcceso}`

  try {
    return await fetch(`${BASE_URL}${ruta}`, {
      method,
      credentials: 'same-origin',
      headers: cabeceras,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error('No se pudo conectar con el servidor. Verifica que el backend esté en ejecución.')
  }
}

// Guarda el access token y devuelve la sesión sin los campos del token.
function procesarSesion({ access_token, expires_in, ...sesion }) {
  tokenAcceso = access_token || null
  return sesion
}

// Pide un access token nuevo usando la cookie de refresh.
function renovarSesion() {
  if (!renovacionEnCurso) {
    renovacionEnCurso = enviar('/refresh/', { method: 'POST' })
      .then(leerRespuesta)
      .then(procesarSesion)
      .catch((error) => {
        tokenAcceso = null
        throw error
      })
      .finally(() => {
        renovacionEnCurso = null
      })
  }
  return renovacionEnCurso
}

async function peticion(ruta, opciones) {
  let respuesta = await enviar(ruta, opciones)

  // Access token vencido: se renueva una vez y se repite la petición.
  if (respuesta.status === 401) {
    try {
      await renovarSesion()
      respuesta = await enviar(ruta, opciones)
    } catch {
      // Sin refresh válido: se devuelve el 401 original para que la app cierre la sesión.
    }
  }
  return leerRespuesta(respuesta)
}

// Sesión
// Al abrir la página no hay access token en memoria: se intenta recuperar la sesión
// con la cookie de refresh. Si no hay sesión previa, devuelve "no autenticado".
export async function restaurarSesion() {
  try {
    return await renovarSesion()
  } catch (error) {
    if (error.status === 401) return SIN_SESION
    throw error
  }
}

export async function iniciarSesion(usuario, clave) {
  const respuesta = await enviar('/login/', { method: 'POST', body: { usuario, clave } })
  return procesarSesion(await leerRespuesta(respuesta))
}

export async function cerrarSesion() {
  try {
    await enviar('/logout/', { method: 'POST' })
  } finally {
    tokenAcceso = null
  }
}

// Datos
export const obtenerMuebles = () => peticion('/muebles/')
export const obtenerClientes = () => peticion('/clientes/')
export const crearCliente = (cliente) => peticion('/clientes/', { method: 'POST', body: cliente })
export const eliminarCliente = (id) => peticion(`/clientes/${id}/`, { method: 'DELETE' })
export const obtenerCotizaciones = () => peticion('/cotizaciones/')
export const crearCotizacion = (cotizacion) => peticion('/cotizaciones/', { method: 'POST', body: cotizacion })
export const obtenerBitacora = () => peticion('/bitacora/')

// Inventario
export const obtenerExistencias = () => peticion('/inventario/')
export const obtenerMovimientos = () => peticion('/movimientos/')
export const registrarMovimiento = (movimiento) => peticion('/movimientos/', { method: 'POST', body: movimiento })
