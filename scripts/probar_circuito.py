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
from datetime import date, timedelta
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
from sqlalchemy import func, select, update  # noqa: E402

from app.db import Base, SesionLocal, motor  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    CLASE_DESCUBIERTA,
    DESAFIO_ESPECIALIDAD,
    DESAFIO_REQUERIDO,
    Actividad,
    Area,
    Asignacion,
    AvanceDesafio,
    Aviso,
    CambioEtapa,
    Cargo,
    CompetenciaElegida,
    Desafio,
    EntradaBitacora,
    Entrega,
    Especialidad,

    Idea,
    ParticipacionActividad,
    Patrulla,
    PausaSinTelefono,
    PeriodoCargo,
    ROL_JOVEN,
    Reto,
    Usuario,
)
from app import seguridad  # noqa: E402
from app.servicios import cuentas, cumpleanos, medios, retos  # noqa: E402
from app.servicios.progresion import MIN_CARTAS  # noqa: E402
from scripts.inicializar_db import asegurar_cargos, cargar_cartas, cargar_demo  # noqa: E402

SUBIDAS = _temporal / "uploads"

fallos: list[str] = []


def check(nombre: str, condicion: bool, extra: object = "") -> None:
    print(f"{'ok   ' if condicion else 'FALLA'} {nombre}{'  → ' + str(extra) if extra != '' else ''}")
    if not condicion:
        fallos.append(nombre)


def provisoria_de(html: str) -> str:
    """La contraseña que la pantalla muestra una sola vez tras un alta o blanqueo.

    Se lee de la página y no de la base a propósito: es el único lugar donde
    esa contraseña existe en claro, así que si el cartel se rompe el test tiene
    que enterarse.
    """
    hallado = re.search(r"contraseña <strong[^>]*>([^<]+)</strong>", html)
    return hallado.group(1).strip() if hallado else ""


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
        asegurar_cargos(sesion)


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

    # El freno a la fuerza bruta. Se prueba contra un usuario de descarte para no
    # dejar bloqueada ninguna cuenta que el resto del recorrido necesita, y se
    # limpia después: el contador vive en memoria del proceso y este proceso
    # sigue corriendo el resto de las pruebas.
    fuerza = TestClient(app, follow_redirects=True)
    for _ in range(5):
        fuerza.post("/ingresar", data={"usuario": "ana", "clave": "probando"})
    frenado = fuerza.post("/ingresar", data={"usuario": "ana", "clave": "probando"}).text
    check("cinco intentos fallidos y la cuenta se frena", "Demasiados intentos" in frenado)
    check("el mensaje dice a quién pedirle ayuda", "blanquee" in frenado)
    check(
        "y el freno no cede ni con la contraseña correcta",
        "Demasiados intentos"
        in fuerza.post("/ingresar", data={"usuario": "ana", "clave": "scout1907"}).text,
    )
    seguridad.olvidar_fallos("ana", "testclient")

    r = joven.post("/ingresar", data={"usuario": "ana", "clave": "scout1907"})
    check("un joven entra a /hoy, con el freno ya limpio", r.url.path == "/hoy", r.url.path)

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
    check("evidencia floja queda para el educador", "mirando tu educador" in r.text)
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

    # --- la capa de JavaScript -----------------------------------------------
    # Todo esto tiene que seguir andando sin JavaScript, así que se prueban las
    # dos formas: con la cabecera que manda app.js y sin ella.

    check("app.js se sirve", joven.get("/estaticos/app.js").status_code == 200)

    catalogo = joven.get("/mis-cartas").text
    check("las páginas lo cargan", "/estaticos/app.js" in catalogo)
    # El JavaScript se engancha por estas marcas: si una plantilla las pierde,
    # la página sigue andando pero en silencio deja de ser fluida.
    check(
        "el catálogo marca sus formularios",
        catalogo.count("data-elegir=") == catalogo.count('id="carta-'),
        catalogo.count("data-elegir="),
    )
    check("y tiene dónde pegar la elección", 'id="eleccion"' in catalogo)
    check("el buscador del catálogo está en la página", 'id="filtros-cartas"' in catalogo)
    check(
        "cada carta dice de qué área es, para poder filtrarla",
        catalogo.count("data-area=") == catalogo.count('id="carta-'),
    )
    check("y cada área es un bloque que se puede esconder entero",
          catalogo.count("data-bloque-area=") == 4)
    check("la sesión sabe de quién es, para la cola de reintentos",
          "data-usuario=" in catalogo and 'id="pendientes"' in catalogo)
    check(
        "sin JavaScript el «Trabajar →» de una carta no elegida queda escondido",
        "[hidden] { display: none !important; }" in joven.get("/estaticos/estilos.css").text,
    )
    trabajo = joven.get("/mis-cartas/1").text
    check("la página de una carta se autoguarda", "data-autoguardar" in trabajo)
    check("y avisa cómo va cada guardado", 'class="estado-guardado"' in trabajo)

    json_ = {"X-Sin-Recarga": "json"}

    r = joven.post("/mis-cartas/20", headers=json_)
    check("elegir contesta en JSON", r.headers["content-type"].startswith("application/json"))
    datos = r.json()
    check("y dice que quedó elegida", datos["elegida"] is True)
    check(
        "con el pedazo de página ya armado",
        "Trabajar en esta carta" in datos["fragmentos"]["#eleccion"],
    )
    # El pedazo se pega adentro de la página que ya tiene las 53 del catálogo:
    # si trajera esos id, quedarían repetidos en el documento.
    check(
        "sin repetir los id del catálogo",
        'id="carta-' not in datos["fragmentos"]["#eleccion"],
    )
    with SesionLocal() as s:
        areas_totales = s.scalar(select(func.count(Area.id)))
    contadores_area = [c for c in datos["cuentas"] if c.startswith("area-")]
    check(
        "los contadores de las cuatro áreas viajan siempre",
        len(contadores_area) == areas_totales,
        f"{len(contadores_area)} de {areas_totales}",
    )

    with SesionLocal() as s:
        requerido_20 = s.scalar(
            select(Desafio.id)
            .where(Desafio.competencia_id == 20, Desafio.tipo == DESAFIO_REQUERIDO)
            .order_by(Desafio.orden)
        )
    r = joven.post(
        f"/mis-cartas/20/desafios/{requerido_20}",
        data={"hecho": "true", "comentario": "Guardado solo, sin apretar nada."},
        headers=json_,
    )
    check("marcar un desafío contesta en JSON", r.json()["hecho"] is True)
    check(
        "y devuelve el resumen de la carta al día",
        "Cómo venís" in r.json()["fragmentos"]["#resumen-carta"],
    )
    with SesionLocal() as s:
        guardado = s.scalar(
            select(AvanceDesafio).where(AvanceDesafio.desafio_id == requerido_20)
        )
        check("el comentario quedó guardado igual que sin JavaScript",
              guardado is not None and guardado.comentario.startswith("Guardado solo"))

    check("sacarla vuelve a decir que no está", joven.post("/mis-cartas/20", headers=json_).json()["elegida"] is False)

    # Sin la cabecera nada cambia: sigue siendo un formulario con su redirección.
    r = joven.post("/mis-cartas/20", follow_redirects=False)
    check(
        "sin la cabecera sigue redirigiendo como siempre",
        r.status_code == 303 and r.headers["location"] == "/mis-cartas#carta-20",
        r.headers.get("location"),
    )
    # Elegirla desde su propia página te deja ahí, no te manda al catálogo.
    r = joven.post("/mis-cartas/20", data={"quedarse": "1"}, follow_redirects=False)
    check(
        "elegirla desde su página te deja en su página",
        r.headers["location"] == "/mis-cartas/20",
        r.headers["location"],
    )
    joven.post("/mis-cartas/20")  # queda como estaba

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

    # Lo de la cuenta vive en el menú de arriba a la derecha y **fuera** de
    # <nav>, que en el celular se esconde entero. Estando afuera se ve siempre,
    # que es lo que antes no pasaba con «Equipo» y con «Salir».
    cabecera = r.text.split("</header>")[0]
    menu = cabecera[cabecera.index('class="menu-usuario"'):]
    check("el menú de la cuenta no queda adentro de la navegación", "</nav>" not in menu)
    check(
        "y desde ahí se llega a la contraseña, al equipo y a salir",
        all(destino in menu for destino in ("/clave", "/educadores", "/salir")),
    )
    check("la barra del celular lleva solo las secciones", "/educadores" not in r.text.split("barra-movil")[1])

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

    # --- corregir un reto ya escrito ------------------------------------------
    # Un reto se escribe una vez y se agenda muchas, así que la consigna que
    # resultó confusa se arregla en su lugar. Antes el único camino era
    # archivarlo y escribir otro casi igual.
    pagina = edu.get("/retos").text
    check("la tarjeta ofrece corregir el reto", f'action="/retos/{reto_id}"' in pagina)
    check("y avisa que todavía no lo agendó nadie", "Todavía no lo agendaste" in pagina)
    check("el formulario llega con lo escrito adentro", 'value="Nudo margarita"' in pagina)

    with SesionLocal() as s:
        de_carta = s.scalar(select(Desafio).order_by(Desafio.id))
        desafio_id, area_de_la_carta = de_carta.id, de_carta.competencia.area_id

    r = edu.post(
        f"/retos/{reto_id}",
        data={
            "titulo": "Nudo margarita",
            "consigna": "Hacelo, explicá para qué sirve y contá dónde lo usarías.",
            "desafio_id": str(desafio_id),
            "puntaje": "15",
            "pide_texto": "true",
        },
    )
    check("la consigna corregida se ve en la lista", "dónde lo usarías" in r.text)
    with SesionLocal() as s:
        corregido = s.get(Reto, reto_id)
        check("colgarlo de una carta lo pasa a tipo carta", corregido.tipo == "carta")
        check("y el área la manda la carta", corregido.area_id == area_de_la_carta)

    check(
        "un título en blanco no pisa nada",
        edu.post(f"/retos/{reto_id}", data={"titulo": "   ", "consigna": "algo"}).status_code == 400,
    )
    check(
        "un reto de otra Unidad no existe",
        edu.post("/retos/999999", data={"titulo": "a", "consigna": "b"}).status_code == 404,
    )
    check(
        "y un joven no corrige retos",
        joven.post(f"/retos/{reto_id}", data={"titulo": "a", "consigna": "b"}).status_code == 403,
    )

    # Soltar la carta lo devuelve a reto propio, que es como sigue el recorrido.
    edu.post(
        f"/retos/{reto_id}",
        data={
            "titulo": "Nudo margarita",
            "consigna": "Hacelo y explicá para qué sirve.",
            "puntaje": "15",
            "pide_texto": "true",
        },
    )
    with SesionLocal() as s:
        corregido = s.get(Reto, reto_id)
        check(
            "soltar la carta lo devuelve a propio y sin área",
            corregido.tipo == "personalizado" and corregido.area_id is None,
        )

    # --- archivar y desarchivar -----------------------------------------------
    # Archivar es un botón que no pregunta nada y está a un dedo del de al lado.
    # El reto archivado no se fue: deja de estar para agendar y vuelve entero.
    r = edu.post(f"/retos/{reto_id}/archivar")
    check("archivar lo baja a «Archivados»", "Archivados" in r.text)
    check("y deja de estar para agendar", "Nudo margarita" not in edu.get("/asignar").text)
    check(
        "un joven no desarchiva retos",
        joven.post(f"/retos/{reto_id}/desarchivar").status_code == 403,
    )
    check(
        "y un reto de otra Unidad tampoco existe para desarchivar",
        edu.post("/retos/999999/desarchivar").status_code == 404,
    )

    r = edu.post(f"/retos/{reto_id}/desarchivar")
    check("desarchivarlo lo devuelve a la lista", f'action="/retos/{reto_id}/archivar"' in r.text)
    check("vuelve a estar para agendar", "Nudo margarita" in edu.get("/asignar").text)
    check(
        "desarchivar uno que ya está en la lista no hace nada",
        edu.post(f"/retos/{reto_id}/desarchivar").status_code == 400,
    )

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
    check(
        "la cola se puede recorrer con el teclado",
        'data-atajos="validaciones"' in r.text and "data-entrega=" in r.text,
    )
    check("el tablero se pone al día solo", "data-refrescar=" in edu.get("/tablero").text)
    entrega_id = int(re.search(r'action="/validaciones/(\d+)"', r.text).group(1))

    edu.post(
        f"/validaciones/{entrega_id}",
        data={"decision": "aprobar", "devolucion": "Muy bien explicado."},
    )
    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("la validación manual suma sus puntos", halcones["puntos"] == 25, halcones["puntos"])

    # --- decirle algo a quien hizo bien el reto -------------------------------
    #
    # Casi todo se aprueba solo, así que sobre una entrega ya validada las
    # únicas puertas que había eran las dos malas noticias. Felicitar escribe y
    # no toca nada más: ni el estado, ni los puntos, ni quién la validó.
    with SesionLocal() as s:
        sola_id = s.scalar(select(Entrega.id).where(Entrega.asignacion_id == asignacion))

    check(
        "lo que contesta la aplicación no se firma como si fuera una persona",
        "Respuesta automática" in joven.get("/mis-retos").text,
    )

    pagina = edu.get("/validaciones").text
    check("una entrega ya validada se puede felicitar", 'value="felicitar"' in pagina)
    check("la devolución que ya está escrita dice quién la escribió", "La escribió" in pagina)
    check("y el atajo de teclado también está anunciado", "<kbd>F</kbd>" in pagina)

    felicitacion = "Me encantó cómo contaste para qué sirve el nudo. Seguí por ahí."
    edu.post(
        f"/validaciones/{sola_id}",
        data={"decision": "felicitar", "devolucion": felicitacion},
    )
    with SesionLocal() as s:
        felicitada = s.get(Entrega, sola_id)
        check("la felicitación queda guardada", felicitada.devolucion == felicitacion)
        check(
            "y deja la entrega como estaba",
            felicitada.estado == "aprobada" and felicitada.puntaje_otorgado == 10,
            f"{felicitada.estado} / {felicitada.puntaje_otorgado} pts",
        )
        check("firmada por quien la escribió", felicitada.devolucion_por_id is not None)
        # Lo que se aprobó solo se aprobó solo: un comentario no reescribe eso.
        check("sin hacerse pasar por la validación", felicitada.validador == "simulado",
              felicitada.validador)

    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("felicitar no mueve el tablero", halcones["puntos"] == 25, halcones["puntos"])

    mis_retos = joven.get("/mis-retos").text
    check("el joven lee la felicitación", felicitacion in mis_retos)
    check("y ve de quién es", "Te lo escribió" in mis_retos)
    su_reto = joven.get(f"/reto/{asignacion}").text
    check("también en la página del reto, adentro del «¡Validado!»",
          felicitacion in su_reto and "Te lo escribió" in su_reto)
    check(
        "felicitar sin escribir nada no llega a ninguna parte",
        edu.post(
            f"/validaciones/{sola_id}", data={"decision": "felicitar", "devolucion": "   "}
        ).status_code == 400,
    )
    check("un joven no felicita entregas",
          joven.post(f"/validaciones/{sola_id}",
                     data={"decision": "felicitar", "devolucion": "va"}).status_code == 403)

    # Corregir un reto que ya está en juego. La pantalla tiene que decir de cuál
    # se trata, y bajarle el puntaje no puede reescribir un tablero: los puntos
    # se copian a la entrega en el momento de validarla.
    pagina = edu.get("/retos").text
    check("la lista dice cuántas veces se agendó cada reto", "Ya lo agendaste 1 vez" in pagina)
    check("y cuántas entregas cuelgan de él", "1 entrega colgando de él" in pagina)

    edu.post(f"/retos/{reto_id}", data={"titulo": "Nudo margarita", "puntaje": "1",
                                        "consigna": "Hacelo y explicá para qué sirve.",
                                        "pide_texto": "true"})
    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("bajarle el puntaje no toca los puntos ya dados", halcones["puntos"] == 25,
          halcones["puntos"])
    edu.post(f"/retos/{reto_id}", data={"titulo": "Nudo margarita", "puntaje": "15",
                                        "consigna": "Hacelo y explicá para qué sirve.",
                                        "pide_texto": "true"})

    check("la API filtra por área", len(edu.get("/api/competencias?area=ambiente").json()) == 9)

    r = edu.get(f"/cartas-de/{ana_id}")
    check("el educador ve las cartas elegidas y los comentarios", comentario in r.text)
    check("el listado de jóvenes enlaza la progresión", f"/progresion/{ana_id}" in edu.get("/jovenes").text)
    # Mover a alguien de patrulla no recarga la lista entera de la Unidad.
    with SesionLocal() as s:
        patrulla_de_ana = s.scalar(select(Usuario.patrulla_id).where(Usuario.id == ana_id))
    r = edu.post(
        f"/jovenes/{ana_id}",
        data={"patrulla_id": str(patrulla_de_ana)},
        headers={"X-Sin-Recarga": "json"},
    )
    check("cambiar de patrulla contesta en JSON", r.json() == {"ok": True}, r.text[:60])

    # --- cuentas y contraseñas -----------------------------------------------
    # Toda cuenta nace con su nombre de usuario como contraseña, y con esa puesta
    # lo único que abre es /clave. Es la mitad del alta que le toca a la persona.
    with SesionLocal() as s:
        una_patrulla = s.scalar(select(Patrulla.id).order_by(Patrulla.id))
    r = edu.post(
        "/jovenes",
        data={
            "nombre": "Nadia",
            "usuario_nuevo": "nadialopez",
            "patrulla_id": str(una_patrulla),
            "etapa": "pistas",
        },
    )
    check(
        "el alta de un joven no pide contraseña",
        "Nadia" in r.text and 'name="clave"' not in r.text,
    )
    check(
        "un usuario con espacios se rechaza",
        edu.post(
            "/jovenes", data={"nombre": "Otra", "usuario_nuevo": "na dia", "etapa": "pistas"}
        ).status_code == 400,
    )
    check(
        "un usuario repetido se rechaza",
        edu.post(
            "/jovenes", data={"nombre": "Otra", "usuario_nuevo": "nadialopez", "etapa": "pistas"}
        ).status_code == 400,
    )

    # La provisoria se sortea y la pantalla la muestra una sola vez: el test la
    # lee de ahí, que es exactamente lo que hace el educador.
    clave_nadia = provisoria_de(r.text)
    check("el alta muestra una provisoria sorteada", bool(clave_nadia), clave_nadia)
    check("y no es el nombre de usuario", clave_nadia != "nadialopez")
    check(
        "leerla la consume: al recargar ya no está",
        provisoria_de(edu.get("/jovenes").text) == "",
    )

    nadia = TestClient(app, follow_redirects=True)
    check(
        "con el usuario como contraseña ya no se entra",
        "incorrectos" in nadia.post("/ingresar", data={"usuario": "nadialopez", "clave": "nadialopez"}).text,
    )
    r = nadia.post("/ingresar", data={"usuario": "nadialopez", "clave": clave_nadia})
    check("se entra con la provisoria que se mostró", r.url.path == "/clave", r.url.path)
    check("con la contraseña del alta no hay navegación", "/mis-cartas" not in r.text)
    check("y ninguna otra página abre", nadia.get("/hoy").url.path == "/clave")
    check("tampoco la API", nadia.get("/api/yo").url.path == "/clave")

    def cambiar(actual: str, nueva: str, repetida: str | None = None):
        return nadia.post(
            "/clave",
            data={"actual": actual, "nueva": nueva, "repetida": repetida or nueva},
        )

    # El usuario tiene diez letras a propósito: con uno de cinco esta regla no
    # se alcanza nunca, porque antes salta la del largo mínimo. La versión vieja
    # de este check pasaba por el texto de ayuda de la plantilla, no por el error.
    check(
        "la nueva no puede ser el propio usuario",
        "no puede ser tu nombre de usuario" in cambiar(clave_nadia, "nadialopez").text,
    )
    check("ni más corta que el mínimo", "al menos" in cambiar(clave_nadia, "abc").text)
    check("las dos escrituras tienen que coincidir", "no coinciden" in cambiar(clave_nadia, "brujula24", "brujula25").text)
    check("y hay que saber la actual", "actual no es esa" in cambiar("puse-cualquiera", "brujula24").text)

    check("con todo bien, la contraseña se cambia", "Contraseña cambiada" in cambiar(clave_nadia, "brujula24").text)
    check("recién ahí abre el resto de la aplicación", nadia.get("/hoy").url.path == "/hoy")
    sin_cambiar = TestClient(app, follow_redirects=True)
    check(
        "la provisoria ya no entra después de cambiarla",
        "incorrectos" in sin_cambiar.post("/ingresar", data={"usuario": "nadialopez", "clave": clave_nadia}).text,
    )

    with SesionLocal() as s:
        nadia_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "nadialopez"))
    check("un joven no blanquea a nadie", joven.post(f"/jovenes/{nadia_id}/blanquear").status_code == 403)

    # Perder la provisoria antes de que la persona entre tiene que tener arreglo.
    # Es el único camino de vuelta: no se guarda en ningún lado, se mostró una vez.
    # La pantalla escondía justo acá el botón de blanquear, heredado de cuando la
    # provisoria era el nombre de usuario y no hacía falta.
    r = edu.post("/jovenes", data={"nombre": "Perdida Provisoria",
                                   "usuario_nuevo": "perdida", "etapa": "pistas"})
    with SesionLocal() as s:
        perdida_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "perdida"))
        check("la cuenta nueva arranca sin haber entrado",
              s.get(Usuario, perdida_id).debe_cambiar_clave)
    lista = edu.get("/jovenes").text
    check("una cuenta que nunca entró ofrece generar otra provisoria",
          "Mostrarme otra provisoria" in lista)
    check("y ya no dice que entra con su nombre de usuario",
          "elige su contraseña" not in lista and "entra con «perdida»" not in lista)

    otra = provisoria_de(edu.post(f"/jovenes/{perdida_id}/blanquear").text)
    check("blanquear una cuenta que nunca entró da una provisoria nueva",
          bool(otra) and otra != provisoria_de(r.text), otra)
    recuperada = TestClient(app, follow_redirects=True)
    check("y con esa se entra",
          recuperada.post("/ingresar", data={"usuario": "perdida", "clave": otra}).url.path == "/clave")
    check("mientras que la primera ya no sirve",
          "incorrectos" in TestClient(app, follow_redirects=True).post(
              "/ingresar", data={"usuario": "perdida", "clave": provisoria_de(r.text)}).text)
    blanqueada = provisoria_de(edu.post(f"/jovenes/{nadia_id}/blanquear").text)
    check("el blanqueo muestra una provisoria nueva", blanqueada not in ("", clave_nadia), blanqueada)
    otra_vez = TestClient(app, follow_redirects=True)
    check(
        "blanquear la devuelve a la pantalla de elegir contraseña",
        otra_vez.post("/ingresar", data={"usuario": "nadialopez", "clave": blanqueada}).url.path == "/clave",
    )

    # --- equipo de educadores ------------------------------------------------
    check("un joven no entra al equipo", joven.get("/educadores").status_code == 403)
    r = edu.post("/educadores", data={"nombre": "Sofía Ruiz", "usuario_nuevo": "sofia"})
    check("un educador da de alta a otro educador", "Sofía Ruiz" in r.text)
    # El POST sigue el redirect, así que esta respuesta ya es la página que
    # muestra la provisoria. Hay que leerla acá: el próximo GET no la tiene.
    clave_sofia = provisoria_de(r.text)
    check(
        "el alta repetida se rechaza",
        edu.post("/educadores", data={"nombre": "Otra", "usuario_nuevo": "sofia"}).status_code == 400,
    )

    with SesionLocal() as s:
        sofia_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "sofia"))
        educador_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "educador"))
    check("nadie se blanquea a sí mismo", edu.post(f"/educadores/{educador_id}/blanquear").status_code == 400)
    check(
        "un educador no se blanquea por la puerta de los jóvenes",
        edu.post(f"/jovenes/{sofia_id}/blanquear").status_code == 404,
    )

    check("el alta de un educador también muestra su provisoria", bool(clave_sofia), clave_sofia)

    sofia = TestClient(app, follow_redirects=True)
    r = sofia.post("/ingresar", data={"usuario": "sofia", "clave": clave_sofia})
    check("el educador nuevo también elige su contraseña", r.url.path == "/clave", r.url.path)
    check("y el panel no abre hasta entonces", sofia.get("/panel").url.path == "/clave")
    sofia.post("/clave", data={"actual": clave_sofia, "nueva": "morse-1907", "repetida": "morse-1907"})
    check("después entra al panel como cualquier educador", sofia.get("/panel").status_code == 200)

    de_nuevo = provisoria_de(edu.post(f"/educadores/{sofia_id}/blanquear").text)
    de_cero = TestClient(app, follow_redirects=True)
    check(
        "un educador blanquea a otro del equipo",
        de_cero.post("/ingresar", data={"usuario": "sofia", "clave": de_nuevo}).url.path == "/clave",
    )

    # --- sacar a alguien del equipo ------------------------------------------
    #
    # Dos caminos distintos según lo que la cuenta haya hecho, y la aplicación
    # elige sola mirando la base. Ver `servicios/cuentas.py`.

    # a) Una cuenta que no llegó a firmar nada se borra de verdad.
    r = edu.post("/educadores", data={"nombre": "Se Escribió Mal", "usuario_nuevo": "tpyo"})
    with SesionLocal() as s:
        tpyo_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "tpyo"))
    with SesionLocal() as s:
        check("una cuenta recién creada no dejó rastro", not cuentas.dejo_rastro(s, tpyo_id))
    check("y la pantalla ofrece borrarla, no darla de baja", "Borrar cuenta" in r.text)
    edu.post(f"/educadores/{tpyo_id}/baja")
    with SesionLocal() as s:
        check("borrar una cuenta sin rastro la saca de la base",
              s.get(Usuario, tpyo_id) is None)

    # b) Sofía ya firmó cosas: se desactiva y su nombre se queda donde está.
    with SesionLocal() as s:
        s.add(CambioEtapa(joven_id=ana_id, etapa_anterior="pistas",
                          etapa_nueva="pistas", educador_id=sofia_id,
                          nota="firma de prueba"))
        s.commit()
    with SesionLocal() as s:
        check("quien firmó algo sí deja rastro", cuentas.dejo_rastro(s, sofia_id))
    check("y la pantalla ofrece sacarla del equipo", "Sacar del equipo" in edu.get("/educadores").text)

    check("nadie se da de baja a sí mismo",
          edu.post(f"/educadores/{educador_id}/baja").status_code == 400)
    check("por la puerta del equipo no se saca a un joven",
          edu.post(f"/educadores/{ana_id}/baja").status_code == 404)
    check("y un joven no saca a nadie del equipo",
          joven.post(f"/educadores/{sofia_id}/baja").status_code == 403)

    activa = TestClient(app, follow_redirects=True)
    activa.post("/ingresar", data={"usuario": "sofia", "clave": de_nuevo})
    edu.post(f"/educadores/{sofia_id}/baja")
    with SesionLocal() as s:
        fuera = s.get(Usuario, sofia_id)
        check("la cuenta con historia no se borra", fuera is not None)
        check("se desactiva", not fuera.activo)
        check("y su firma sigue en pie",
              s.scalar(select(CambioEtapa).where(CambioEtapa.educador_id == sofia_id)) is not None)
    check("la sesión que tenía abierta se corta sola",
          activa.get("/panel").url.path == "/ingresar")
    check("y no puede volver a entrar",
          "incorrectos" in activa.post("/ingresar", data={"usuario": "sofia", "clave": de_nuevo}).text)
    equipo_html = edu.get("/educadores").text
    check("aparece en «ya no están»", "Ya no están en el equipo" in equipo_html)
    check("no se la puede dar de baja dos veces",
          edu.post(f"/educadores/{sofia_id}/baja").status_code == 400)

    edu.post(f"/educadores/{sofia_id}/reincorporar")
    with SesionLocal() as s:
        check("reincorporar la devuelve al equipo", s.get(Usuario, sofia_id).activo)
    de_vuelta = TestClient(app, follow_redirects=True)
    check("y vuelve a entrar con la contraseña que tenía",
          de_vuelta.post("/ingresar", data={"usuario": "sofia", "clave": de_nuevo}).url.path == "/clave")
    # Se la vuelve a sacar: el resto del recorrido cuenta educadores activos.
    edu.post(f"/educadores/{sofia_id}/baja")

    # Cambiarla sin que nadie la obligue: el mismo formulario, desde el pie.
    r = joven.post(
        "/clave", data={"actual": "scout1907", "nueva": "linterna-77", "repetida": "linterna-77"}
    )
    check("cualquiera cambia su contraseña cuando quiere", "Contraseña cambiada" in r.text)
    check("y la sesión sigue abierta", joven.get("/hoy").status_code == 200)

    # --- cerrar cartas: la decisión es del educador --------------------------
    check("un joven no entra a la progresión", joven.get(f"/progresion/{ana_id}").status_code == 403)
    check("el educador abre la progresión", "Las cartas de esta etapa" in edu.get(f"/progresion/{ana_id}").text)

    def elegida_de(joven_id: int, competencia_id: int, etapa: str) -> CompetenciaElegida:
        with SesionLocal() as s:
            return s.scalar(
                select(CompetenciaElegida).where(
                    CompetenciaElegida.joven_id == joven_id,
                    CompetenciaElegida.competencia_id == competencia_id,
                    CompetenciaElegida.etapa == etapa,
                )
            )

    # Ana marcó un solo requerido de la carta 1: cerrarla es ir más allá de lo
    # que muestra la lista, y eso no puede pasar sin que alguien lo confirme.
    r = edu.post(f"/progresion/{ana_id}/cartas/1", data={"accion": "cerrar"}, follow_redirects=False)
    check(
        "cerrar una carta incompleta pide confirmación",
        "confirmar=1" in r.headers["location"],
        r.headers["location"],
    )
    check("y mientras tanto no la cierra", not elegida_de(ana_id, 1, "senda").lograda)
    check(
        "el aviso vuelve abierto sobre esa carta",
        "Falta confirmar." in edu.get(f"/progresion/{ana_id}?confirmar=1").text,
    )

    cierre = "Lo mostró en el Consejo de Patrulla: el resto lo hizo en el campamento."
    edu.post(
        f"/progresion/{ana_id}/cartas/1",
        data={"accion": "cerrar", "confirmado": "true", "nota": cierre},
    )
    cerrada = elegida_de(ana_id, 1, "senda")
    check("confirmando se cierra igual", cerrada.lograda)
    check("queda registrado que tenía requeridos sin marcar", cerrada.con_pendientes)
    check("y firmada por quien la cerró", cerrada.lograda_por_id is not None)
    check("el joven lee la nota del cierre", cierre in joven.get("/mis-cartas/1").text)
    joven.post("/mis-cartas/1")
    check("una carta lograda no se saca de la elección", elegida_de(ana_id, 1, "senda") is not None)

    # La carta 7, con todos sus requeridos marcados, se cierra derecho.
    with SesionLocal() as s:
        requeridos_7 = list(
            s.scalars(
                select(Desafio.id).where(
                    Desafio.competencia_id == 7, Desafio.tipo == DESAFIO_REQUERIDO
                )
            )
        )
    for desafio_id in requeridos_7:
        joven.post(f"/mis-cartas/7/desafios/{desafio_id}", data={"hecho": "true"})
    edu.post(f"/progresion/{ana_id}/cartas/7", data={"accion": "cerrar"})
    completa = elegida_de(ana_id, 7, "senda")
    check("con los requeridos hechos se cierra sin confirmar", completa.lograda)
    check("y no queda marcada como incompleta", not completa.con_pendientes)

    edu.post(f"/progresion/{ana_id}/cartas/7", data={"accion": "reabrir"})
    check("el educador puede reabrir un cierre", not elegida_de(ana_id, 7, "senda").lograda)

    # --- el paso de etapa ----------------------------------------------------
    recuerdo_senda = "En Senda armé el botiquín de la patrulla y lo conté en el Consejo."
    with SesionLocal() as s:
        bruno = s.scalar(select(Usuario).where(Usuario.usuario == "bruno"))
        bruno_id, bruno_patrulla = bruno.id, bruno.patrulla_id
        eli_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "eli"))
        # A Elisa le damos la etapa recorrida: es el único camino que sale
        # derecho, y armarlo carta por carta desde el navegador no probaría nada
        # distinto de lo que ya probamos arriba.
        for numero in range(1, MIN_CARTAS + 1):
            s.add(
                CompetenciaElegida(
                    joven_id=eli_id, competencia_id=numero, etapa="senda", lograda=True
                )
            )
        s.add(
            AvanceDesafio(
                joven_id=eli_id,
                desafio_id=requerido_id,
                etapa="senda",
                hecho=True,
                comentario=recuerdo_senda,
            )
        )
        # La etapa no son solo las cartas (cap. 9): Senda pide además dos cargos
        # distintos cumplidos y haber estado en una descubierta. Sin esto la
        # aplicación tiene razón en pedir confirmación, y eso se prueba aparte.
        dos_cargos = list(s.scalars(select(Cargo.id).order_by(Cargo.orden).limit(2)))
        for cargo_id in dos_cargos:
            s.add(
                PeriodoCargo(
                    cargo_id=cargo_id,
                    joven_id=eli_id,
                    patrulla_id=s.get(Usuario, eli_id).patrulla_id,
                    desde=date.today() - timedelta(days=120),
                    hasta=date.today() - timedelta(days=10),
                    cumplido=True,
                )
            )
        descubierta = Actividad(
            unidad_id=s.get(Usuario, eli_id).unidad_id,
            titulo="Visita al comedor del barrio",
            fecha=date.today() - timedelta(days=30),
            clase=CLASE_DESCUBIERTA,
        )
        s.add(descubierta)
        s.flush()
        s.add(ParticipacionActividad(actividad_id=descubierta.id, joven_id=eli_id))
        s.commit()

    r = edu.post(f"/progresion/{bruno_id}/etapa", data={"etapa": "senda"}, follow_redirects=False)
    check(
        "cambiar de etapa sin las cartas pide confirmación",
        "confirmar=etapa" in r.headers["location"],
        r.headers["location"],
    )
    with SesionLocal() as s:
        check("y no lo cambia", s.get(Usuario, bruno_id).etapa == "pistas")
    check(
        "la página explica qué falta confirmar",
        "Falta confirmar el cambio." in edu.get(f"/progresion/{bruno_id}?confirmar=etapa").text,
    )

    edu.post(
        f"/progresion/{bruno_id}/etapa",
        data={"etapa": "senda", "confirmado": "true", "nota": "Se suma al grupo de Senda."},
    )
    with SesionLocal() as s:
        check("confirmando, el educador lo pasa igual", s.get(Usuario, bruno_id).etapa == "senda")
        cambio = s.scalar(select(CambioEtapa).where(CambioEtapa.joven_id == bruno_id))
        check("el cambio queda registrado con quién y con qué números",
              cambio is not None and cambio.educador_id is not None and cambio.con_pendientes,
              f"{cambio.cartas_logradas} cartas logradas" if cambio else "sin registro")

    edu.post(f"/progresion/{eli_id}/etapa", data={"etapa": "rumbo"})
    with SesionLocal() as s:
        check("con la etapa recorrida el paso sale derecho", s.get(Usuario, eli_id).etapa == "rumbo")
        check(
            "las cartas quedan guardadas en la etapa donde se hicieron",
            s.scalar(
                select(func.count(CompetenciaElegida.id)).where(
                    CompetenciaElegida.joven_id == eli_id, CompetenciaElegida.etapa == "senda"
                )
            ) == MIN_CARTAS,
        )

    edu.post(f"/jovenes/{bruno_id}", data={"patrulla_id": str(bruno_patrulla), "etapa": "travesia"})
    with SesionLocal() as s:
        check(
            "la etapa no se cambia desde el listado de jóvenes",
            s.get(Usuario, bruno_id).etapa == "senda",
        )

    # --- lo que quedó de la etapa anterior -----------------------------------
    elisa = TestClient(app, follow_redirects=True)
    elisa.post("/ingresar", data={"usuario": "eli", "clave": "scout1907"})
    pagina = elisa.get("/mis-cartas").text

    check("una carta ya lograda no vuelve al catálogo", 'data-carta="1"' not in pagina)
    check("las que no logró siguen estando", 'data-carta="13"' in pagina)
    check("el catálogo dice cuántas quedan", "ya las lograste y están" in pagina)
    check("el historial guarda la etapa anterior", "Etapa Senda" in pagina)
    check("con las anotaciones de entonces", recuerdo_senda in pagina)

    r = elisa.post("/mis-cartas/1", follow_redirects=False)
    check("volver a elegirla se rechaza con su motivo", r.status_code == 400, r.status_code)
    check("y el motivo dice en qué etapa fue", "Senda" in r.text)

    r = elisa.get("/mis-cartas/1")
    check("la carta lograda antes se abre de solo lectura", "ya la lograste en la etapa Senda" in r.text)
    check("y no ofrece marcar nada", 'name="hecho"' not in r.text)
    check("pero muestra lo que había escrito", recuerdo_senda in r.text)

    check(
        "la patrulla y el educador ven ese historial",
        recuerdo_senda in edu.get(f"/cartas-de/{eli_id}").text,
    )
    check(
        "y también desde la progresión",
        "Lo que quedó de las etapas anteriores" in edu.get(f"/progresion/{eli_id}").text,
    )

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

    # Tener sesión no alcanza: la foto se sirve a quien podría ver la página
    # donde vive. El uuid se filtra solo —el historial, una captura reenviada— y
    # sin esto el link suelto valía más que el permiso sobre el Libro de Oro.
    check("la patrulla ve la foto de su libro",
          companiera.get(f"/fotos/{nombre_foto}").status_code == 200)
    check("otra patrulla no ve esa foto ni con el uuid en la mano",
          de_otra.get(f"/fotos/{nombre_foto}").status_code == 404)
    check("el equipo sí la ve", edu.get(f"/fotos/{nombre_foto}").status_code == 200)
    check("un archivo que no es de nadie no se sirve",
          joven.get("/fotos/00000000000000000000000000000000.jpg").status_code == 404)
    check("no se puede salir del directorio de subidas",
          joven.get("/fotos/..%2F..%2Fscout.db").status_code == 404)

    # --- lo que puede tumbar el contenedor ------------------------------------
    #
    # 0,5 GiB de memoria: lo que entra por un formulario lo elige otro, y hay dos
    # formas de convertir un archivo chico en un problema grande.

    # Una bomba de descompresión: 20000x20000 en blanco son unos pocos kB
    # comprimidos y 1,2 GB abiertos. El tope de bytes no la ve pasar.
    bomba = BytesIO()
    Image.new("L", (20000, 20000)).save(bomba, "PNG")
    bomba = bomba.getvalue()
    check("una bomba de descompresión pesa poquísimo",
          len(bomba) < 1024 * 1024, f"{len(bomba) // 1024} kB")
    # Ojo con `r`: más abajo se sigue usando la respuesta del alta de la página
    # del libro, así que estas dos van a variables propias.
    rechazo = joven.post(
        f"/libro-de-oro/{halcones_id}",
        data={"titulo": "Bomba", "texto": "x", "fecha": "2026-07-18"},
        files={"foto": ("bomba.png", bomba, "image/png")},
    )
    check("y se rechaza con un motivo, no con un 500",
          rechazo.status_code == 400, rechazo.status_code)

    # Un cuerpo enorme se corta por Content-Length antes de leer un solo byte.
    gigante = joven.post(
        f"/libro-de-oro/{halcones_id}",
        data={"titulo": "Gigante", "texto": "x", "fecha": "2026-07-18"},
        files={"foto": ("gigante.jpg", b"\xff\xd8" + b"\x00" * (12 * 1024 * 1024), "image/jpeg")},
    )
    check("un cuerpo de 12 MB se rechaza antes de leerlo",
          gigante.status_code == 413, gigante.status_code)
    check("y ninguna de las dos dejó basura en el disco",
          len(list(SUBIDAS.glob("*.jpg"))) == 1, len(list(SUBIDAS.glob("*.jpg"))))

    check(
        "borrar una página pregunta dentro de la tarjeta, y con confirm() si no hay JavaScript",
        "data-confirmar=" in r.text and "onsubmit=" in r.text,
    )
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

    # El libro se publica en el momento y es de la patrulla: no espera permiso de
    # ningún adulto. Lo que sí hay es avisar y bajar, igual que en el muro.
    check("quien no escribió la página puede avisar",
          "Avisar al equipo" in companiera.get(f"/libro-de-oro/{halcones_id}").text)
    check("avisar sobre una página del libro",
          companiera.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/avisar",
                          data={"motivo": "Sale mi hermano y no quiere."}).status_code == 200)
    check("otra patrulla no puede avisar sobre un libro que no ve",
          de_otra.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/avisar").status_code == 404)
    check("la página del libro llega al feed del equipo",
          recuerdo in edu.get("/novedades?filtro=avisadas").text)

    edu.post(f"/novedades/libro/{entrada_id}",
             data={"decision": "bajar", "resolucion": "La bajamos, lo hablamos el sábado."})
    check("bajada, la patrulla ya no la ve",
          recuerdo not in companiera.get(f"/libro-de-oro/{halcones_id}").text)
    check("su autor la sigue viendo, marcada",
          "El equipo bajó esta página" in joven.get(f"/libro-de-oro/{halcones_id}").text)
    check("y la foto de una página bajada no se sirve a la patrulla",
          companiera.get(f"/fotos/{nombre_foto}").status_code == 404)
    edu.post(f"/novedades/libro/{entrada_id}", data={"decision": "devolver"})
    check("devuelta, la patrulla la ve de nuevo",
          recuerdo in companiera.get(f"/libro-de-oro/{halcones_id}").text)

    # Cerrar un aviso sin bajar nada: que exista esta salida es lo que impide que
    # avisar sea, en los hechos, sacar algo del muro.
    companiera.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/avisar", data={"motivo": "otra"})
    edu.post(f"/novedades/libro/{entrada_id}",
             data={"decision": "esta_bien", "resolucion": "Lo miramos y queda."})
    check("un aviso se puede cerrar dejando la página publicada",
          recuerdo in companiera.get(f"/libro-de-oro/{halcones_id}").text)
    check("y el panel deja de marcarlo",
          "con un aviso sin mirar" not in edu.get("/panel").text)
    edu.post(f"/libro-de-oro/{halcones_id}/{entrada_id}/borrar")
    check(
        "el educador puede borrar",
        recuerdo not in joven.get(f"/libro-de-oro/{halcones_id}").text,
    )
    check("borrar la página borra su foto", not list(SUBIDAS.glob("*.jpg")))

    # --- sacar un reto de la agenda -------------------------------------------
    # Arrepentirse de un reto que nadie entregó tiene que ser barato. Borrar uno
    # que ya tiene entregas adentro, no: ahí hay trabajo de un chico y puntos de
    # una patrulla.

    manana = (date.today() + timedelta(days=1)).isoformat()
    r = edu.post("/asignar", data={"reto_id": str(reto_id), "fecha": manana, "alcance": "unidad"})
    agendado = int(re.findall(r"/asignar/(\d+)/borrar", r.text)[-1])
    check("el reto de mañana queda agendado", f"/asignar/{agendado}/borrar" in r.text)
    check("la agenda tiene su columna para quitar", "<th>Quitar</th>" in r.text)

    # Un `confirmar` que no lleva a ningún lado no puede voltear la página.
    check(
        "un confirmar inventado no rompe la agenda",
        edu.get("/asignar?confirmar=999999").status_code == 200
        and edu.get("/asignar?confirmar=abc").status_code == 200,
    )

    check(
        "un joven no saca retos de la agenda",
        joven.post(f"/asignar/{agendado}/borrar").status_code == 403,
    )
    check(
        "una asignación de otra Unidad no existe",
        edu.post("/asignar/999999/borrar").status_code == 404,
    )

    r = edu.post(f"/asignar/{agendado}/borrar", follow_redirects=False)
    check("sin entregas se saca derecho", r.headers["location"] == "/asignar", r.headers["location"])
    with SesionLocal() as s:
        check("y desaparece de la base", s.get(Asignacion, agendado) is None)

    # La de «Nudo margarita» tiene una entrega validada de 15 puntos.
    con_entregas = nuevo["asignacion_id"]
    with SesionLocal() as s:
        entrega = s.scalar(select(Entrega).where(Entrega.asignacion_id == con_entregas))
        # Una entrada de bitácora colgada de esa entrega: es lo personal del
        # joven y no puede irse con el reto del que se arrepintió el educador.
        s.add(EntradaBitacora(joven_id=ana_id, entrega_id=entrega.id,
                              titulo="El nudo", texto="Me salió a la tercera."))
        s.commit()

    r = edu.post(f"/asignar/{con_entregas}/borrar", follow_redirects=False)
    check(
        "con entregas adentro pide confirmación",
        f"confirmar={con_entregas}" in r.headers["location"],
        r.headers["location"],
    )
    with SesionLocal() as s:
        check("y mientras tanto no lo saca", s.get(Asignacion, con_entregas) is not None)

    pagina = edu.get(f"/asignar?confirmar={con_entregas}").text
    check("la página dice cuántos puntos se llevaría", "15 puntos" in pagina)
    check("y a qué patrulla", "Halcones" in pagina)

    edu.post(f"/asignar/{con_entregas}/borrar", data={"confirmado": "true"})
    with SesionLocal() as s:
        check("confirmando se saca igual", s.get(Asignacion, con_entregas) is None)
        check(
            "y se lleva sus entregas",
            s.scalar(select(func.count(Entrega.id)).where(
                Entrega.asignacion_id == con_entregas)) == 0,
        )
        suelta = s.scalar(select(EntradaBitacora).where(EntradaBitacora.titulo == "El nudo"))
        check("la bitácora del joven sobrevive", suelta is not None)
        check("y queda sin el vínculo a la entrega borrada", suelta.entrega_id is None)

    halcones = next(f for f in joven.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("los puntos vuelven a donde estaban", halcones["puntos"] == 10, halcones["puntos"])

    # Una entrega con foto: el archivo tampoco puede quedar dando vueltas.
    edu.post("/asignar", data={"reto_id": str(reto_id), "fecha": date.today().isoformat(),
                               "alcance": "unidad"})
    with SesionLocal() as s:
        con_foto = s.scalar(select(func.max(Asignacion.id)))
    joven.post(f"/reto/{con_foto}", data={"texto": "corto"},
               files={"foto": ("entrega.jpg", original, "image/jpeg")})
    check("la entrega deja su foto en disco", len(list(SUBIDAS.glob("*.jpg"))) == 1)

    # Reentregar con otra foto: la anterior se va del disco. Antes quedaba ahí
    # para siempre, sin nada que la referenciara y accesible por su dirección.
    vieja = list(SUBIDAS.glob("*.jpg"))[0]
    joven.post(f"/reto/{con_foto}", data={"texto": "corto, de nuevo"},
               files={"foto": ("otra.jpg", original, "image/jpeg")})
    check("reentregar con otra foto borra la anterior", not vieja.exists())
    check("y no deja dos fotos para una sola entrega",
          len(list(SUBIDAS.glob("*.jpg"))) == 1, len(list(SUBIDAS.glob("*.jpg"))))

    edu.post(f"/asignar/{con_foto}/borrar", data={"confirmado": "true"})
    check("sacar el reto borra las fotos de sus entregas", not list(SUBIDAS.glob("*.jpg")))

    # El reto que inventó la aplicación no sobrevive a su asignación.
    with SesionLocal() as s:
        automatica = s.scalar(select(Asignacion).where(Asignacion.automatica.is_(True)))
        auto_id, auto_reto = automatica.id, automatica.reto_id
    edu.post(f"/asignar/{auto_id}/borrar", data={"confirmado": "true"})
    with SesionLocal() as s:
        check("sacar el reto propuesto se lleva el reto que inventó la app",
              s.get(Asignacion, auto_id) is None and s.get(Reto, auto_reto) is None)
        check("el reto que escribió el educador sigue en su lista",
              s.get(Reto, reto_id) is not None)

    # --- 1. Los cargos de patrulla (cap. 4) ---------------------------------
    with SesionLocal() as s:
        ana = s.scalar(select(Usuario).where(Usuario.usuario == "ana"))
        ana_patrulla = ana.patrulla_id
        cargo_guia = s.scalar(select(Cargo).where(Cargo.nombre == "Guía"))
        cargo_guia_id = cargo_guia.id
        cargo_cocina_id = s.scalar(select(Cargo.id).where(Cargo.nombre == "Cocinero/a"))
        dante_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "dante"))

    check("el catálogo de cargos nace con los de la guía", cargo_guia is not None)
    check(
        "la patrulla propia abre",
        joven.get(f"/patrulla/{ana_patrulla}").status_code == 200,
    )
    check(
        "la patrulla ajena no existe para un joven",
        joven.get("/patrulla/999999").status_code == 404,
    )
    otra = None
    with SesionLocal() as s:
        otra = s.scalar(select(Patrulla.id).where(Patrulla.id != ana_patrulla))
    check("ni la de al lado", joven.get(f"/patrulla/{otra}").status_code == 404)
    check("el educador sí entra a cualquiera", edu.get(f"/patrulla/{otra}").status_code == 200)

    joven.post(
        f"/patrulla/{ana_patrulla}/cargos",
        data={"cargo_id": str(cargo_guia_id), "joven_id": str(ana_id)},
    )
    with SesionLocal() as s:
        periodo = s.scalar(select(PeriodoCargo).where(PeriodoCargo.joven_id == ana_id))
        check("un joven puede repartir cargos en su patrulla", periodo is not None)
        check("y el período nace abierto", periodo is not None and periodo.hasta is None)
        periodo_id = periodo.id

    joven.post(
        f"/patrulla/{ana_patrulla}/cargos",
        data={"cargo_id": str(cargo_guia_id), "joven_id": str(ana_id)},
    )
    with SesionLocal() as s:
        repetidos = s.scalar(
            select(func.count(PeriodoCargo.id)).where(PeriodoCargo.joven_id == ana_id)
        )
        check("tomar dos veces el mismo cargo no duplica el período", repetidos == 1)

    check(
        "no se le puede dar un cargo a alguien de otra patrulla",
        joven.post(
            f"/patrulla/{ana_patrulla}/cargos",
            data={"cargo_id": str(cargo_guia_id), "joven_id": str(dante_id)},
        ).status_code == 404,
    )

    joven.post(
        f"/patrulla/{ana_patrulla}/cargos/{periodo_id}/cerrar",
        data={"cumplido": "true", "nota": "Coordinó todo el ciclo."},
    )
    with SesionLocal() as s:
        cerrado = s.get(PeriodoCargo, periodo_id)
        check("el Consejo cierra el período con su evaluación",
              cerrado.hasta is not None and cerrado.cumplido)

    # Ese cargo cumplido es lo que Pistas pide además de las cartas.
    with SesionLocal() as s:
        bruno = s.scalar(select(Usuario).where(Usuario.usuario == "bruno"))
        bruno.etapa = "pistas"
        s.commit()
    texto_progresion = edu.get(f"/progresion/{bruno_id}").text
    check("la etapa muestra lo que pide además de las cartas",
          "Cargos de patrulla distintos, cumplidos" in texto_progresion)
    # Travesía suma dos exigencias que ninguna base de datos puede verificar. No
    # se cuentan: se muestran para que alguien se acuerde de conversarlas.
    from app.servicios.progresion import REQUISITOS_ETAPA  # noqa: PLC0415

    check("Travesía pide tres cargos", REQUISITOS_ETAPA["travesia"].cargos == 3)
    check("y suma lo que no se puede medir",
          any("Exploración de Travesía" in t
              for t in REQUISITOS_ETAPA["travesia"].conversadas))

    # --- 2. Voz y voto: las ideas (cap. 8) ----------------------------------
    #
    # La Asamblea no pasa por la aplicación: se reúne en persona. Acá se prueba
    # que la pantalla junta las propuestas y anota lo que se decidió allá.
    joven.post("/ideas", data={
        "titulo": "Salida de noche a la reserva",
        "texto": "Ir a ver las estrellas con el telescopio del club.",
        "hace_falta": "Permiso y alguien que sepa de astronomía.",
        "clase": "actividad", "ambito": "unidad",
    })
    with SesionLocal() as s:
        idea = s.scalar(select(Idea).where(Idea.titulo.like("Salida de noche%")))
        idea_id = idea.id
        check("un joven propone una idea", idea is not None)
        check("y queda a nombre de su patrulla", idea.patrulla_id == ana_patrulla)
        check("nace como propuesta", idea.estado == "propuesta")

    check("la idea aparece en el buzón", "Salida de noche" in joven.get("/ideas").text)
    check("la pantalla avisa que la Asamblea es presencial",
          "la Asamblea es en persona" in joven.get("/ideas").text)
    check("no hay ninguna pantalla de votación",
          joven.get("/asamblea").status_code == 404)

    joven.post(f"/ideas/{idea_id}/apoyo")
    check("«me sumo» queda anotado", "Me sumé" in joven.get("/ideas").text)
    check(
        "un educador no apoya ideas: eso es de los jóvenes",
        edu.post(f"/ideas/{idea_id}/apoyo").status_code == 403,
    )

    # El equipo la mira y dice si se puede.
    check(
        "un joven no mueve el estado de una idea",
        joven.post(f"/ideas/{idea_id}/estado", data={"estado": "posible"}).status_code == 403,
    )
    edu.post(f"/ideas/{idea_id}/estado",
             data={"estado": "posible", "respuesta": "Se puede, hay que pedir permiso."})
    with SesionLocal() as s:
        mirada = s.get(Idea, idea_id)
        check("el equipo la marca como posible", mirada.estado == "posible")
        check("y le contesta a quien la propuso",
              "hay que pedir permiso" in mirada.respuesta)
    check("la respuesta se ve en la página", "pedir permiso" in joven.get("/ideas").text)

    check(
        "un estado inventado se rechaza",
        edu.post(f"/ideas/{idea_id}/estado", data={"estado": "genial"}).status_code == 400,
    )

    # Una segunda idea para probar el guardado y el borrado.
    edu.post("/ideas", data={"titulo": "Torneo de pionerismo", "clase": "proyecto",
                             "ambito": "unidad"})
    with SesionLocal() as s:
        segunda = s.scalar(select(Idea).where(Idea.titulo == "Torneo de pionerismo"))
        segunda_id = segunda.id
        check("el educador también propone: la guía se lo pide", segunda is not None)

    edu.post(f"/ideas/{segunda_id}/estado",
             data={"estado": "guardada", "respuesta": "Este ciclo no llegamos."})
    with SesionLocal() as s:
        check("lo que no sale se guarda, no se borra",
              s.get(Idea, segunda_id).estado == "guardada")

    # Después de la Asamblea presencial, el equipo anota lo elegido y lo agenda.
    edu.post(f"/ideas/{idea_id}/agendar",
             data={"fecha": (date.today() + timedelta(days=20)).isoformat()})
    with SesionLocal() as s:
        elegida_idea = s.get(Idea, idea_id)
        check("agendarla la marca como elegida en la Asamblea",
              elegida_idea.estado == "elegida")
        agendada = s.scalar(select(Actividad).where(Actividad.idea_id == idea_id))
        check("y cae en el calendario", agendada is not None)
        check("con el título de la idea", agendada.titulo == elegida_idea.titulo)

    # Borrar: el equipo siempre; el autor solo mientras nadie la haya mirado.
    joven.post("/ideas", data={"titulo": "Me arrepentí", "clase": "actividad"})
    with SesionLocal() as s:
        arrepentida = s.scalar(select(Idea).where(Idea.titulo == "Me arrepentí"))
        arrepentida_id = arrepentida.id
    joven.post(f"/ideas/{arrepentida_id}/borrar")
    with SesionLocal() as s:
        check("el autor borra la suya mientras nadie la miró",
              s.get(Idea, arrepentida_id) is None)

    check(
        "pero no una que el equipo ya marcó",
        joven.post(f"/ideas/{idea_id}/borrar").status_code == 403,
    )
    edu.post(f"/ideas/{segunda_id}/borrar")
    with SesionLocal() as s:
        check("el equipo sí la borra", s.get(Idea, segunda_id) is None)


    # --- 3. La autoevaluación: la carta la cierra el joven (cap. 9) ---------
    joven.post("/mis-cartas/33")  # una carta que todavía no tocó
    check("la carta nueva queda elegida", elegida_de(ana_id, 33, "senda") is not None)
    with SesionLocal() as s:
        requeridos_33 = list(
            s.scalars(
                select(Desafio.id).where(
                    Desafio.competencia_id == 33, Desafio.tipo == DESAFIO_REQUERIDO
                )
            )
        )

    r = joven.post("/mis-cartas/33/cerrar", data={"autoevaluacion": ""})
    check("cerrar sin escribir nada se rechaza", r.status_code == 400)

    reflexion = ("Aprendí a cocinar para ocho. Me costó calcular las cantidades y "
                 "me ayudó Elisa. Quiero aprender a hacer pan en el fogón.")
    r = joven.post("/mis-cartas/33/cerrar", data={"autoevaluacion": reflexion})
    check("con requeridos sin marcar pide confirmar", "falta confirmar" in r.text.lower())
    check("y no pierde lo que escribió", reflexion in r.text)
    check("la carta sigue abierta", not elegida_de(ana_id, 33, "senda").lograda)

    for desafio_id in requeridos_33:
        joven.post(f"/mis-cartas/33/desafios/{desafio_id}", data={"hecho": "true"})
    joven.post("/mis-cartas/33/cerrar", data={"autoevaluacion": reflexion})
    cerrada_por_ella = elegida_de(ana_id, 33, "senda")
    check("con todo hecho, el joven cierra su propia carta", cerrada_por_ella.lograda)
    check("y queda firmada por ella, no por el educador",
          cerrada_por_ella.lograda_por_id == ana_id)
    check("la autoevaluación queda guardada",
          cerrada_por_ella.autoevaluacion == reflexion)
    check("no nace acordada: falta la conversación", not cerrada_por_ella.acordada)

    panel = edu.get("/panel").text
    check("el panel del educador pide esa conversación",
          "esperan una conversación" in panel)
    check("el educador ve la autoevaluación",
          reflexion in edu.get(f"/progresion/{ana_id}").text)

    edu.post(f"/progresion/{ana_id}/cartas/33",
             data={"accion": "acordar", "nota": "Lo charlamos después del campamento."})
    acordada = elegida_de(ana_id, 33, "senda")
    check("el educador registra la conversación", acordada.acordada)
    check("y queda quién la conversó", acordada.acordada_por_id is not None)
    check("acordar no cambia quién la cerró", acordada.lograda_por_id == ana_id)

    # --- 4. El Consejo de Patrulla ------------------------------------------
    r = joven.post(f"/patrulla/{ana_patrulla}/consejo", data={"temas": ""})
    check("un Consejo sin temas se rechaza", r.status_code == 400)

    joven.post(f"/patrulla/{ana_patrulla}/consejo", data={
        "fecha": date.today().isoformat(),
        "temas": "Elegimos las actividades del ciclo y repartimos los cargos.",
        "presente": [str(ana_id), str(dante_id)],
    })
    with SesionLocal() as s:
        from app.models import ConsejoPatrulla, PresenciaConsejo  # noqa: PLC0415

        consejo = s.scalar(select(ConsejoPatrulla))
        consejo_id = consejo.id
        check("queda el acta del Consejo", consejo is not None)
        presentes = s.scalar(
            select(func.count(PresenciaConsejo.id)).where(
                PresenciaConsejo.consejo_id == consejo_id
            )
        )
        # Dante es de otra patrulla: no puede figurar como presente en esta.
        check("solo entran como presentes los de la patrulla", presentes == 1)

    joven.post(f"/patrulla/{ana_patrulla}/acuerdos", data={
        "texto": "Llevar las carpas a secar",
        "responsable_id": str(ana_id),
        "para_cuando": (date.today() + timedelta(days=3)).isoformat(),
        "consejo_id": str(consejo_id),
    })
    with SesionLocal() as s:
        from app.models import Acuerdo  # noqa: PLC0415

        acuerdo = s.scalar(select(Acuerdo))
        acuerdo_id = acuerdo.id
        check("el acuerdo queda con nombre y fecha",
              acuerdo.responsable_id == ana_id and acuerdo.para_cuando is not None)

    check("el acuerdo espera a su responsable en /hoy",
          "Llevar las carpas a secar" in joven.get("/hoy").text)
    joven.post(f"/acuerdos/{acuerdo_id}", data={"cumplido": "true", "volver": "hoy"})
    with SesionLocal() as s:
        check("y se puede dar por hecho", s.get(Acuerdo, acuerdo_id).cumplido)
    check("una vez hecho ya no molesta en /hoy",
          "Llevar las carpas a secar" not in joven.get("/hoy").text)

    # --- 5. El calendario del ciclo -----------------------------------------
    manana = (date.today() + timedelta(days=5)).isoformat()
    edu.post("/calendario", data={
        "titulo": "Campamento de primavera", "fecha": manana,
        "hasta": (date.today() + timedelta(days=7)).isoformat(),
        "clase": "campamento", "lugar": "Los Robles",
    })
    with SesionLocal() as s:
        campamento = s.scalar(select(Actividad).where(Actividad.titulo.like("Campamento%")))
        campamento_id = campamento.id
        check("el educador agenda un campamento", campamento is not None)
        check("con su rango de días", campamento.hasta is not None)

    check("lo que viene aparece en /hoy", "Campamento de primavera" in joven.get("/hoy").text)
    check("y en el calendario", "Los Robles" in joven.get("/calendario").text)
    check(
        "un joven no agenda actividades de la Unidad",
        joven.post("/calendario", data={"titulo": "La mía", "fecha": manana}).status_code == 403,
    )

    # «Estuve» lo marca cada uno, y es lo que cuenta para la etapa.
    with SesionLocal() as s:
        proyecto = Actividad(
            unidad_id=s.get(Usuario, ana_id).unidad_id,
            titulo="Proyecto de la huerta",
            fecha=date.today() - timedelta(days=15),
            clase="proyecto",
        )
        s.add(proyecto)
        s.commit()
        proyecto_id = proyecto.id

    check(
        "un educador no marca «estuve» por otro",
        edu.post(f"/calendario/{proyecto_id}/estuve").status_code == 403,
    )
    joven.post(f"/calendario/{proyecto_id}/estuve")
    with SesionLocal() as s:
        check("el joven marca dónde estuvo",
              s.scalar(select(func.count(ParticipacionActividad.id)).where(
                  ParticipacionActividad.joven_id == ana_id)) == 1)
    # Y eso es lo que alimenta los requisitos de la etapa: no una lista de
    # asistencia que lleva un adulto, sino lo que cada uno dice que hizo.
    with SesionLocal() as s:
        from app.servicios import agenda as servicio_agenda  # noqa: PLC0415

        hizo = servicio_agenda.lo_que_hizo(s, s.get(Usuario, ana_id))
        check("lo marcado cuenta como proyecto de Unidad", hizo.proyectos_unidad == 1)
    check("y la etapa lo lista entre lo que pide",
          "Descubiertas" in edu.get(f"/progresion/{ana_id}").text)

    # Una actividad de otra patrulla no se ve, igual que el Libro de Oro.
    with SesionLocal() as s:
        ajena = Actividad(
            unidad_id=s.get(Usuario, ana_id).unidad_id,
            patrulla_id=otra,
            titulo="Reunión secreta de los Pumas",
            fecha=date.today() + timedelta(days=2),
        )
        s.add(ajena)
        s.commit()
        ajena_id = ajena.id
    check("la actividad de otra patrulla no se ve",
          "Reunión secreta" not in joven.get("/calendario").text)
    check("ni se puede marcar",
          joven.post(f"/calendario/{ajena_id}/estuve").status_code == 404)

    # --- 6. Las especialidades ----------------------------------------------
    #
    # La pide el joven, la que quiera; el recorrido lo arma el equipo para esa
    # persona; la cierra el equipo.
    check("la página de especialidades abre",
          joven.get("/especialidades").status_code == 200)
    check(
        "una especialidad sin nombre se rechaza",
        joven.post("/especialidades", data={"nombre": " "}).status_code == 400,
    )
    check(
        "un educador no pide especialidades",
        edu.post("/especialidades", data={"nombre": "Cocina"}).status_code == 403,
    )

    # El campo es libre: nada de elegir de una lista.
    joven.post("/especialidades", data={
        "nombre": "Apicultura", "icono": "🐝",
        "motivo": "Mi tío tiene colmenas y quiero aprender a manejarlas.",
    })
    with SesionLocal() as s:
        esp = s.scalar(select(Especialidad).where(Especialidad.joven_id == ana_id))
        esp_id = esp.id
        check("el joven pide la especialidad que quiere", esp is not None)
        check("y queda con sus palabras", esp.nombre == "Apicultura")
        check("con el motivo que escribió", "colmenas" in esp.motivo)
        check("nace pedida, todavía sin preparar",
              esp.estado == "pedida" and not esp.preparada)

    joven.post("/especialidades", data={"nombre": "Apicultura"})
    with SesionLocal() as s:
        check("pedir dos veces lo mismo no la duplica",
              s.scalar(select(func.count(Especialidad.id)).where(
                  Especialidad.joven_id == ana_id)) == 1)

    # Pedirla es el aviso: aparece en el panel del equipo desde ese momento.
    check("el equipo ve el pedido en su panel",
          "esperan que armes el recorrido" in edu.get("/panel").text)
    check("y en la lista de especialidades", "Apicultura" in edu.get("/especialidades").text)
    check("con el motivo a la vista", "colmenas" in edu.get("/especialidades").text)

    # Hasta que el equipo no la prepara, no se puede empezar.
    texto_joven = joven.get("/especialidades").text
    check("mientras tanto el joven ve que la están preparando",
          "la está preparando" in texto_joven)

    check(
        "un joven no arma su propio recorrido",
        joven.post(f"/especialidades/{esp_id}/preparar",
                   data={"pide_taller": "lo que yo quiera"}).status_code == 403,
    )

    edu.post(f"/especialidades/{esp_id}/preparar", data={
        "experto": "Su tío Julio, apicultor",
        "pide_exploracion": "Conocer la colmena, el ahumador y el traje.",
        "pide_taller": "Acompañar una revisión de cuadros.",
        "pide_desafio": "Contarle a la Unidad cómo se cuida una colmena.",
    })
    with SesionLocal() as s:
        preparada = s.get(Especialidad, esp_id)
        check("el equipo arma el recorrido", preparada.preparada)
        check("con quién la acompaña", "Julio" in preparada.experto)
        check("y qué se espera en cada fase",
              "ahumador" in preparada.pide_exploracion)
        check("queda firmado por quien la preparó",
              preparada.preparada_por_id is not None)

    texto_joven = joven.get("/especialidades").text
    check("ahora el joven la puede empezar", "la está preparando" not in texto_joven)
    check("y ve lo que le pidieron", "ahumador" in texto_joven)

    joven.post(f"/especialidades/{esp_id}",
               data={"fase": "taller", "texto": "Fui a revisar los cuadros con mi tío."})
    with SesionLocal() as s:
        check("escribir en el taller adelanta la fase sola",
              s.get(Especialidad, esp_id).fase == "taller")

    check(
        "una fase inventada se rechaza",
        joven.post(f"/especialidades/{esp_id}",
                   data={"fase": "recreo", "texto": "x"}).status_code == 400,
    )

    joven.post(f"/especialidades/{esp_id}",
               data={"fase": "desafio", "texto": "Lo conté en la reunión del sábado."})
    check("el panel avisa que hay una lista para la insignia",
          "fase de servicio" in edu.get("/panel").text)

    check(
        "la especialidad de otro no se toca",
        elisa.post(f"/especialidades/{esp_id}",
                   data={"fase": "taller", "texto": "mía"}).status_code == 404,
    )
    check(
        "un joven no da por concluida su propia especialidad",
        joven.post(f"/especialidades/{esp_id}/entregar").status_code == 403,
    )

    edu.post(f"/especialidades/{esp_id}/entregar",
             data={"nota": "Explicó la colmena con las fotos de su tío."})
    with SesionLocal() as s:
        cerrada = s.get(Especialidad, esp_id)
        check("el educador la da por concluida", cerrada.lograda)
        check("y queda con quién la cerró y qué se conversó",
              cerrada.lograda_por_id is not None and "colmena" in cerrada.nota_cierre)
    check(
        "una especialidad lograda no se borra",
        joven.post(f"/especialidades/{esp_id}/borrar").status_code == 400,
    )

    # Cancelar un pedido antes de que lo preparen es barato.
    joven.post("/especialidades", data={"nombre": "Malabares"})
    with SesionLocal() as s:
        malabares = s.scalar(select(Especialidad).where(Especialidad.nombre == "Malabares"))
        malabares_id = malabares.id
    joven.post(f"/especialidades/{malabares_id}/borrar")
    with SesionLocal() as s:
        check("cancelar un pedido sin preparar se puede",
              s.get(Especialidad, malabares_id) is None)


    # --- 7. La identidad de la patrulla -------------------------------------
    joven.post(f"/patrulla/{ana_patrulla}/identidad", data={
        "lema": "Siempre más alto",
        "grito": "¡Halcones, al cielo!",
        "emblema": "🦅",
        "historia": "La patrulla nació en el campamento de 2019.",
        "fundada_en": "2019-03-15",
    })
    with SesionLocal() as s:
        p = s.get(Patrulla, ana_patrulla)
        check("la patrulla escribe su propia identidad", p.grito == "¡Halcones, al cielo!")
        check("con su emblema y su fecha", p.emblema == "🦅" and p.fundada_en is not None)
    check("el grito se ve en su página",
          "¡Halcones, al cielo!" in joven.get(f"/patrulla/{ana_patrulla}").text)
    check(
        "nadie edita la identidad de otra patrulla",
        joven.post(f"/patrulla/{otra}/identidad", data={"grito": "jaja"}).status_code == 404,
    )

    # El banderín es una foto y se comprime como cualquier otra.
    joven.post(
        f"/patrulla/{ana_patrulla}/identidad",
        data={"lema": "Siempre más alto"},
        files={"banderin": ("banderin.jpg", original, "image/jpeg")},
    )
    with SesionLocal() as s:
        check("el banderín queda guardado",
              s.get(Patrulla, ana_patrulla).archivo_banderin is not None)
    check("y solo se ve con sesión iniciada", len(list(SUBIDAS.glob("*.jpg"))) == 1)

    # --- 8. El muro de la Unidad --------------------------------------------
    #
    # Se comparte porque uno quiso, solo lo validado, y sin puntos al lado.
    check("el muro abre", joven.get("/muro").status_code == 200)

    edu.post("/asignar", data={"reto_id": str(reto_id), "fecha": date.today().isoformat(),
                               "alcance": "unidad"})
    with SesionLocal() as s:
        para_muro = s.scalar(select(func.max(Asignacion.id)))

    relato_muro = ("Armé el botiquín de la patrulla con la lista que nos dio la "
                   "enfermera y lo colgamos en el rincón.")
    joven.post(f"/reto/{para_muro}", data={"texto": relato_muro})
    with SesionLocal() as s:
        entrega_muro = s.scalar(
            select(Entrega).where(Entrega.asignacion_id == para_muro,
                                  Entrega.joven_id == ana_id)
        )
        check("una entrega completa se valida sola",
              entrega_muro.estado == "aprobada")
        check("y no se comparte si nadie lo pidió", not entrega_muro.compartida)
        entrega_muro_id = entrega_muro.id

    check("mientras tanto el muro sigue vacío para esa entrega",
          relato_muro not in joven.get("/muro").text)

    joven.post(f"/reto/{para_muro}/compartir")
    with SesionLocal() as s:
        check("el autor la comparte",
              s.get(Entrega, entrega_muro_id).compartida)
    texto_muro = joven.get("/muro").text
    check("y aparece en el muro", relato_muro in texto_muro)
    check("con el nombre de quien la hizo", "Ana" in texto_muro)
    check("el muro no muestra puntos", "puntaje" not in texto_muro.lower())
    check("otro joven de la Unidad la ve", relato_muro in elisa.get("/muro").text)
    check("y el equipo también", relato_muro in edu.get("/muro").text)

    check(
        "nadie comparte la entrega de otro",
        elisa.post(f"/reto/{para_muro}/compartir").status_code == 404,
    )

    # Dar de baja una entrega la saca del muro.
    edu.post(f"/validaciones/{entrega_muro_id}",
             data={"decision": "rechazar", "devolucion": "Esto no llegó a pasar."})
    with SesionLocal() as s:
        baja = s.get(Entrega, entrega_muro_id)
        check("el educador puede dar de baja algo ya validado",
              baja.estado == "rechazada" and baja.puntaje_otorgado == 0)
        check("y eso la saca del muro", not baja.compartida)
    check("ya no se ve en el muro", relato_muro not in joven.get("/muro").text)
    check(
        "no se comparte algo que no está validado",
        joven.post(f"/reto/{para_muro}/compartir").status_code == 400,
    )

    # --- 8b. Avisar y bajar: lo que sostiene publicar en el momento ----------
    #
    # Acá una foto entra al muro sin que un adulto la mire antes. La contraparte
    # es que cualquiera pueda pedir que la miren y que el equipo pueda bajarla
    # en dos toques, sin borrar nada. Ver `servicios/moderacion.py`.
    edu.post("/asignar", data={"reto_id": str(reto_id), "fecha": date.today().isoformat(),
                               "alcance": "unidad"})
    with SesionLocal() as s:
        para_avisar = s.scalar(select(func.max(Asignacion.id)))

    relato_aviso = ("Ordenamos el depósito del grupo y tiramos tres bolsas de cosas "
                    "rotas que estaban desde el campamento pasado.")
    joven.post(f"/reto/{para_avisar}", data={"texto": relato_aviso, "compartir": "true"})
    with SesionLocal() as s:
        pub = s.scalar(select(Entrega).where(Entrega.asignacion_id == para_avisar,
                                             Entrega.joven_id == ana_id))
        pub_id = pub.id
        check("compartir en la entrega publica de una", pub.compartida and not pub.oculta)
        check("y queda la fecha de publicación", pub.compartida_en is not None)

    check("se publica sin que ningún adulto lo mire antes",
          relato_aviso in elisa.get("/muro").text)

    novedades = edu.get("/novedades").text
    check("el equipo lo ve en /novedades", relato_aviso in novedades)
    check("y sabe que no es una cola de aprobación",
          "ya está publicado" in novedades)

    check("el autor no se avisa a sí mismo: ve el botón de sacarlo",
          "Sacarlo del muro" in joven.get("/muro").text)
    check("otro joven sí puede avisar",
          "Avisar al equipo" in elisa.get("/muro").text)

    r = elisa.post(f"/muro/{pub_id}/avisar", data={"motivo": "Salgo yo en esa foto."})
    check("avisar deja constancia", r.status_code == 200)
    with SesionLocal() as s:
        av = s.scalar(select(Aviso).where(Aviso.entrega_id == pub_id))
        check("el aviso guarda quién y por qué",
              av is not None and av.motivo == "Salgo yo en esa foto." and not av.atendido)
    check("avisar no baja nada por sí solo",
          relato_aviso in elisa.get("/muro").text)
    check("y no se avisa dos veces",
          elisa.post(f"/muro/{pub_id}/avisar", data={"motivo": "otra vez"}).status_code == 400)
    check("quien ya avisó lo ve en la página",
          "Avisaste al equipo" in elisa.get("/muro").text)
    check("el panel del equipo lo pone arriba de todo",
          "con un aviso sin mirar" in edu.get("/panel").text)

    # El equipo mira y baja. La entrega no se borra: conserva sus puntos.
    edu.post(f"/novedades/muro/{pub_id}",
             data={"decision": "bajar", "resolucion": "Lo hablamos con Ana."})
    with SesionLocal() as s:
        bajada = s.get(Entrega, pub_id)
        check("bajar no toca la entrega ni sus puntos",
              bajada.estado == "aprobada" and bajada.puntaje_otorgado > 0)
        check("ni el interruptor del autor", bajada.compartida)
        check("pero la marca como bajada", bajada.oculta and bajada.oculta_por_id is not None)
        check("y cierra el aviso con lo que se hizo",
              s.scalar(select(Aviso).where(Aviso.entrega_id == pub_id)).resolucion
              == "Lo hablamos con Ana.")
    check("una publicación bajada no está en el muro para nadie",
          relato_aviso not in elisa.get("/muro").text)
    check("tampoco para su autor",
          relato_aviso not in joven.get("/muro").text)
    check("y el autor no la puede volver a poner",
          joven.post(f"/reto/{para_avisar}/compartir").status_code == 400)

    edu.post(f"/novedades/muro/{pub_id}", data={"decision": "devolver"})
    with SesionLocal() as s:
        check("devolverla la desmarca", not s.get(Entrega, pub_id).oculta)
    check("y vuelve a verse en el muro", relato_aviso in elisa.get("/muro").text)

    # La lista de entregas del educador no es una cola de aprobación.
    entregas_html = edu.get("/validaciones").text
    check("la sección se llama por lo que es",
          "Lo que entregaron" in entregas_html)
    check("y avisa que lo completo se valida solo",
          "no es una cola de aprobación" in entregas_html.lower())

    # --- 9. El puntaje no premia a la patrulla más numerosa -----------------
    with SesionLocal() as s:
        halcones_p = s.scalar(select(Patrulla).where(Patrulla.nombre == "Halcones"))
        ceibos_p = s.scalar(select(Patrulla).where(Patrulla.nombre == "Ceibos"))
        # Halcones queda con el doble de gente y el doble de puntos: mismo
        # esfuerzo por cabeza, así que ninguna tiene que ganarle a la otra. Se
        # arma desde cero y no sobre lo que había, porque a esta altura de la
        # prueba la gente ya se movió de patrulla varias veces.
        s.execute(update(Entrega).values(puntaje_otorgado=0, estado="pendiente"))
        s.execute(
            update(Usuario)
            .where(Usuario.rol == ROL_JOVEN)
            .values(patrulla_id=None)
        )
        s.execute(
            update(Usuario)
            .where(Usuario.usuario.in_(("ana", "bruno")))
            .values(patrulla_id=halcones_p.id)
        )
        s.execute(
            update(Usuario)
            .where(Usuario.usuario == "eli")
            .values(patrulla_id=ceibos_p.id)
        )
        s.commit()

    from app.servicios import puntajes as servicio_puntajes  # noqa: PLC0415

    with SesionLocal() as s:
        entregas_falsas = [
            Entrega(asignacion_id=para_muro, joven_id=ana_id, patrulla_id=halcones_p.id,
                    estado="aprobada", puntaje_otorgado=20),
            Entrega(asignacion_id=para_muro, joven_id=eli_id, patrulla_id=ceibos_p.id,
                    estado="aprobada", puntaje_otorgado=10),
        ]
        s.execute(
            update(Entrega)
            .where(Entrega.id == entrega_muro_id)
            .values(estado="aprobada", puntaje_otorgado=20, patrulla_id=halcones_p.id)
        )
        s.add(entregas_falsas[1])
        s.commit()

        filas = servicio_puntajes.tablero_de_unidad(
            s, halcones_p.unidad_id, date.today()
        )
        por_nombre = {f.patrulla.nombre: f for f in filas}
        halcones_f, ceibos_f = por_nombre["Halcones"], por_nombre["Ceibos"]
        check("Halcones suma el doble de puntos en total",
              halcones_f.puntos == 2 * ceibos_f.puntos,
              f"{halcones_f.puntos} contra {ceibos_f.puntos}")
        check("pero tiene el doble de integrantes",
              halcones_f.integrantes == 2 * ceibos_f.integrantes,
              f"{halcones_f.integrantes} contra {ceibos_f.integrantes}")
        check("así que el promedio por integrante empata",
              halcones_f.promedio == ceibos_f.promedio,
              f"{halcones_f.promedio} contra {ceibos_f.promedio}")
        check("una patrulla sin integrantes no divide por cero",
              all(f.promedio == 0 for f in filas if f.integrantes == 0))
        check("el promedio redondo se escribe sin decimal",
              "." not in halcones_f.promedio_texto, halcones_f.promedio_texto)

    check("el tablero explica por qué es por integrante",
          "por integrante" in joven.get("/tablero").text)

    # --- 9b. Quien está sin teléfono no divide -------------------------------
    #
    # A alguien se le rompe el celular un martes y su patrulla pasa dos semanas
    # dividiendo por cinco lo que pudieron hacer cuatro: quedan atrás por algo
    # que no decidió ninguno. Tienen que pasar las dos cosas —que esa cabeza
    # salga del divisor, y que igual pueda registrar lo que hace dictándoselo a
    # alguien—, porque solo la primera le arregla el número a la patrulla y lo
    # deja a él mirando de afuera.

    check("un joven no pone a nadie sin teléfono",
          joven.post(f"/jovenes/{bruno_id}/pausa").status_code == 403)

    edu.post(f"/jovenes/{bruno_id}/pausa",
             data={"motivo": "Se le rompió el teléfono", "vuelve_el": ""})
    with SesionLocal() as s:
        pausa = s.scalar(
            select(PausaSinTelefono).where(PausaSinTelefono.joven_id == bruno_id)
        )
        check("el educador registra que está sin teléfono", pausa is not None)
        pausa_id = pausa.id
        check("y queda firmado quién lo anotó", pausa.abierta_por_id is not None)

        filas = servicio_puntajes.tablero_de_unidad(
            s, halcones_p.unidad_id, date.today()
        )
        por_nombre = {f.patrulla.nombre: f for f in filas}
        halcones_f, ceibos_f = por_nombre["Halcones"], por_nombre["Ceibos"]
        check("sigue siendo integrante de su patrulla",
              halcones_f.integrantes == 2, halcones_f.integrantes)
        check("pero no divide",
              halcones_f.dividen == 1 and halcones_f.en_pausa == 1,
              f"{halcones_f.dividen} dividen, {halcones_f.en_pausa} en pausa")
        check("y los puntos que ya había hecho se quedan en el total",
              halcones_f.puntos == 20, halcones_f.puntos)
        check("así que su patrulla deja de quedar atrás por eso",
              halcones_f.promedio > ceibos_f.promedio,
              f"{halcones_f.promedio} contra {ceibos_f.promedio}")

    check("el tablero dice por qué divide por menos",
          "sin teléfono" in joven.get("/tablero").text)
    # El motivo lo escribió un educador y se queda del lado del equipo: a la
    # patrulla le alcanza con saber que está sin teléfono.
    check("el motivo no se le muestra a la Unidad",
          "Se le rompió el teléfono" not in joven.get("/tablero").text
          and "Se le rompió el teléfono" not in joven.get(f"/patrulla/{halcones_p.id}").text)
    check("y sí al equipo", "Se le rompió el teléfono" in edu.get("/jovenes").text)

    # Le cargan lo que hizo. Un reto de hoy que él no tiene cómo entregar.
    edu.post("/asignar", data={"reto_id": str(reto_id), "fecha": date.today().isoformat(),
                               "alcance": "unidad"})
    with SesionLocal() as s:
        para_dictar = s.scalar(select(func.max(Asignacion.id)))

    check("su patrulla se entera al entrar", "Cargar lo que hizo" in joven.get("/hoy").text)
    check("y puede abrir la pantalla para cargarle",
          joven.get(f"/sin-telefono/{bruno_id}").status_code == 200)
    check("otra patrulla no", elisa.get(f"/sin-telefono/{bruno_id}").status_code == 404)
    check("un educador siempre puede", edu.get(f"/sin-telefono/{bruno_id}").status_code == 200)
    check("nadie carga entregas de quien sí tiene el teléfono",
          edu.get(f"/sin-telefono/{eli_id}").status_code == 404)
    check("ni se dicta a sí mismo", joven.get(f"/sin-telefono/{ana_id}").status_code == 404)

    dictado = ("Nos contó que ayudó a cortar la leña del fogón y que aprendió a "
               "apilarla para que se mantenga seca.")
    joven.post(f"/sin-telefono/{bruno_id}/reto/{para_dictar}", data={"texto": dictado})
    with SesionLocal() as s:
        cargada = s.scalar(
            select(Entrega).where(Entrega.asignacion_id == para_dictar,
                                  Entrega.joven_id == bruno_id)
        )
        check("la entrega queda a nombre de quien hizo el reto", cargada is not None)
        check("con la firma de quien la escribió", cargada.dictada_por_id == ana_id)
        check("los puntos van a su patrulla",
              cargada.patrulla_id == halcones_p.id and cargada.puntaje_otorgado > 0,
              cargada.puntaje_otorgado)
        # Compartir lo decide quien lo hizo y nadie más: el interruptor lo
        # aprieta él cuando recupere el teléfono.
        check("al muro no va: eso lo decide su dueño", not cargada.compartida)

    # La firma se muestra en los tres lados donde esa entrega se lee. Son tres
    # plantillas distintas y una rota no se nota hasta que alguien entra.
    check("él ve quién se la escribió",
          "lo cargó Ana" in companiera.get(f"/reto/{para_dictar}").text)
    check("y también en su lista de retos",
          "lo escribió Ana" in companiera.get("/mis-retos").text)
    check("el equipo la ve marcada entre las entregas",
          "la escribió Ana" in edu.get("/validaciones").text)

    # Cerrarla se nota en el momento, no al día siguiente: `vuelve_el` es el día
    # que lo tiene de vuelta y ese día ya cuenta.
    edu.post(f"/jovenes/{bruno_id}/pausa/{pausa_id}/cerrar")
    with SesionLocal() as s:
        cerrada = s.get(PausaSinTelefono, pausa_id)
        check("cerrar la pausa no la borra: le pone el día de vuelta",
              cerrada is not None and cerrada.vuelve_el == date.today())
        check("y queda firmado quién la cerró", cerrada.cerrada_por_id is not None)
        check("no sigue vigente el mismo día que se cierra",
              not cerrada.vigente_en(date.today()))
        halcones_f = next(
            f for f in servicio_puntajes.tablero_de_unidad(
                s, halcones_p.unidad_id, date.today())
            if f.patrulla.nombre == "Halcones"
        )
        check("vuelve a contar en el divisor en el momento",
              halcones_f.dividen == 2 and halcones_f.en_pausa == 0,
              f"{halcones_f.dividen} dividen, {halcones_f.en_pausa} en pausa")
    check("y ya nadie escribe en su nombre",
          joven.get(f"/sin-telefono/{bruno_id}").status_code == 404)
    check("la entrega que le habían cargado se queda",
          companiera.get(f"/reto/{para_dictar}").status_code == 200)

    # --- 10. Varios cargos a la vez ------------------------------------------
    #
    # En una patrulla de cinco no hay una persona por cargo, y la guía no lo
    # pide: son responsabilidades, no puestos.
    with SesionLocal() as s:
        tres = list(s.scalars(select(Cargo.id).order_by(Cargo.orden).limit(3)))
    for cargo_id in tres:
        joven.post(f"/patrulla/{ana_patrulla}/cargos",
                   data={"cargo_id": str(cargo_id), "joven_id": str(ana_id)})
    with SesionLocal() as s:
        abiertos_ana = s.scalar(
            select(func.count(PeriodoCargo.id)).where(
                PeriodoCargo.joven_id == ana_id, PeriodoCargo.hasta.is_(None)
            )
        )
        check("una misma persona puede tener varios cargos a la vez",
              abiertos_ana == 3, abiertos_ana)
    check("y la pantalla lo dice",
          "Se pueden tener varios a la vez" in joven.get(f"/patrulla/{ana_patrulla}").text)

    # --- todas las pantallas nuevas abren, para los dos roles ---------------
    #
    # Una plantilla rota no se nota hasta que alguien entra. Esto entra a todas.
    for ruta in ("/hoy", "/mis-cartas", "/mi-patrulla", f"/patrulla/{ana_patrulla}",
                 f"/patrulla/{ana_patrulla}/consejo/{consejo_id}", "/ideas",
                 "/muro", "/calendario", "/especialidades", "/bitacora",
                 "/mis-retos", "/tablero", "/libro-de-oro"):
        check(f"un joven abre {ruta}", joven.get(ruta).status_code == 200)

    for ruta in ("/panel", "/validaciones", "/retos", "/asignar", "/patrullas",
                 "/jovenes", "/cargos", "/ideas", "/especialidades", "/calendario",
                 f"/patrulla/{ana_patrulla}", f"/progresion/{ana_id}"):
        check(f"un educador abre {ruta}", edu.get(ruta).status_code == 200)

    # Y las que son de un solo rol siguen cerradas para el otro.
    check("un joven no entra al catálogo de cargos", joven.get("/cargos").status_code == 403)
    check("un joven no ve el catálogo de especialidades del equipo",
          "Sumar una especialidad" not in joven.get("/especialidades").text)

    # --- 14. Bajas de jóvenes y de patrullas ---------------------------------
    #
    # Mismo criterio que en el equipo —sin rastro se borra, con historia se
    # archiva— más una regla propia de las patrullas: con gente adentro, no.

    check("un joven no da de baja a nadie",
          joven.post(f"/jovenes/{ana_id}/baja").status_code == 403)

    # a) Una ficha vacía se borra de verdad.
    edu.post("/jovenes", data={"nombre": "Nunca Vino", "usuario_nuevo": "nuncavino",
                               "etapa": "pistas"})
    with SesionLocal() as s:
        vacia_id = s.scalar(select(Usuario.id).where(Usuario.usuario == "nuncavino"))
    check("una ficha recién creada ofrece borrado real",
          "Borrar ficha" in edu.get("/jovenes").text)
    edu.post(f"/jovenes/{vacia_id}/baja")
    with SesionLocal() as s:
        check("borrar una ficha sin nada adentro la saca de la base",
              s.get(Usuario, vacia_id) is None)

    # b) Ana tiene cartas, entregas y bitácora: se archiva, y sus puntos quedan.
    antes = next(f for f in edu.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("y una con progresión ofrece archivarla", "Dejó la Unidad" in edu.get("/jovenes").text)
    edu.post(f"/jovenes/{ana_id}/baja")
    with SesionLocal() as s:
        archivada = s.get(Usuario, ana_id)
        check("la ficha con historia no se borra", archivada is not None)
        check("se archiva", not archivada.activo)
        check("y su bitácora sigue entera",
              s.scalar(select(func.count(EntradaBitacora.id))
                       .where(EntradaBitacora.joven_id == ana_id)) > 0)
    despues = next(f for f in edu.get("/api/tablero").json() if f["patrulla"] == "Halcones")
    check("los puntos que le dio a su patrulla se quedan donde se ganaron",
          despues["puntos"] == antes["puntos"], f'{antes["puntos"]} → {despues["puntos"]}')
    check("pero deja de contarse como integrante",
          despues["integrantes"] == antes["integrantes"] - 1)
    check("su sesión se corta sola", joven.get("/hoy").url.path == "/ingresar")
    check("aparece en «ya no están»", "Ya no están en la Unidad" in edu.get("/jovenes").text)

    edu.post(f"/jovenes/{ana_id}/reincorporar")
    with SesionLocal() as s:
        check("reincorporar la devuelve a la Unidad", s.get(Usuario, ana_id).activo)
    check("y sus cartas siguen donde las dejó",
          "🃏" in edu.get("/jovenes").text and edu.get(f"/cartas-de/{ana_id}").status_code == 200)
    # Vuelve a entrar con la contraseña que ella misma se puso más arriba: la
    # baja le cortó la sesión pero no le tocó la contraseña. El resto del
    # recorrido sigue usando este cliente, así que tiene que quedar adentro.
    check("y vuelve a entrar con su contraseña de siempre",
          joven.post("/ingresar", data={"usuario": "ana", "clave": "linterna-77"}).url.path == "/hoy")

    # c) Patrullas: con gente adentro no se disuelve.
    r = edu.post(f"/patrullas/{ana_patrulla}/disolver")
    check("una patrulla con integrantes no se disuelve", r.status_code == 400, r.status_code)
    check("y el motivo dice a quiénes hay que mover",
          "Ana" in r.text and "Movelos" in r.text)
    check("la pantalla ni siquiera ofrece el botón",
          "primero movés sus" in edu.get("/patrullas").text)

    # d) Una patrulla nueva y vacía se borra de verdad.
    edu.post("/patrullas", data={"nombre": "Erratas", "lema": "", "color": "#123456"})
    with SesionLocal() as s:
        erratas_id = s.scalar(select(Patrulla.id).where(Patrulla.nombre == "Erratas"))
    check("una patrulla vacía y sin historia ofrece borrado real",
          "Borrar patrulla" in edu.get("/patrullas").text)
    edu.post(f"/patrullas/{erratas_id}/disolver")
    with SesionLocal() as s:
        check("y se borra de la base", s.get(Patrulla, erratas_id) is None)

    # e) Una patrulla vacía pero con Libro de Oro se desactiva y conserva todo.
    edu.post("/patrullas", data={"nombre": "Los Que Fueron", "lema": "", "color": "#654321"})
    with SesionLocal() as s:
        fueron_id = s.scalar(select(Patrulla.id).where(Patrulla.nombre == "Los Que Fueron"))
    edu.post(f"/libro-de-oro/{fueron_id}",
             data={"titulo": "Nuestro último campamento", "texto": "Estuvo bueno.",
                   "fecha": "2026-05-10"})
    edu.post(f"/patrullas/{fueron_id}/disolver")
    with SesionLocal() as s:
        disuelta = s.get(Patrulla, fueron_id)
        check("una patrulla con historia no se borra", disuelta is not None)
        check("se disuelve", not disuelta.activa)
    check("su Libro de Oro se sigue leyendo",
          "último campamento" in edu.get(f"/libro-de-oro/{fueron_id}").text)
    check("sale del tablero",
          not any(f["patrulla"] == "Los Que Fueron" for f in edu.get("/api/tablero").json()))
    check("y ya no se le puede asignar un reto",
          "Los Que Fueron" not in edu.get("/asignar").text)
    check("aparece entre las disueltas", "Disueltas" in edu.get("/patrullas").text)
    check("no se disuelve dos veces",
          edu.post(f"/patrullas/{fueron_id}/disolver").status_code == 400)

    edu.post(f"/patrullas/{fueron_id}/reabrir")
    with SesionLocal() as s:
        check("reabrirla la devuelve al juego", s.get(Patrulla, fueron_id).activa)
    check("y vuelve al tablero",
          any(f["patrulla"] == "Los Que Fueron" for f in edu.get("/api/tablero").json()))

    # --- 15. Cumpleaños ------------------------------------------------------
    #
    # El cálculo tiene dos bordes que se rompen solos: el salto de año —el 5 de
    # enero visto desde diciembre— y el 29 de febrero, que tres de cada cuatro
    # años no existe y hace estallar un `date()`.

    for nombre, nac, desde, esperado in (
        ("cumple hoy", date(2012, 8, 1), date(2026, 8, 1), date(2026, 8, 1)),
        ("ya pasó este año", date(2012, 3, 15), date(2026, 8, 1), date(2027, 3, 15)),
        ("de diciembre salta a enero", date(2012, 1, 5), date(2026, 12, 30), date(2027, 1, 5)),
        ("el 29/2 cae en su día si el año es bisiesto",
         date(2012, 2, 29), date(2028, 1, 10), date(2028, 2, 29)),
        ("y pasa al 1/3 si no lo es",
         date(2012, 2, 29), date(2026, 1, 10), date(2026, 3, 1)),
    ):
        check(nombre, cumpleanos._proxima_vez(nac, desde) == esperado,
              cumpleanos._proxima_vez(nac, desde))

    quince = Usuario(nombre="Prueba", nacimiento=date(2012, 8, 15))
    check("la edad no se adelanta un día", quince.edad_al(date(2026, 8, 14)) == 13)
    check("y cambia el día del cumpleaños", quince.edad_al(date(2026, 8, 15)) == 14)
    check("sin fecha cargada no hay edad", Usuario(nombre="X").edad_al(date(2026, 8, 1)) == None)

    # De punta a punta: cargar la fecha desde la pantalla y verla aparecer.
    hoy_es = retos.hoy()
    edu.post(f"/jovenes/{ana_id}", data={"patrulla_id": str(ana_patrulla),
                                         "nacimiento": hoy_es.replace(year=2012).isoformat()})
    with SesionLocal() as s:
        check("el cumpleaños se guarda desde la ficha",
              s.get(Usuario, ana_id).nacimiento == hoy_es.replace(year=2012))
    check("y la ficha muestra la edad", "🎂" in edu.get("/jovenes").text)
    check("el panel avisa que cumple hoy", "Cumpleaños del mes" in edu.get("/panel").text)
    check("y el joven lo ve sin la edad",
          "Hoy cumple años Ana" in joven.get("/hoy").text
          and "cumple 14" not in joven.get("/hoy").text)

    # Guardar vacío lo borra: el dato es opcional y tiene que poder sacarse.
    edu.post(f"/jovenes/{ana_id}", data={"patrulla_id": str(ana_patrulla), "nacimiento": ""})
    with SesionLocal() as s:
        check("dejarlo vacío lo borra", s.get(Usuario, ana_id).nacimiento is None)
    check("y desaparece de los cumpleaños", "Cumpleaños del mes" not in edu.get("/panel").text)

    # Una fecha imposible no se guarda en vez de romper la pantalla.
    edu.post(f"/jovenes/{ana_id}", data={"patrulla_id": str(ana_patrulla),
                                         "nacimiento": "2099-01-01"})
    with SesionLocal() as s:
        check("una fecha futura se descarta", s.get(Usuario, ana_id).nacimiento is None)
    edu.post(f"/jovenes/{ana_id}", data={"patrulla_id": str(ana_patrulla),
                                         "nacimiento": "cualquier cosa"})
    with SesionLocal() as s:
        check("y un texto que no es fecha, también", s.get(Usuario, ana_id).nacimiento is None)

    # El equipo también cumple años, y se carga desde su propia pantalla.
    edu.post(f"/educadores/{educador_id}/nacimiento", data={"nacimiento": "1990-06-20"})
    with SesionLocal() as s:
        check("un educador también tiene cumpleaños",
              s.get(Usuario, educador_id).nacimiento == date(1990, 6, 20))
    check("y se ve en su ficha", "20/06" in edu.get("/educadores").text)

    print()
    if fallos:
        print(f"{len(fallos)} verificaciones fallaron: {fallos}")
        return 1
    print("Circuito completo funcionando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
