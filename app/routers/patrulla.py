"""La patrulla por dentro: identidad, cargos, Consejo y acuerdos (cap. 4).

Todo esto lo tocan las y los jóvenes, no el educador. Es a propósito: «Puede
haber patrullas sin Unidad, pero no Unidad sin patrullas», y la guía pide que el
equipo de educadores acompañe «sin que interfiera "dentro" de la patrulla».

El educador entra a mirar y a ayudar —ve las patrullas de su Unidad y puede
escribir en ellas— pero no hay nada acá que solo él pueda hacer.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, usuario_actual
from app.models import (
    ROL_JOVEN,
    Acuerdo,
    Cargo,
    ConsejoPatrulla,
    Patrulla,
    PeriodoCargo,
    Usuario,
)
from app.servicios import medios, pausas, progresion, retos
from app.servicios import patrulla as vida

router = APIRouter()


def _patrulla_visible(sesion: Session, patrulla_id: int, usuario: Usuario) -> Patrulla:
    """La propia, o cualquiera de la Unidad si es educador. Otra patrulla, no.

    Mismo criterio que el Libro de Oro: lo que pasa adentro de una patrulla es de
    esa patrulla.
    """
    patrulla = sesion.get(Patrulla, patrulla_id)
    if patrulla is None or patrulla.unidad_id != usuario.unidad_id:
        raise HTTPException(404, "Esa patrulla no existe.")
    if not usuario.es_educador and patrulla.id != usuario.patrulla_id:
        raise HTTPException(404, "Esa patrulla no existe.")
    return patrulla


def _integrantes(sesion: Session, patrulla_id: int) -> list[Usuario]:
    return list(
        sesion.scalars(
            select(Usuario)
            .where(
                Usuario.patrulla_id == patrulla_id,
                Usuario.rol == ROL_JOVEN,
                Usuario.activo.is_(True),
            )
            .order_by(Usuario.nombre)
        )
    )


def _fecha(texto: str, por_defecto: date | None = None) -> date | None:
    try:
        return date.fromisoformat(texto.strip())
    except (AttributeError, ValueError):
        return por_defecto


@router.get("/mi-patrulla")
def mi_patrulla(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Atajo a la patrulla propia."""
    if usuario.es_educador:
        return redirigir("/patrullas")
    if usuario.patrulla_id is None:
        return render(request, "joven/mi_patrulla.html", usuario=usuario, patrulla=None)
    return redirigir(f"/patrulla/{usuario.patrulla_id}")


@router.get("/patrulla/{patrulla_id}")
def ver_patrulla(
    patrulla_id: int,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Quiénes son, quién tiene qué cargo, qué decidieron y a qué se comprometieron."""
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    integrantes = _integrantes(sesion, patrulla_id)
    hoy = retos.hoy()

    return render(
        request,
        "joven/mi_patrulla.html",
        usuario=usuario,
        patrulla=patrulla,
        integrantes=[(j, progresion.cartas_elegidas(sesion, j)) for j in integrantes],
        # Quién está sin teléfono. Acá se dice que lo está y nunca por qué: el
        # motivo lo escribió un educador y se queda del lado del equipo (ver
        # `models.PausaSinTelefono`). Lo que la patrulla necesita saber es que a
        # esa persona hay que preguntarle qué hizo y cargárselo.
        en_pausa=pausas.vigentes_de(sesion, [j.id for j in integrantes], hoy),
        cargos=vida.catalogo(sesion, patrulla.unidad_id),
        porta=vida.cargos_por_joven(sesion, patrulla_id),
        abiertos=vida.periodos_abiertos(sesion, patrulla_id),
        consejos=vida.consejos_de(sesion, patrulla_id),
        acuerdos=vida.acuerdos_de(sesion, patrulla_id),
        resumen=vida.resumen(sesion, patrulla_id, integrantes),
        hoy=hoy,
    )


# --- Identidad (cap. 5) -------------------------------------------------------


@router.post("/patrulla/{patrulla_id}/identidad")
def guardar_identidad(
    patrulla_id: int,
    lema: str = Form(""),
    grito: str = Form(""),
    emblema: str = Form(""),
    historia: str = Form(""),
    fundada_en: str = Form(""),
    banderin: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """El nombre, el grito, el banderín: la identidad la escribe la patrulla.

    El nombre no está acá y es a propósito: cambiar el nombre de una patrulla es
    una decisión de la Unidad, no un campo de texto. Eso sigue en `/patrullas`,
    del lado del educador.
    """
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)

    patrulla.lema = lema.strip()[:200]
    patrulla.grito = grito.strip()
    # Un emoji, no una parrafada: es lo que entra al lado del nombre.
    patrulla.emblema = emblema.strip()[:10]
    patrulla.historia = historia.strip()
    patrulla.fundada_en = _fecha(fundada_en)

    if banderin is not None and banderin.filename:
        try:
            nombre = medios.guardar_foto(banderin.filename, medios.leer_subida(banderin))
        except medios.MedioInvalido as error:
            raise HTTPException(400, str(error)) from error
        # El banderín viejo se va del disco: hay uno solo por patrulla.
        medios.borrar_foto(patrulla.archivo_banderin)
        patrulla.archivo_banderin = nombre

    sesion.commit()
    return redirigir(f"/patrulla/{patrulla.id}#identidad")


# --- Cargos -------------------------------------------------------------------


@router.post("/patrulla/{patrulla_id}/cargos")
def tomar_cargo(
    patrulla_id: int,
    cargo_id: int = Form(...),
    joven_id: int = Form(...),
    desde: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Alguien toma un cargo. Lo decide la patrulla, así que lo carga la patrulla."""
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    cargo = sesion.get(Cargo, cargo_id)
    if cargo is None or cargo.unidad_id != patrulla.unidad_id:
        raise HTTPException(404, "Ese cargo no existe en tu Unidad.")

    joven = sesion.get(Usuario, joven_id)
    if joven is None or joven.patrulla_id != patrulla.id or joven.rol != ROL_JOVEN:
        raise HTTPException(404, "Esa persona no está en esta patrulla.")

    vida.asumir(sesion, cargo, joven, _fecha(desde, retos.hoy()) or retos.hoy())
    sesion.commit()
    return redirigir(f"/patrulla/{patrulla.id}#cargos")


@router.post("/patrulla/{patrulla_id}/cargos/{periodo_id}/cerrar")
def cerrar_cargo(
    patrulla_id: int,
    periodo_id: int,
    cumplido: bool = Form(False),
    hasta: str = Form(""),
    nota: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """El Consejo cierra un período y dice cómo le fue.

    Que se marque cumplido no es un premio: es lo que después cuenta para la
    etapa, y por eso lo decide la patrulla que lo vio trabajar.
    """
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    periodo = sesion.get(PeriodoCargo, periodo_id)
    if periodo is None or periodo.patrulla_id != patrulla.id:
        raise HTTPException(404, "Ese período no existe.")

    vida.cerrar(periodo, _fecha(hasta, retos.hoy()) or retos.hoy(), cumplido, nota)
    sesion.commit()
    return redirigir(f"/patrulla/{patrulla.id}#cargos")


# --- Consejo de Patrulla ------------------------------------------------------


@router.post("/patrulla/{patrulla_id}/consejo")
def anotar_consejo(
    patrulla_id: int,
    fecha: str = Form(""),
    temas: str = Form(""),
    # Una casilla por integrante: llegan repetidas con el mismo nombre.
    presente: list[int] = Form([]),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Un acta de Consejo de Patrulla."""
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    if not temas.strip():
        raise HTTPException(400, "Contá de qué hablaron en el Consejo.")

    consejo = vida.anotar_consejo(
        sesion,
        patrulla.id,
        _fecha(fecha, retos.hoy()) or retos.hoy(),
        temas,
        usuario,
        presente,
    )
    sesion.commit()
    return redirigir(f"/patrulla/{patrulla.id}/consejo/{consejo.id}")


@router.get("/patrulla/{patrulla_id}/consejo/{consejo_id}")
def ver_consejo(
    patrulla_id: int,
    consejo_id: int,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    consejo = sesion.get(ConsejoPatrulla, consejo_id)
    if consejo is None or consejo.patrulla_id != patrulla.id:
        raise HTTPException(404, "Ese Consejo no existe.")

    return render(
        request,
        "joven/consejo.html",
        usuario=usuario,
        patrulla=patrulla,
        consejo=consejo,
        integrantes=_integrantes(sesion, patrulla.id),
        acuerdos=[a for a in consejo.acuerdos],
        hoy=retos.hoy(),
    )


# --- Acuerdos -----------------------------------------------------------------


@router.post("/patrulla/{patrulla_id}/acuerdos")
def anotar_acuerdo(
    patrulla_id: int,
    texto: str = Form(...),
    responsable_id: str = Form(""),
    para_cuando: str = Form(""),
    consejo_id: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Algo que la patrulla decidió hacer, con nombre y fecha si corresponde."""
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    if not texto.strip():
        raise HTTPException(400, "Escribí qué se acordó.")

    responsable = None
    if responsable_id.strip().isdigit():
        candidato = sesion.get(Usuario, int(responsable_id))
        if candidato is not None and candidato.patrulla_id == patrulla.id:
            responsable = candidato

    consejo = None
    if consejo_id.strip().isdigit():
        candidato = sesion.get(ConsejoPatrulla, int(consejo_id))
        if candidato is not None and candidato.patrulla_id == patrulla.id:
            consejo = candidato

    sesion.add(
        Acuerdo(
            consejo_id=consejo.id if consejo else None,
            patrulla_id=patrulla.id,
            texto=texto.strip(),
            responsable_id=responsable.id if responsable else None,
            para_cuando=_fecha(para_cuando),
        )
    )
    sesion.commit()
    if consejo is not None:
        return redirigir(f"/patrulla/{patrulla.id}/consejo/{consejo.id}#acuerdos")
    return redirigir(f"/patrulla/{patrulla.id}#acuerdos")


@router.post("/acuerdos/{acuerdo_id}")
def resolver_acuerdo(
    acuerdo_id: int,
    cumplido: bool = Form(False),
    volver: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Dar por hecho un acuerdo, o volver atrás.

    Lo puede marcar cualquiera de la patrulla y no solo el responsable: el
    acuerdo es del grupo, y el que lo hizo bien no siempre es el que se acuerda
    de venir a tildarlo.
    """
    acuerdo = sesion.get(Acuerdo, acuerdo_id)
    if acuerdo is None:
        raise HTTPException(404, "Ese acuerdo no existe.")
    _patrulla_visible(sesion, acuerdo.patrulla_id, usuario)

    acuerdo.cumplido = cumplido
    acuerdo.cumplido_en = datetime.now(timezone.utc) if cumplido else None
    sesion.commit()

    if volver == "hoy":
        return redirigir("/hoy#acuerdos")
    if acuerdo.consejo_id:
        return redirigir(f"/patrulla/{acuerdo.patrulla_id}/consejo/{acuerdo.consejo_id}#acuerdos")
    return redirigir(f"/patrulla/{acuerdo.patrulla_id}#acuerdos")
