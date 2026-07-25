"""Prueba de punta a punta del circuito completo.

    python scripts/probar_circuito.py

Recorre lo que de verdad importa: un joven entra, ve el reto del día, entrega,
el validador decide, el educador confirma y los puntos aparecen en la patrulla.
Corre sobre una base de datos temporal, así que no toca scout.db.

Requiere httpx (ver requirements-dev.txt).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_temporal = Path(tempfile.mkdtemp(prefix="scout-prueba-"))
os.environ["BASE_DATOS_URL"] = f"sqlite:///{_temporal / 'prueba.db'}"
os.environ["DIR_SUBIDAS"] = str(_temporal / "uploads")
os.environ["VALIDADOR"] = "simulado"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.db import Base, SesionLocal, motor  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    DESAFIO_ESPECIALIDAD,
    DESAFIO_REQUERIDO,
    AvanceDesafio,
    Desafio,
    Patrulla,
    Usuario,
)
from app.servicios import medios  # noqa: E402
from scripts.inicializar_db import cargar_cartas, cargar_demo  # noqa: E402

SUBIDAS = _temporal / "uploads"

fallos: list[str] = []


def check(nombre: str, condicion: bool, extra: object = "") -> None:
    print(f"{'ok   ' if condicion else 'FALLA'} {nombre}{'  → ' + str(extra) if extra != '' else ''}")
    if not condicion:
        fallos.append(nombre)


def _rechaza(url: str) -> bool:
    """True si leer_video se niega a aceptar ese enlace."""
    try:
        medios.leer_video(url)
    except medios.MedioInvalido:
        return True
    return False


def preparar() -> None:
    Base.metadata.create_all(motor)
    with SesionLocal() as sesion:
        cargar_cartas(sesion)
        cargar_demo(sesion)


def main() -> int:
    preparar()

    joven = TestClient(app, follow_redirects=True)
    edu = TestClient(app, follow_redirects=True)

    # --- acceso --------------------------------------------------------------
    check("sin sesión redirige a /ingresar", joven.get("/").url.path == "/ingresar")
    check(
        "contraseña incorrecta rechazada",
        "incorrectos" in joven.post("/ingresar", data={"usuario": "ana", "clave": "x"}).text,
    )
    r = joven.post("/ingresar", data={"usuario": "ana", "clave": "scout1907"})
    check("un joven entra a /hoy", r.url.path == "/hoy", r.url.path)

    # --- reto del día automático --------------------------------------------
    datos = joven.get("/api/hoy").json()
    check("hay un reto propuesto para hoy", len(datos["retos"]) == 1, datos["fecha"])
    asignacion = datos["retos"][0]["asignacion_id"]

    check("la página del reto abre", joven.get(f"/reto/{asignacion}").status_code == 200)

    with SesionLocal() as s:
        sin_clasificar = s.scalar(
            select(func.count(Desafio.id)).where(Desafio.tipo.is_(None))
        )
        check("las 53 cartas están clasificadas", sin_clasificar == 0, sin_clasificar)
        # El reto automático nunca puede ser una especialidad o un rol de patrulla:
        # son recorridos de meses, no algo que se entregue hoy. Se compara contra
        # el total y no contra un número fijo: la clasificación se sigue afinando.
        total = s.scalar(select(func.count(Desafio.id)))
        especialidades = s.scalar(
            select(func.count(Desafio.id)).where(Desafio.tipo == DESAFIO_ESPECIALIDAD)
        )
        elegibles = s.scalar(
            select(func.count(Desafio.id)).where(Desafio.tipo != DESAFIO_ESPECIALIDAD)
        )
        check(
            "el pozo del reto diario excluye especialidades",
            especialidades > 0 and elegibles == total - especialidades,
            f"{elegibles} de {total}",
        )

    # --- validación automática ----------------------------------------------
    r = joven.post(f"/reto/{asignacion}", data={"texto": "listo"})
    check("evidencia floja queda para el educador", "Esperando al educador" in r.text)
    check(
        "el estado se ve en la API",
        joven.get("/api/hoy").json()["retos"][0]["estado_entrega"] == "requiere_revision",
    )

    relato = (
        "Hice el nudo margarita para acortar una soga sin cortarla. Lo usamos en el "
        "portal de la patrulla y aguantó todo el día."
    )
    check("evidencia completa se aprueba sola", "Validado" in joven.post(
        f"/reto/{asignacion}", data={"texto": relato}
    ).text)

    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("los puntos van a la patrulla", halcones["puntos"] == 10, halcones["puntos"])
    check("la racha arranca en 1", halcones["racha"] == 1)

    # --- progresión personal -------------------------------------------------
    check("se listan las 53 cartas", joven.get("/mis-cartas").text.count('id="carta-') == 53)
    check("elegir una carta la marca", "Sacar de mi elección" in joven.post("/mis-cartas/1").text)

    # Elegir la carta 47 no puede devolverte al principio de una lista de 53.
    r = joven.post("/mis-cartas/7", follow_redirects=False)
    check(
        "elegir vuelve al ancla de la carta",
        r.headers["location"] == "/mis-cartas#carta-7",
        r.headers["location"],
    )

    with SesionLocal() as s:
        ana_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "ana"))
        requerido_id = s.scalar(
            select(Desafio.id)
            .where(Desafio.competencia_id == 1, Desafio.tipo == DESAFIO_REQUERIDO)
            .order_by(Desafio.orden)
        )
        ajeno_id = s.scalar(select(Desafio.id).where(Desafio.competencia_id == 2))
        de_carta_3 = s.scalar(select(Desafio.id).where(Desafio.competencia_id == 3))

    check("las elegidas se separan del catálogo", "Trabajar en esta carta" in joven.get("/mis-cartas").text)
    check("la carta elegida tiene página de trabajo", "Cómo me fue" in joven.get("/mis-cartas/1").text)
    check("una carta no elegida ofrece elegirla", "Elegir esta carta" in joven.get("/mis-cartas/3").text)

    comentario = "Lo hicimos en la reunión del sábado con toda la patrulla."
    r = joven.post(
        f"/mis-cartas/1/desafios/{requerido_id}",
        data={"hecho": "true", "comentario": comentario},
    )
    check("marcar un desafío guarda el comentario", comentario in r.text)

    with SesionLocal() as s:
        marca = s.scalar(select(AvanceDesafio).where(AvanceDesafio.desafio_id == requerido_id))
        check("queda marcado como hecho", marca is not None and marca.hecho)

    check(
        "un desafío de otra carta da 404",
        joven.post(f"/mis-cartas/1/desafios/{ajeno_id}", data={"hecho": "true"}).status_code == 404,
    )
    check(
        "no se marca una carta que no elegí",
        joven.post(f"/mis-cartas/3/desafios/{de_carta_3}", data={"hecho": "true"}).status_code == 400,
    )

    check(
        "la bitácora guarda",
        "Primer nudo"
        in joven.post("/bitacora", data={"titulo": "Primer nudo", "texto": "Me costó."}).text,
    )

    # --- quién ve la progresión ----------------------------------------------
    companiera = TestClient(app, follow_redirects=True)
    companiera.post("/ingresar", data={"usuario": "bruno", "clave": "scout1907"})
    check("la patrulla ve el recorrido", comentario in companiera.get(f"/cartas-de/{ana_id}").text)
    check("mi patrulla lista a sus integrantes", "Ana" in companiera.get("/mi-patrulla").text)

    de_otra = TestClient(app, follow_redirects=True)
    de_otra.post("/ingresar", data={"usuario": "cami", "clave": "scout1907"})
    check(
        "otra patrulla no ve el recorrido",
        de_otra.get(f"/cartas-de/{ana_id}").status_code == 404,
    )
    with SesionLocal() as s:
        cami_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "cami"))
    check(
        "sin cartas elegidas la página igual abre",
        "Todavía no elegiste" in de_otra.get(f"/cartas-de/{cami_id}").text,
    )

    # --- permisos ------------------------------------------------------------
    check("un joven no entra al panel", joven.get("/panel").status_code == 403)
    check("un reto ajeno da 404", joven.get("/reto/99999").status_code == 404)

    # --- educador ------------------------------------------------------------
    r = edu.post("/ingresar", data={"usuario": "educador", "clave": "scout1907"})
    check("un educador entra al panel", r.url.path == "/panel", r.url.path)

    r = edu.post(
        "/retos",
        data={
            "titulo": "Nudo margarita",
            "consigna": "Hacelo y explicá para qué sirve.",
            "puntaje": "15",
            "pide_texto": "true",
        },
    )
    check("el educador crea un reto propio", "Nudo margarita" in r.text)
    reto_id = int(re.search(r"/retos/(\d+)/archivar", r.text).group(1))

    r = edu.post(
        "/asignar",
        data={"reto_id": str(reto_id), "fecha": date.today().isoformat(), "alcance": "unidad"},
    )
    check("el educador lo asigna a la Unidad", "Nudo margarita" in r.text)

    retos_hoy = joven.get("/api/hoy").json()["retos"]
    check("el joven ve el reto nuevo", len(retos_hoy) == 2, len(retos_hoy))
    nuevo = next(x for x in retos_hoy if x["titulo"] == "Nudo margarita")
    joven.post(f"/reto/{nuevo['asignacion_id']}", data={"texto": "corto"})

    r = edu.get("/validaciones")
    check("la entrega aparece en la cola", "Nudo margarita" in r.text)
    entrega_id = int(re.search(r'action="/validaciones/(\d+)"', r.text).group(1))

    edu.post(
        f"/validaciones/{entrega_id}",
        data={"decision": "aprobar", "devolucion": "Muy bien explicado."},
    )
    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("la validación manual suma sus puntos", halcones["puntos"] == 25, halcones["puntos"])

    check("la API filtra por área", len(edu.get("/api/competencias?area=ambiente").json()) == 9)

    r = edu.get(f"/cartas-de/{ana_id}")
    check("el educador ve las cartas elegidas y los comentarios", comentario in r.text)
    check("el listado de jóvenes enlaza la progresión", f"/cartas-de/{ana_id}" in edu.get("/jovenes").text)

    # --- Libro de Oro ---------------------------------------------------------
    check("reconoce youtu.be", medios.leer_video("https://youtu.be/dQw4w9WgXcQ").identificador == "dQw4w9WgXcQ")
    check(
        "reconoce youtube.com con parámetros",
        medios.leer_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s").identificador
        == "dQw4w9WgXcQ",
    )
    check("reconoce shorts", medios.leer_video("https://youtube.com/shorts/dQw4w9WgXcQ").servicio == "youtube")
    check("reconoce vimeo", medios.leer_video("https://vimeo.com/123456789").servicio == "vimeo")
    check("sin enlace no hay video", medios.leer_video("   ") is None)
    check("rechaza un enlace que no es de video", _rechaza("javascript:alert(document.cookie)"))
    check("rechaza un host cualquiera", _rechaza("https://malo.example/youtu.be/dQw4w9WgXcQ.mp4"))

    with SesionLocal() as s:
        halcones_id = s.scalar(select(Patrulla.id).where(Patrulla.nombre == "Halcones"))

    r = joven.get("/libro-de-oro", follow_redirects=False)
    check(
        "el atajo lleva al libro de tu patrulla",
        r.headers["location"] == f"/libro-de-oro/{halcones_id}",
        r.headers["location"],
    )

    # Ruido, no un color plano: un JPEG de color plano pesa nada y el chequeo
    # de compresión no probaría nada.
    grande = BytesIO()
    Image.frombytes("RGB", (2400, 1800), os.urandom(2400 * 1800 * 3)).save(
        grande, "JPEG", quality=95
    )
    original = grande.getvalue()

    # Marcador propio: el formulario trae un placeholder de ejemplo y buscar
    # "Campamento de invierno" daría positivo aunque la página no se haya creado.
    recuerdo = "Se voló la carpa y terminamos los cinco en la de Bruno."
    r = joven.post(
        f"/libro-de-oro/{halcones_id}",
        data={
            "titulo": "Campamento de invierno",
            "texto": recuerdo,
            "fecha": "2026-07-18",
            "video": "https://youtu.be/dQw4w9WgXcQ",
        },
        files={"foto": ("campamento.jpg", original, "image/jpeg")},
    )
    check("la página entra al libro", recuerdo in r.text)
    check("el video se embebe desde el dominio sin cookies",
          "youtube-nocookie.com/embed/dQw4w9WgXcQ" in r.text)

    guardadas = sorted(SUBIDAS.glob("*.jpg"))
    check("la foto se guardó una sola vez", len(guardadas) == 1, len(guardadas))
    with Image.open(guardadas[0]) as imagen:
        lado, peso = max(imagen.size), guardadas[0].stat().st_size
    check("la foto se achica al guardarse", lado <= 1600, f"lado mayor {lado}px")
    check(
        "la foto pesa una fracción del original",
        peso < len(original) // 3,
        f"{len(original) // 1024} kB → {peso // 1024} kB",
    )

    nombre_foto = guardadas[0].name
    anonimo = TestClient(app, follow_redirects=False)
    check("las fotos piden sesión", anonimo.get(f"/fotos/{nombre_foto}").status_code == 303)
    check("con sesión la foto se sirve", joven.get(f"/fotos/{nombre_foto}").status_code == 200)

    check("la patrulla lee el libro",
          recuerdo in companiera.get(f"/libro-de-oro/{halcones_id}").text)
    check("otra patrulla no entra al libro",
          de_otra.get(f"/libro-de-oro/{halcones_id}").status_code == 404)
    check("el educador entra al libro",
          recuerdo in edu.get(f"/libro-de-oro/{halcones_id}").text)

    entrada_id = int(re.search(r"/libro-de-oro/\d+/(\d+)/borrar", r.text).group(1))
    check(
        "nadie borra la página de otro",
        companiera.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/borrar").status_code == 403,
    )
    edu.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/borrar")
    check(
        "el educador puede borrar",
        recuerdo not in joven.get(f"/libro-de-oro/{halcones_id}").text,
    )
    check("borrar la página borra su foto", not list(SUBIDAS.glob("*.jpg")))

    print()
    if fallos:
        print(f"{len(fallos)} verificaciones fallaron: {fallos}")
        return 1
    print("Circuito completo funcionando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
