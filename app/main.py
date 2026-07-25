"""Aplicación FastAPI: sirve las páginas (Jinja2) y la API JSON."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import CLAVE_SECRETA, DIR_ESTATICOS, DIR_SUBIDAS
from app.dependencias import RedireccionAIngreso, plantillas, usuario_actual
from app.models import Usuario
from app.routers import api, auth, educador, joven

app = FastAPI(title="Método Scout — Retos de Unidad", docs_url="/api/docs")

app.add_middleware(SessionMiddleware, secret_key=CLAVE_SECRETA, https_only=False)

DIR_SUBIDAS.mkdir(parents=True, exist_ok=True)
app.mount("/estaticos", StaticFiles(directory=str(DIR_ESTATICOS)), name="estaticos")


@app.get("/fotos/{nombre}")
def ver_foto(nombre: str, usuario: Usuario = Depends(usuario_actual)):
    """Las fotos subidas piden sesión.

    Antes esto era un StaticFiles montado. El nombre de archivo es un uuid, pero
    aun así cualquiera con el link entraba sin cuenta, y son fotos de chicos.
    Ahora hace falta estar dentro de la aplicación.

    `Path(nombre).name` descarta cualquier intento de salir del directorio.
    """
    ruta = DIR_SUBIDAS / Path(nombre).name
    if not ruta.is_file():
        raise HTTPException(404, "Esa foto no existe.")
    # Privada: que la cachee el navegador de quien la vio, no un proxy.
    return FileResponse(ruta, headers={"Cache-Control": "private, max-age=3600"})


app.include_router(auth.router)
app.include_router(joven.router)
app.include_router(educador.router)
app.include_router(api.router)


@app.exception_handler(RedireccionAIngreso)
def _sin_sesion(request: Request, exc: RedireccionAIngreso):
    return RedirectResponse(exc.destino, status_code=303)


@app.exception_handler(403)
def _sin_permiso(request: Request, exc):
    return plantillas.TemplateResponse(
        request,
        "error.html",
        {"titulo": "No tenés acceso a esta página", "detalle": getattr(exc, "detail", "")},
        status_code=403,
    )


@app.exception_handler(404)
def _no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api"):
        raise exc
    return plantillas.TemplateResponse(
        request,
        "error.html",
        {"titulo": "No encontramos eso", "detalle": getattr(exc, "detail", "")},
        status_code=404,
    )
