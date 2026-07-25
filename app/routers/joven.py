"""Lo que ve y hace un joven protagonista."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.dependencias import redirigir, render, solo_joven, usuario_actual
from app.models import (
    ALCANCE_JOVEN,
    ALCANCE_PATRULLA,
    ESTADO_APROBADA,
    ROL_JOVEN,
    Area,
    Asignacion,
    AvanceDesafio,
    Competencia,
    CompetenciaElegida,
    Desafio,
    Entrega,
    EntradaBitacora,
    EntradaLibroOro,
    Patrulla,
    Usuario,
)
from app.servicios import medios, progresion, puntajes, retos
from app.servicios.validacion import ContextoValidacion, obtener_validador

router = APIRouter()

MIN_CARTAS = 12
MAX_CARTAS = 14


def _guardar_foto(archivo: UploadFile) -> str:
    """Toda foto pasa por el servicio de medios: se comprime antes de ir a disco."""
    try:
        return medios.guardar_foto(archivo.filename, archivo.file.read())
    except medios.MedioInvalido as error:
        raise HTTPException(400, str(error)) from error


@router.get("/hoy")
def hoy(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        return render(request, "joven/hoy.html", usuario=usuario, asignaciones=[], fecha=retos.hoy())

    fecha = retos.hoy()
    retos.asegurar_reto_del_dia(sesion, usuario.unidad_id, fecha)

    asignaciones = retos.asignaciones_del_dia(sesion, usuario, fecha)
    entregas = retos.entregas_por_asignacion(sesion, usuario, asignaciones)

    fila_patrulla = None
    if usuario.patrulla_id is not None:
        tablero = puntajes.tablero_de_unidad(sesion, usuario.unidad_id, fecha)
        fila_patrulla = next(
            (f for f in tablero if f.patrulla.id == usuario.patrulla_id), None
        )

    return render(
        request,
        "joven/hoy.html",
        usuario=usuario,
        fecha=fecha,
        asignaciones=asignaciones,
        entregas=entregas,
        fila_patrulla=fila_patrulla,
    )


@router.get("/reto/{asignacion_id}")
def ver_reto(
    asignacion_id: int,
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    asignacion = _asignacion_visible(sesion, asignacion_id, usuario)
    entrega = sesion.scalar(
        select(Entrega).where(
            Entrega.asignacion_id == asignacion.id, Entrega.joven_id == usuario.id
        )
    )
    return render(
        request,
        "joven/reto.html",
        usuario=usuario,
        asignacion=asignacion,
        entrega=entrega,
    )


@router.post("/reto/{asignacion_id}")
def entregar_reto(
    asignacion_id: int,
    request: Request,
    texto: str = Form(""),
    foto: UploadFile | None = File(None),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    asignacion = _asignacion_visible(sesion, asignacion_id, usuario)

    ya_entregada = sesion.scalar(
        select(Entrega).where(
            Entrega.asignacion_id == asignacion.id, Entrega.joven_id == usuario.id
        )
    )
    if ya_entregada is not None and ya_entregada.estado == ESTADO_APROBADA:
        return redirigir(f"/reto/{asignacion.id}")

    nombre_foto = None
    if foto is not None and foto.filename:
        nombre_foto = _guardar_foto(foto)

    entrega = ya_entregada or Entrega(
        asignacion_id=asignacion.id,
        joven_id=usuario.id,
        patrulla_id=usuario.patrulla_id,
    )
    entrega.texto = texto.strip()
    if nombre_foto:
        entrega.archivo_foto = nombre_foto
    entrega.enviada_en = datetime.now(timezone.utc)
    entrega.patrulla_id = usuario.patrulla_id

    reto = asignacion.reto
    desafio = reto.desafio
    competencia = desafio.competencia if desafio else None
    resultado = obtener_validador().validar(
        ContextoValidacion(
            reto_titulo=reto.titulo,
            reto_consigna=reto.consigna,
            texto_evidencia=entrega.texto,
            tiene_foto=entrega.archivo_foto is not None,
            pide_texto=reto.pide_texto,
            pide_foto=reto.pide_foto,
            desafio_texto=desafio.texto if desafio else None,
            competencia_titulo=competencia.titulo if competencia else None,
            area_nombre=reto.area.nombre if reto.area else None,
        )
    )

    entrega.estado = resultado.estado
    entrega.devolucion = resultado.devolucion
    entrega.validador = resultado.validador
    entrega.validada_en = datetime.now(timezone.utc) if resultado.estado == ESTADO_APROBADA else None
    entrega.puntaje_otorgado = reto.puntaje if resultado.estado == ESTADO_APROBADA else 0

    sesion.add(entrega)
    sesion.commit()
    return redirigir(f"/reto/{asignacion.id}")


@router.get("/mis-retos")
def mis_retos(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    entregas = list(
        sesion.scalars(
            select(Entrega)
            .where(Entrega.joven_id == usuario.id)
            .order_by(Entrega.enviada_en.desc())
        )
    )
    return render(request, "joven/mis_retos.html", usuario=usuario, entregas=entregas)


@router.get("/bitacora")
def bitacora(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    entradas = list(
        sesion.scalars(
            select(EntradaBitacora)
            .where(EntradaBitacora.joven_id == usuario.id)
            .order_by(EntradaBitacora.creada_en.desc())
        )
    )
    return render(request, "joven/bitacora.html", usuario=usuario, entradas=entradas)


@router.post("/bitacora")
def escribir_bitacora(
    titulo: str = Form(""),
    texto: str = Form(...),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    if texto.strip():
        sesion.add(
            EntradaBitacora(
                joven_id=usuario.id, titulo=titulo.strip(), texto=texto.strip()
            )
        )
        sesion.commit()
    return redirigir("/bitacora")


@router.get("/mis-cartas")
def mis_cartas(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    areas = list(sesion.scalars(select(Area).order_by(Area.id)))
    competencias = list(sesion.scalars(select(Competencia).order_by(Competencia.numero)))
    avances = progresion.cartas_elegidas(sesion, usuario)
    return render(
        request,
        "joven/mis_cartas.html",
        usuario=usuario,
        areas=areas,
        competencias=competencias,
        avances=avances,
        elegidas={a.elegida.competencia_id: a.elegida for a in avances},
        min_cartas=MIN_CARTAS,
        max_cartas=MAX_CARTAS,
        total_cartas=len(competencias),
    )


@router.post("/mis-cartas/{competencia_id}")
def alternar_carta(
    competencia_id: int,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    # Vuelve al ancla de la carta: elegir la número 47 no debería devolverte
    # al principio de una lista de 53.
    destino = f"/mis-cartas#carta-{competencia_id}"

    existente = sesion.scalar(
        select(CompetenciaElegida).where(
            CompetenciaElegida.joven_id == usuario.id,
            CompetenciaElegida.competencia_id == competencia_id,
            CompetenciaElegida.etapa == usuario.etapa,
        )
    )
    if existente is not None:
        # Una competencia ya lograda no se desmarca sola: eso se conversa.
        # Lo marcado dentro de la carta no se borra (ver AvanceDesafio): si la
        # vuelve a elegir, su trabajo sigue estando.
        if not existente.lograda:
            sesion.delete(existente)
            sesion.commit()
        return redirigir(destino)

    if sesion.get(Competencia, competencia_id) is None:
        raise HTTPException(404, "Esa carta no existe.")

    sesion.add(
        CompetenciaElegida(
            joven_id=usuario.id, competencia_id=competencia_id, etapa=usuario.etapa
        )
    )
    sesion.commit()
    return redirigir(destino)


@router.get("/mis-cartas/{competencia_id}")
def trabajar_carta(
    competencia_id: int,
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """La página de trabajo de una carta: marcar desafíos y comentarlos."""
    competencia = sesion.get(Competencia, competencia_id)
    if competencia is None:
        raise HTTPException(404, "Esa carta no existe.")

    elegida = sesion.scalar(
        select(CompetenciaElegida).where(
            CompetenciaElegida.joven_id == usuario.id,
            CompetenciaElegida.competencia_id == competencia_id,
            CompetenciaElegida.etapa == usuario.etapa,
        )
    )
    marcas = progresion.marcas_de(sesion, usuario)
    return render(
        request,
        "joven/carta.html",
        usuario=usuario,
        competencia=competencia,
        desafios=progresion.desafios_de(sesion, competencia_id),
        elegida=elegida,
        marcas=marcas,
        avance=progresion.avance_de_carta(elegida, marcas) if elegida else None,
    )


@router.post("/mis-cartas/{competencia_id}/desafios/{desafio_id}")
def marcar_desafio(
    competencia_id: int,
    desafio_id: int,
    hecho: bool = Form(False),
    comentario: str = Form(""),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    desafio = sesion.get(Desafio, desafio_id)
    if desafio is None or desafio.competencia_id != competencia_id:
        raise HTTPException(404, "Ese desafío no existe.")

    elegida = sesion.scalar(
        select(CompetenciaElegida.id).where(
            CompetenciaElegida.joven_id == usuario.id,
            CompetenciaElegida.competencia_id == competencia_id,
            CompetenciaElegida.etapa == usuario.etapa,
        )
    )
    if elegida is None:
        raise HTTPException(400, "Primero elegí esta carta para tu etapa.")

    avance = sesion.scalar(
        select(AvanceDesafio).where(
            AvanceDesafio.joven_id == usuario.id,
            AvanceDesafio.desafio_id == desafio_id,
            AvanceDesafio.etapa == usuario.etapa,
        )
    )
    if avance is None:
        avance = AvanceDesafio(
            joven_id=usuario.id, desafio_id=desafio_id, etapa=usuario.etapa
        )
        sesion.add(avance)
    avance.hecho = hecho
    avance.comentario = comentario.strip()
    sesion.commit()
    return redirigir(f"/mis-cartas/{competencia_id}#desafio-{desafio_id}")


@router.get("/mi-patrulla")
def mi_patrulla(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """Quiénes son y en qué andan. Por nombre, nunca ordenados por avance."""
    if usuario.patrulla_id is None:
        return render(request, "joven/mi_patrulla.html", usuario=usuario, integrantes=[])

    integrantes = list(
        sesion.scalars(
            select(Usuario)
            .where(
                Usuario.patrulla_id == usuario.patrulla_id,
                Usuario.rol == ROL_JOVEN,
                Usuario.activo.is_(True),
            )
            .order_by(Usuario.nombre)
        )
    )
    return render(
        request,
        "joven/mi_patrulla.html",
        usuario=usuario,
        integrantes=[(j, progresion.cartas_elegidas(sesion, j)) for j in integrantes],
    )


@router.get("/cartas-de/{joven_id}")
def cartas_de(
    joven_id: int,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """La progresión de un joven, de solo lectura.

    La miran tres personas distintas: quien la escribió, su patrulla —el Consejo
    de Patrulla acompaña la progresión de sus integrantes (cap. 4)— y el equipo
    de educadores. Es una sola página porque es una sola conversación.
    """
    joven = sesion.get(Usuario, joven_id)
    if joven is None or not _puede_ver_progresion(usuario, joven):
        raise HTTPException(404, "Esa persona no está en tu Unidad.")

    return render(
        request,
        "cartas_de.html",
        usuario=usuario,
        joven=joven,
        avances=progresion.cartas_elegidas(sesion, joven),
        marcas=progresion.marcas_de(sesion, joven),
        propia=joven.id == usuario.id,
        min_cartas=MIN_CARTAS,
        max_cartas=MAX_CARTAS,
    )


# --- Libro de Oro de la Patrulla ---------------------------------------------


@router.get("/libro-de-oro")
def mi_libro_de_oro(
    usuario: Usuario = Depends(usuario_actual),
):
    """Atajo: te lleva al libro de tu patrulla."""
    if usuario.es_educador:
        return redirigir("/patrullas")
    if usuario.patrulla_id is None:
        raise HTTPException(404, "Todavía no estás en una patrulla.")
    return redirigir(f"/libro-de-oro/{usuario.patrulla_id}")


@router.get("/libro-de-oro/{patrulla_id}")
def libro_de_oro(
    patrulla_id: int,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """El Libro de Oro: lo que la patrulla quiere recordar.

    Lo escribe la patrulla y lo lee la patrulla, más el equipo de educadores.
    Otra patrulla no entra: el libro es de quienes lo vivieron.
    """
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    entradas = list(
        sesion.scalars(
            select(EntradaLibroOro)
            .where(EntradaLibroOro.patrulla_id == patrulla.id)
            .order_by(EntradaLibroOro.fecha.desc(), EntradaLibroOro.id.desc())
        )
    )
    return render(
        request,
        "libro_oro.html",
        usuario=usuario,
        patrulla=patrulla,
        entradas=entradas,
        hoy=retos.hoy(),
        con_foto=sum(1 for e in entradas if e.archivo_foto),
        con_video=sum(1 for e in entradas if e.video_id),
    )


@router.post("/libro-de-oro/{patrulla_id}")
def escribir_libro_de_oro(
    patrulla_id: int,
    titulo: str = Form(...),
    texto: str = Form(""),
    fecha: str = Form(""),
    video: str = Form(""),
    foto: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    patrulla = _patrulla_visible(sesion, patrulla_id, usuario)
    if not titulo.strip():
        raise HTTPException(400, "Ponele un título a la página.")

    try:
        enlace = medios.leer_video(video)
    except medios.MedioInvalido as error:
        raise HTTPException(400, str(error)) from error

    nombre_foto = None
    if foto is not None and foto.filename:
        nombre_foto = _guardar_foto(foto)

    sesion.add(
        EntradaLibroOro(
            patrulla_id=patrulla.id,
            autor_id=usuario.id,
            titulo=titulo.strip(),
            texto=texto.strip(),
            archivo_foto=nombre_foto,
            video_servicio=enlace.servicio if enlace else None,
            video_id=enlace.identificador if enlace else None,
            fecha=date.fromisoformat(fecha) if fecha.strip() else retos.hoy(),
        )
    )
    sesion.commit()
    return redirigir(f"/libro-de-oro/{patrulla.id}")


@router.post("/libro-de-oro/{patrulla_id}/{entrada_id}/borrar")
def borrar_del_libro(
    patrulla_id: int,
    entrada_id: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Borra una página. Puede quien la escribió, o un educador."""
    _patrulla_visible(sesion, patrulla_id, usuario)
    entrada = sesion.get(EntradaLibroOro, entrada_id)
    if entrada is None or entrada.patrulla_id != patrulla_id:
        raise HTTPException(404, "Esa página no existe.")
    if not usuario.es_educador and entrada.autor_id != usuario.id:
        raise HTTPException(403, "Esta página la escribió otra persona.")

    medios.borrar_foto(entrada.archivo_foto)
    sesion.delete(entrada)
    sesion.commit()
    return redirigir(f"/libro-de-oro/{patrulla_id}")


def _patrulla_visible(sesion: Session, patrulla_id: int, usuario: Usuario) -> Patrulla:
    patrulla = sesion.get(Patrulla, patrulla_id)
    if patrulla is None or patrulla.unidad_id != usuario.unidad_id:
        raise HTTPException(404, "Esa patrulla no existe.")
    if not usuario.es_educador and patrulla.id != usuario.patrulla_id:
        raise HTTPException(404, "Esa patrulla no existe.")
    return patrulla


def _puede_ver_progresion(mirador: Usuario, joven: Usuario) -> bool:
    if joven.rol != ROL_JOVEN or mirador.unidad_id is None:
        return False
    if joven.unidad_id != mirador.unidad_id:
        return False
    if mirador.es_educador or mirador.id == joven.id:
        return True
    return joven.patrulla_id is not None and joven.patrulla_id == mirador.patrulla_id


@router.get("/tablero")
def tablero(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        return render(request, "tablero.html", usuario=usuario, filas=[])
    filas = puntajes.tablero_de_unidad(sesion, usuario.unidad_id, retos.hoy())
    return render(request, "tablero.html", usuario=usuario, filas=filas)


def _asignacion_visible(sesion: Session, asignacion_id: int, usuario: Usuario) -> Asignacion:
    asignacion = sesion.get(Asignacion, asignacion_id)
    if asignacion is None or asignacion.unidad_id != usuario.unidad_id:
        raise HTTPException(404, "Ese reto no existe.")
    if asignacion.alcance == ALCANCE_JOVEN and asignacion.joven_id != usuario.id:
        raise HTTPException(404, "Ese reto no existe.")
    if asignacion.alcance == ALCANCE_PATRULLA and asignacion.patrulla_id != usuario.patrulla_id:
        raise HTTPException(404, "Ese reto no existe.")
    return asignacion
