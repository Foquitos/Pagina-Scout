"""Aplicación FastAPI: sirve las páginas (Jinja2) y la API JSON."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import aparatos
from app.config import (
    CLAVE_SECRETA,
    COOKIES_SEGURAS,
    DIR_ESTATICOS,
    DIR_SUBIDAS,
    MAX_BYTES_PETICION,
)
from app.db import SesionLocal, obtener_sesion
from app.dependencias import Redireccion, plantillas, usuario_actual
from app.models import Usuario
from app.routers import (
    agenda,
    api,
    auth,
    educador,
    especialidades,
    joven,
    participacion,
    patrulla,
)
from app.servicios import moderacion

app = FastAPI(title="Método Scout — Retos de Unidad", docs_url="/api/docs")

app.add_middleware(SessionMiddleware, secret_key=CLAVE_SECRETA, https_only=COOKIES_SEGURAS)

DIR_SUBIDAS.mkdir(parents=True, exist_ok=True)
app.mount("/estaticos", StaticFiles(directory=str(DIR_ESTATICOS)), name="estaticos")


@app.middleware("http")
async def _cuerpo_acotado(request: Request, call_next):
    """Rechaza una petición enorme antes de leerle un solo byte.

    El contenedor corre con 0,5 GiB. Sin esto, un POST de 300 MB lo tumba
    mientras Starlette todavía está armando el formulario, mucho antes de que
    ninguna validación nuestra pueda opinar.

    Se mira el Content-Length, que el navegador siempre manda en un `multipart`.
    Quien lo omita a propósito pasa de largo por acá y lo frena `leer_subida`,
    que nunca acumula más del tope en memoria. Son dos redes: esta corta barato
    el caso normal, la otra sostiene el caso raro.
    """
    largo = request.headers.get("content-length")
    if largo is not None and largo.isdigit() and int(largo) > MAX_BYTES_PETICION:
        return JSONResponse(
            {"detail": f"Eso pesa demasiado (máximo {MAX_BYTES_PETICION // (1024 * 1024)} MB)."},
            status_code=413,
        )
    return await call_next(request)


@app.middleware("http")
async def _de_que_aparato(request: Request, call_next):
    """Le pone —o le renueva— a este navegador su número de aparato.

    Acá y no en el ingreso porque la cookie tiene que estar puesta **antes** de
    que alguien entre: si se sellara recién al ingresar, el primer ingreso de un
    teléfono nunca quedaría atado a él, que es justo el que interesa cuando
    aparece una cuenta prestada.

    Se vuelve a mandar en cada respuesta y eso corre el vencimiento: dos años
    desde la última vez que se usó, no desde que se creó. Un chico que entra todos
    los sábados nunca la pierde. Por qué existe todo esto: `app/aparatos.py`.
    """
    request.state.aparato = request.cookies.get(aparatos.NOMBRE) or aparatos.nuevo()
    respuesta = await call_next(request)
    aparatos.sellar(respuesta, request.state.aparato)
    return respuesta


@app.get("/fotos/{nombre}")
def ver_foto(
    nombre: str,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Una foto se sirve a quien podría ver la página donde vive, y a nadie más.

    Antes esto era un StaticFiles montado y cualquiera con el link entraba sin
    cuenta. Pedir sesión arregló eso pero dejaba lo otro: con sesión, cualquiera
    de cualquier patrulla veía cualquier foto si tenía el uuid. Y el uuid se
    filtra solo —el historial, «copiar dirección de la imagen», una captura
    reenviada—, así que el Libro de Oro quedaba protegido por página y abierto
    por archivo. `moderacion.puede_ver_foto` aplica acá la misma regla que la
    página, y por eso vive en un solo lugar.

    404 y no 403 cuando no corresponde: que exista una foto que no podés ver ya
    es contar algo. `Path(nombre).name` descarta cualquier intento de salir del
    directorio.
    """
    nombre = Path(nombre).name
    ruta = DIR_SUBIDAS / nombre
    if not ruta.is_file() or not moderacion.puede_ver_foto(sesion, nombre, usuario):
        raise HTTPException(404, "Esa foto no existe.")
    # Privada: que la cachee el navegador de quien la vio, no un proxy.
    return FileResponse(ruta, headers={"Cache-Control": "private, max-age=3600"})


app.include_router(auth.router)
app.include_router(joven.router)
app.include_router(patrulla.router)
app.include_router(participacion.router)
app.include_router(agenda.router)
app.include_router(especialidades.router)
app.include_router(educador.router)
app.include_router(api.router)


@app.exception_handler(Redireccion)
def _antes_hay_que_pasar_por(request: Request, exc: Redireccion):
    """Sin sesión, a `/ingresar`; con la contraseña del alta puesta, a `/clave`.

    Un solo manejador para las dos: Starlette busca por la jerarquía de la
    excepción, así que alcanza con registrar la clase de arriba.
    """
    return RedirectResponse(exc.destino, status_code=303)


def _usuario_de_sesion(request: Request) -> Usuario | None:
    """Quién está mirando la página de error, para no perder la navegación.

    Se abre una sesión propia porque las dependencias no corren acá. Si algo
    falla, la página de error igual tiene que salir: por eso el try.
    """
    id_usuario = request.session.get("usuario_id") if "session" in request.scope else None
    if id_usuario is None:
        return None
    try:
        with SesionLocal() as sesion:
            usuario = sesion.get(Usuario, id_usuario)
            if usuario is not None:
                # El pie de página muestra la patrulla: hay que traerla mientras
                # la sesión sigue abierta, porque afuera ya no se puede.
                _ = usuario.patrulla
            return usuario
    except Exception:  # noqa: BLE001 — la página de error nunca debe romperse
        return None


@app.exception_handler(403)
def _sin_permiso(request: Request, exc):
    return plantillas.TemplateResponse(
        request,
        "error.html",
        {
            "titulo": "No tenés acceso a esta página",
            "detalle": getattr(exc, "detail", ""),
            "usuario": _usuario_de_sesion(request),
        },
        status_code=403,
    )


@app.exception_handler(404)
def _no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api"):
        raise exc
    return plantillas.TemplateResponse(
        request,
        "error.html",
        {
            "titulo": "No encontramos eso",
            "detalle": getattr(exc, "detail", ""),
            "usuario": _usuario_de_sesion(request),
        },
        status_code=404,
    )
