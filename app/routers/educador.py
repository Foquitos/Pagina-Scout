"""Panel del equipo de educadoras y educadores."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PUNTAJE_POR_DEFECTO
from app.db import obtener_sesion
from app.dependencias import quiere_json, redirigir, render, solo_educador
from app.models import (
    ALCANCE_JOVEN,
    ALCANCE_PATRULLA,
    ALCANCE_UNIDAD,
    ESTADO_APROBADA,
    ESTADO_RECHAZADA,
    ESTADO_REVISION,
    ETAPAS,
    ROL_EDUCADOR,
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
from app.servicios import cuentas, progresion, puntajes, retos

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
    educadores = sesion.scalar(
        select(func.count(Usuario.id)).where(
            Usuario.unidad_id == unidad_id,
            Usuario.rol == ROL_EDUCADOR,
            Usuario.activo.is_(True),
        )
    )

    return render(
        request,
        "educador/panel.html",
        usuario=usuario,
        fecha=fecha,
        pendientes=pendientes or 0,
        asignaciones_hoy=asignaciones_hoy,
        jovenes_sin_patrulla=jovenes_sin_patrulla or 0,
        educadores=educadores or 0,
        filas=puntajes.tablero_de_unidad(sesion, unidad_id, fecha),
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
    confirmar: str = "",
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    # `confirmar` trae el reto que se quiso sacar y tenía entregas adentro,
    # para volver a mostrar el aviso con lo que se estaría llevando puesto.
    a_confirmar = _agendado(sesion, confirmar, usuario) if confirmar else None
    return render(
        request,
        "educador/asignar.html",
        usuario=usuario,
        hoy=retos.hoy(),
        a_confirmar=a_confirmar,
        se_lleva=retos.lo_que_se_lleva(a_confirmar) if a_confirmar else None,
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


def _agendado(sesion: Session, asignacion_id: str | int, educador: Usuario) -> Asignacion | None:
    """Una asignación de la Unidad de quien pregunta, o nada."""
    try:
        asignacion = sesion.get(Asignacion, int(asignacion_id))
    except (TypeError, ValueError):
        return None
    if asignacion is None or asignacion.unidad_id != _unidad_de(educador):
        return None
    return asignacion


@router.post("/asignar/{asignacion_id}/borrar")
def borrar_agendado(
    asignacion_id: int,
    confirmado: bool = Form(False),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Saca un reto de la agenda. Arrepentirse tiene que poder ser barato.

    Sin entregas se saca derecho. Con entregas no, y no por trámite: adentro
    hay lo que escribió un chico y puntos que ya están en el tablero de una
    patrulla. Se puede igual —la decisión es del educador— pero recién después
    de leer qué se lleva puesto.
    """
    asignacion = _agendado(sesion, asignacion_id, usuario)
    if asignacion is None:
        raise HTTPException(404, "Ese reto agendado no existe.")

    if retos.lo_que_se_lleva(asignacion).hay_trabajo_ajeno and not confirmado:
        return redirigir(f"/asignar?confirmar={asignacion.id}#confirmar")

    retos.borrar_asignacion(sesion, asignacion)
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
    jovenes = list(
        sesion.scalars(
            select(Usuario)
            .where(Usuario.unidad_id == unidad_id, Usuario.rol == ROL_JOVEN)
            .order_by(Usuario.nombre)
        )
    )
    return render(
        request,
        "educador/jovenes.html",
        usuario=usuario,
        jovenes=jovenes,
        conteos=progresion.conteo_por_joven(sesion, jovenes),
        patrullas=list(
            sesion.scalars(
                select(Patrulla)
                .where(Patrulla.unidad_id == unidad_id, Patrulla.activa.is_(True))
                .order_by(Patrulla.nombre)
            )
        ),
        etapas=ETAPAS,
        min_cartas=progresion.MIN_CARTAS,
    )


@router.post("/jovenes")
def crear_joven(
    nombre: str = Form(...),
    usuario_nuevo: str = Form(...),
    patrulla_id: str = Form(""),
    etapa: str = Form("pistas"),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Da de alta a un joven. La contraseña no se pide: es su nombre de usuario.

    Antes había un campo «contraseña inicial» y era el peor de los dos mundos: el
    educador tenía que inventar algo, dictarlo, y quedaba sabiendo con qué entra
    otra persona. Ahora el alta se cuenta en una frase —«tu usuario es `ana` y tu
    contraseña también»— y la contraseña de verdad la elige el joven al entrar.
    """
    unidad_id = _unidad_de(usuario)
    if etapa not in ETAPAS:
        raise HTTPException(400, "Etapa desconocida.")

    try:
        cuentas.alta(
            sesion,
            usuario_nuevo,
            nombre,
            ROL_JOVEN,
            unidad_id=unidad_id,
            patrulla_id=int(patrulla_id) if patrulla_id.strip() else None,
            etapa=etapa,
        )
    except cuentas.DatoInvalido as error:
        raise HTTPException(400, error.motivo) from error

    sesion.commit()
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}")
def actualizar_joven(
    joven_id: int,
    request: Request,
    patrulla_id: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Cambia la patrulla. La etapa no: esa se toca en /progresion.

    Son dos decisiones de naturaleza distinta. Mover a alguien de patrulla es
    organizar la Unidad; cambiarle la etapa es cerrar un tramo de su progresión
    personal, y para eso hay que estar mirando sus cartas.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    joven.patrulla_id = int(patrulla_id) if patrulla_id.strip() else None
    sesion.commit()
    if quiere_json(request):
        # Acomodar treinta chicos en sus patrullas eran treinta recargas de una
        # lista de treinta. Ahora el select se guarda solo y no se mueve nada.
        return {"ok": True}
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}/blanquear")
def blanquear_joven(
    joven_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """«Me olvidé la contraseña». Vuelve a ser su nombre de usuario.

    Es todo el sistema de recuperación que hay, y alcanza: el educador está en la
    misma reunión que el joven. La contraseña vieja no se muestra en ningún lado
    —nadie la sabe, ni acá ni en la base— y la nueva la vuelve a elegir el joven
    en cuanto entre.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    cuentas.blanquear(joven)
    sesion.commit()
    return redirigir("/jovenes")


# --- Equipo de educadores ----------------------------------------------------
#
# No hay un rol de administrador aparte: cualquier educador de la Unidad puede
# sumar a otro. El equipo son tres o cuatro personas que se conocen y comparten
# la responsabilidad del programa; inventar una jerarquía adentro sería inventar
# un cargo que en la Unidad no existe. Lo que sí queda cerrado es el borde de
# afuera: solo se ve y se toca el equipo de la propia Unidad.


@router.get("/educadores")
def listar_educadores(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    return render(
        request,
        "educador/educadores.html",
        usuario=usuario,
        educadores=list(
            sesion.scalars(
                select(Usuario)
                .where(Usuario.unidad_id == unidad_id, Usuario.rol == ROL_EDUCADOR)
                .order_by(Usuario.nombre)
            )
        ),
    )


@router.post("/educadores")
def crear_educador(
    nombre: str = Form(...),
    usuario_nuevo: str = Form(...),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Suma a alguien al equipo, en la misma Unidad de quien lo da de alta.

    Entra con su nombre de usuario como contraseña y lo primero que hace es
    cambiarla, igual que un joven. Que el alta la pueda hacer cualquiera del
    equipo es lo que saca el `scripts/crear_educador.py` del camino: la consola
    del servidor queda solo para el primer educador de todos.
    """
    try:
        cuentas.alta(
            sesion, usuario_nuevo, nombre, ROL_EDUCADOR, unidad_id=_unidad_de(usuario)
        )
    except cuentas.DatoInvalido as error:
        raise HTTPException(400, error.motivo) from error

    sesion.commit()
    return redirigir("/educadores")


@router.post("/educadores/{educador_id}/blanquear")
def blanquear_educador(
    educador_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Blanquea la contraseña de otro educador del equipo.

    La propia no: para eso está «Cambiar mi contraseña», que pide la actual.
    Blanquearse a sí mismo no serviría para recuperar nada —hay que estar dentro
    de la sesión para poder pedirlo— y dejaría la cuenta con la contraseña más
    fácil de adivinar que existe.
    """
    otro = sesion.get(Usuario, educador_id)
    if otro is None or otro.rol != ROL_EDUCADOR or otro.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Esa persona no está en el equipo de tu Unidad.")
    if otro.id == usuario.id:
        raise HTTPException(400, "La tuya se cambia desde «Cambiar mi contraseña».")

    cuentas.blanquear(otro)
    sesion.commit()
    return redirigir("/educadores")


# --- Progresión personal -----------------------------------------------------


def _joven_de_la_unidad(sesion: Session, joven_id: int, educador: Usuario) -> Usuario:
    joven = sesion.get(Usuario, joven_id)
    if joven is None or joven.rol != ROL_JOVEN or joven.unidad_id != _unidad_de(educador):
        raise HTTPException(404, "Esa persona no está en tu Unidad.")
    return joven


@router.get("/progresion/{joven_id}")
def ver_progresion(
    joven_id: int,
    request: Request,
    confirmar: str = "",
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Las cartas de la etapa y el cambio de etapa, en la misma página.

    Juntas a propósito: la guía cuenta las cartas como el recorrido de la etapa,
    así que la decisión de pasar de etapa se toma mirando cómo vienen, no de
    memoria. `confirmar` trae lo que quedó pendiente de confirmar en el POST
    anterior, para volver a mostrar el aviso donde corresponde.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    resumen = progresion.resumen_de_etapa(sesion, joven)
    return render(
        request,
        "educador/progresion.html",
        usuario=usuario,
        joven=joven,
        resumen=resumen,
        avances=resumen.avances,
        marcas=progresion.marcas_de(sesion, joven),
        cambios=progresion.historial_de_etapas(sesion, joven),
        historial=progresion.historial_de_cartas(sesion, joven),
        propia=False,
        nombre_corto=joven.nombre,
        etapas=ETAPAS,
        min_cartas=progresion.MIN_CARTAS,
        max_cartas=progresion.MAX_CARTAS,
        confirmar=confirmar,
    )


@router.post("/progresion/{joven_id}/cartas/{competencia_id}")
def resolver_carta(
    joven_id: int,
    competencia_id: int,
    accion: str = Form(...),
    nota: str = Form(""),
    confirmado: bool = Form(False),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Da una carta por lograda, o reabre una que se cerró de más."""
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    elegida = progresion.carta_elegida(sesion, joven, competencia_id)
    if elegida is None:
        raise HTTPException(404, "Esa carta no está en su elección de esta etapa.")

    destino = f"/progresion/{joven.id}#carta-{competencia_id}"
    if accion == "reabrir":
        progresion.reabrir_carta(elegida)
    elif accion == "cerrar":
        avance = progresion.avance_de_carta(elegida, progresion.marcas_de(sesion, joven))
        try:
            progresion.cerrar_carta(elegida, avance, usuario, nota, confirmado)
        except progresion.NecesitaConfirmacion:
            # No se pierde nada ni se rompe la navegación: vuelve a la página
            # con el aviso abierto sobre esa carta.
            return redirigir(f"/progresion/{joven.id}?confirmar={competencia_id}#carta-{competencia_id}")
    else:
        raise HTTPException(400, "Acción desconocida.")

    sesion.commit()
    return redirigir(destino)


@router.post("/progresion/{joven_id}/etapa")
def cambiar_etapa(
    joven_id: int,
    etapa: str = Form(...),
    nota: str = Form(""),
    confirmado: bool = Form(False),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """El paso de etapa. Lo decide el equipo de educadores, siempre."""
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    if etapa not in ETAPAS:
        raise HTTPException(400, "Etapa desconocida.")

    try:
        progresion.cambiar_etapa(sesion, joven, etapa, usuario, nota, confirmado)
    except progresion.NecesitaConfirmacion:
        return redirigir(f"/progresion/{joven.id}?confirmar=etapa#etapa")

    sesion.commit()
    return redirigir(f"/progresion/{joven.id}#etapa")
