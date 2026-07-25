"""Panel del equipo de educadoras y educadores."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PUNTAJE_POR_DEFECTO
from app.db import obtener_sesion
from app.dependencias import redirigir, render, solo_educador
from app.models import (
    ALCANCE_JOVEN,
    ALCANCE_PATRULLA,
    ALCANCE_UNIDAD,
    ESTADO_APROBADA,
    ESTADO_RECHAZADA,
    ESTADO_REVISION,
    ETAPAS,
    ROL_JOVEN,
    TIPO_CARTA,
    TIPO_PERSONALIZADO,
    Area,
    Asignacion,
    Competencia,
    Desafio,
    Entrega,
    Patrulla,
    Reto,
    Usuario,
)
from app.seguridad import hashear_clave
from app.servicios import medios, puntajes, retos

router = APIRouter()


def _unidad_de(educador: Usuario) -> int:
    if educador.unidad_id is None:
        raise HTTPException(400, "Tu usuario no está asociado a ninguna Unidad.")
    return educador.unidad_id


@router.get("/panel")
def panel(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    fecha = retos.hoy()

    pendientes = sesion.scalar(
        select(func.count(Entrega.id))
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .where(Asignacion.unidad_id == unidad_id, Entrega.estado == ESTADO_REVISION)
    )
    asignaciones_hoy = list(
        sesion.scalars(
            select(Asignacion)
            .where(Asignacion.unidad_id == unidad_id, Asignacion.fecha == fecha)
            .order_by(Asignacion.id)
        )
    )
    jovenes_sin_patrulla = sesion.scalar(
        select(func.count(Usuario.id)).where(
            Usuario.unidad_id == unidad_id,
            Usuario.rol == ROL_JOVEN,
            Usuario.patrulla_id.is_(None),
            Usuario.activo.is_(True),
        )
    )

    fotos, bytes_usados = medios.espacio_usado()
    return render(
        request,
        "educador/panel.html",
        usuario=usuario,
        fecha=fecha,
        pendientes=pendientes or 0,
        asignaciones_hoy=asignaciones_hoy,
        jovenes_sin_patrulla=jovenes_sin_patrulla or 0,
        filas=puntajes.tablero_de_unidad(sesion, unidad_id, fecha),
        fotos_guardadas=fotos,
        megas_usados=round(bytes_usados / (1024 * 1024), 1),
    )


# --- Validación --------------------------------------------------------------


@router.get("/validaciones")
def validaciones(
    request: Request,
    estado: str = ESTADO_REVISION,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    consulta = (
        select(Entrega)
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .where(Asignacion.unidad_id == unidad_id)
        .order_by(Entrega.enviada_en.desc())
    )
    if estado != "todas":
        consulta = consulta.where(Entrega.estado == estado)

    return render(
        request,
        "educador/validaciones.html",
        usuario=usuario,
        entregas=list(sesion.scalars(consulta)),
        estado=estado,
    )


@router.post("/validaciones/{entrega_id}")
def resolver_validacion(
    entrega_id: int,
    decision: str = Form(...),
    devolucion: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    entrega = sesion.get(Entrega, entrega_id)
    if entrega is None or entrega.asignacion.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Esa entrega no existe.")

    if decision == "aprobar":
        entrega.estado = ESTADO_APROBADA
        entrega.puntaje_otorgado = entrega.asignacion.reto.puntaje
    elif decision == "rechazar":
        entrega.estado = ESTADO_RECHAZADA
        entrega.puntaje_otorgado = 0
    elif decision == "devolver":
        entrega.estado = ESTADO_REVISION
        entrega.puntaje_otorgado = 0
    else:
        raise HTTPException(400, "Decisión desconocida.")

    entrega.devolucion = devolucion.strip() or entrega.devolucion
    entrega.validador = "educador"
    entrega.validada_por_id = usuario.id
    entrega.validada_en = datetime.now(timezone.utc)
    sesion.commit()
    return redirigir("/validaciones")


# --- Retos -------------------------------------------------------------------


@router.get("/retos")
def listar_retos(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    propios = list(
        sesion.scalars(
            select(Reto)
            .where(Reto.unidad_id == unidad_id, Reto.activo.is_(True))
            .order_by(Reto.creado_en.desc())
        )
    )
    return render(
        request,
        "educador/retos.html",
        usuario=usuario,
        retos=propios,
        areas=list(sesion.scalars(select(Area).order_by(Area.id))),
        competencias=list(sesion.scalars(select(Competencia).order_by(Competencia.numero))),
        puntaje_defecto=PUNTAJE_POR_DEFECTO,
    )


@router.post("/retos")
def crear_reto(
    titulo: str = Form(...),
    consigna: str = Form(...),
    desafio_id: str = Form(""),
    area_id: str = Form(""),
    puntaje: int = Form(PUNTAJE_POR_DEFECTO),
    pide_texto: bool = Form(False),
    pide_foto: bool = Form(False),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)

    desafio = sesion.get(Desafio, int(desafio_id)) if desafio_id.strip() else None
    area = None
    if desafio is not None:
        area = desafio.competencia.area
    elif area_id.strip():
        area = sesion.get(Area, int(area_id))

    sesion.add(
        Reto(
            titulo=titulo.strip(),
            consigna=consigna.strip(),
            tipo=TIPO_CARTA if desafio is not None else TIPO_PERSONALIZADO,
            desafio_id=desafio.id if desafio else None,
            area_id=area.id if area else None,
            puntaje=max(0, puntaje),
            pide_texto=pide_texto,
            pide_foto=pide_foto,
            unidad_id=unidad_id,
            creado_por_id=usuario.id,
        )
    )
    sesion.commit()
    return redirigir("/retos")


@router.post("/retos/{reto_id}/archivar")
def archivar_reto(
    reto_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    reto = sesion.get(Reto, reto_id)
    if reto is None or reto.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Ese reto no existe.")
    reto.activo = False
    sesion.commit()
    return redirigir("/retos")


# --- Asignación --------------------------------------------------------------


@router.get("/asignar")
def form_asignar(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    return render(
        request,
        "educador/asignar.html",
        usuario=usuario,
        hoy=retos.hoy(),
        retos=list(
            sesion.scalars(
                select(Reto)
                .where(Reto.unidad_id == unidad_id, Reto.activo.is_(True))
                .order_by(Reto.titulo)
            )
        ),
        patrullas=list(
            sesion.scalars(
                select(Patrulla)
                .where(Patrulla.unidad_id == unidad_id, Patrulla.activa.is_(True))
                .order_by(Patrulla.nombre)
            )
        ),
        jovenes=list(
            sesion.scalars(
                select(Usuario)
                .where(
                    Usuario.unidad_id == unidad_id,
                    Usuario.rol == ROL_JOVEN,
                    Usuario.activo.is_(True),
                )
                .order_by(Usuario.nombre)
            )
        ),
        proximas=list(
            sesion.scalars(
                select(Asignacion)
                .where(Asignacion.unidad_id == unidad_id, Asignacion.fecha >= retos.hoy())
                .order_by(Asignacion.fecha)
            )
        ),
    )


@router.post("/asignar")
def asignar(
    reto_id: int = Form(...),
    fecha: str = Form(...),
    alcance: str = Form(ALCANCE_UNIDAD),
    patrulla_id: str = Form(""),
    joven_id: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    reto = sesion.get(Reto, reto_id)
    if reto is None or reto.unidad_id != unidad_id:
        raise HTTPException(404, "Ese reto no existe.")

    if alcance not in (ALCANCE_UNIDAD, ALCANCE_PATRULLA, ALCANCE_JOVEN):
        raise HTTPException(400, "Alcance desconocido.")
    if alcance == ALCANCE_PATRULLA and not patrulla_id.strip():
        raise HTTPException(400, "Elegí una patrulla.")
    if alcance == ALCANCE_JOVEN and not joven_id.strip():
        raise HTTPException(400, "Elegí a quién asignarle el reto.")

    sesion.add(
        Asignacion(
            reto_id=reto.id,
            fecha=date.fromisoformat(fecha),
            alcance=alcance,
            unidad_id=unidad_id,
            patrulla_id=int(patrulla_id) if alcance == ALCANCE_PATRULLA else None,
            joven_id=int(joven_id) if alcance == ALCANCE_JOVEN else None,
            asignado_por_id=usuario.id,
        )
    )
    sesion.commit()
    return redirigir("/asignar")


# --- Patrullas y jóvenes -----------------------------------------------------


@router.get("/patrullas")
def listar_patrullas(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    return render(
        request,
        "educador/patrullas.html",
        usuario=usuario,
        patrullas=list(
            sesion.scalars(
                select(Patrulla)
                .where(Patrulla.unidad_id == unidad_id)
                .order_by(Patrulla.nombre)
            )
        ),
    )


@router.post("/patrullas")
def crear_patrulla(
    nombre: str = Form(...),
    lema: str = Form(""),
    color: str = Form("#3E8E5A"),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    sesion.add(
        Patrulla(
            unidad_id=_unidad_de(usuario),
            nombre=nombre.strip(),
            lema=lema.strip(),
            color=color,
        )
    )
    sesion.commit()
    return redirigir("/patrullas")


@router.get("/jovenes")
def listar_jovenes(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    return render(
        request,
        "educador/jovenes.html",
        usuario=usuario,
        jovenes=list(
            sesion.scalars(
                select(Usuario)
                .where(Usuario.unidad_id == unidad_id, Usuario.rol == ROL_JOVEN)
                .order_by(Usuario.nombre)
            )
        ),
        patrullas=list(
            sesion.scalars(
                select(Patrulla)
                .where(Patrulla.unidad_id == unidad_id, Patrulla.activa.is_(True))
                .order_by(Patrulla.nombre)
            )
        ),
        etapas=ETAPAS,
    )


@router.post("/jovenes")
def crear_joven(
    nombre: str = Form(...),
    usuario_nuevo: str = Form(...),
    clave: str = Form(...),
    patrulla_id: str = Form(""),
    etapa: str = Form("pistas"),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    login = usuario_nuevo.strip().lower()
    if sesion.scalar(select(Usuario.id).where(Usuario.usuario == login)) is not None:
        raise HTTPException(400, f"El usuario «{login}» ya existe.")
    if etapa not in ETAPAS:
        raise HTTPException(400, "Etapa desconocida.")

    sesion.add(
        Usuario(
            usuario=login,
            nombre=nombre.strip(),
            hash_clave=hashear_clave(clave),
            rol=ROL_JOVEN,
            unidad_id=unidad_id,
            patrulla_id=int(patrulla_id) if patrulla_id.strip() else None,
            etapa=etapa,
        )
    )
    sesion.commit()
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}")
def actualizar_joven(
    joven_id: int,
    patrulla_id: str = Form(""),
    etapa: str = Form("pistas"),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    joven = sesion.get(Usuario, joven_id)
    if joven is None or joven.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Esa persona no está en tu Unidad.")
    if etapa not in ETAPAS:
        raise HTTPException(400, "Etapa desconocida.")

    joven.patrulla_id = int(patrulla_id) if patrulla_id.strip() else None
    joven.etapa = etapa
    sesion.commit()
    return redirigir("/jovenes")
