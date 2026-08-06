"""Panel del equipo de educadoras y educadores."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import tiempo
from app.config import PUNTAJE_POR_DEFECTO
from app.db import hay_referencias_a, obtener_sesion
from app.dependencias import (
    quiere_json,
    recordar_provisoria,
    redirigir,
    render,
    solo_educador,
    tomar_provisoria,
)
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
    Cargo,
    Competencia,
    Desafio,
    EntradaLibroOro,
    Entrega,
    Patrulla,
    PausaSinTelefono,
    PeriodoCargo,
    Reto,
    Usuario,
)
from app.servicios import (
    agenda,
    cuentas,
    cumpleanos,
    especialidades,
    moderacion,
    participacion,
    pausas,
    progresion,
    puntajes,
    retos,
)
from app.servicios import patrulla as vida_de_patrulla

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
        # Lo que pide una respuesta del equipo y no está en «Entregas»: cartas
        # que un joven cerró y falta conversar, especialidades a un paso de la
        # insignia, e ideas que nadie miró todavía.
        cartas_a_conversar=progresion.cartas_sin_acordar(sesion, unidad_id),
        especialidades_listas=especialidades.listas_para_cerrar(sesion, unidad_id),
        especialidades_pedidas=especialidades.sin_preparar(sesion, unidad_id),
        ideas_sin_mirar=participacion.sin_mirar(sesion, unidad_id),
        proximas=agenda.proximas(sesion, usuario, fecha, tope=3),
        # Alguien pidió que el equipo mire una foto publicada. Es lo único de
        # este panel que puede ser urgente, así que se muestra arriba de todo.
        avisadas=moderacion.cuantas_sin_mirar(sesion, unidad_id),
        # Quiénes están sin teléfono. Va en el panel y no escondido en una ficha
        # porque es lo que explica que el tablero divida por menos, y porque
        # alguien tiene que sentarse a cargar lo que hicieron.
        sin_telefono=pausas.a_quienes_puede_cargar(sesion, usuario, fecha),
        # Los que vienen en el mes. Acá se muestran con la edad, que del lado de
        # los jóvenes no se muestra: ver `servicios/cumpleanos.py`.
        cumples=cumpleanos.proximos(sesion, unidad_id, fecha),
    )


# --- Novedades: todo lo que se publicó ----------------------------------------
#
# En esta aplicación una foto entra al muro o al Libro de Oro en el momento, sin
# que ningún adulto la mire antes. Es deliberado —pedirle permiso a un grande
# para escribir en el libro de la propia patrulla lo desnaturaliza— y esta
# pantalla es lo que lo hace sostenible: el equipo se entera de todo en un solo
# lugar, sin recorrer siete libros de patrulla, y puede bajar algo en dos toques.
#
# No es una cola de aprobación. Todo lo que está acá ya está publicado.


@router.get("/novedades")
def novedades(
    request: Request,
    filtro: str = "todas",
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    lista = moderacion.novedades(sesion, unidad_id)

    if filtro == "avisadas":
        lista = [n for n in lista if n.avisos_abiertos]
    elif filtro == "con_foto":
        lista = [n for n in lista if n.foto]
    elif filtro == "bajadas":
        lista = [n for n in lista if n.oculta]

    return render(
        request,
        "educador/novedades.html",
        usuario=usuario,
        novedades=lista,
        filtro=filtro,
        avisadas=moderacion.cuantas_sin_mirar(sesion, unidad_id),
    )


def _publicacion(sesion: Session, clase: str, cosa_id: int, educador: Usuario):
    """La entrega o la página de libro que la acción quiere tocar, de esta Unidad."""
    unidad_id = _unidad_de(educador)
    if clase == "muro":
        entrega = sesion.get(Entrega, cosa_id)
        if entrega is None or entrega.asignacion.unidad_id != unidad_id:
            raise HTTPException(404, "Esa publicación no existe.")
        return entrega
    if clase == "libro":
        pagina = sesion.get(EntradaLibroOro, cosa_id)
        if pagina is None or pagina.patrulla.unidad_id != unidad_id:
            raise HTTPException(404, "Esa página no existe.")
        return pagina
    raise HTTPException(404, "Esa publicación no existe.")


@router.post("/novedades/{clase}/{cosa_id}")
def resolver_novedad(
    clase: str,
    cosa_id: int,
    decision: str = Form(...),
    resolucion: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Bajar una publicación, devolverla, o cerrar el aviso dejándola como está.

    Las tres son de una persona y las tres se pueden deshacer. Bajar no borra:
    la entrega conserva sus puntos y la página del libro sigue existiendo, con
    lo cual un error a las once de la noche se arregla desde acá y no entrando
    a la base de datos.
    """
    cosa = _publicacion(sesion, clase, cosa_id, usuario)
    abiertos = [
        a
        for a in moderacion.avisos_abiertos(sesion, _unidad_de(usuario))
        if (a.entrega_id == cosa_id if clase == "muro" else a.libro_id == cosa_id)
    ]

    if decision == "bajar":
        if clase == "muro":
            moderacion.bajar_entrega(cosa, usuario)
        else:
            moderacion.bajar_pagina(cosa, usuario)
        moderacion.atender(abiertos, usuario, resolucion or "Se bajó la publicación.")
    elif decision == "devolver":
        if clase == "muro":
            moderacion.devolver_entrega(cosa)
        else:
            moderacion.devolver_pagina(cosa)
        moderacion.atender(abiertos, usuario, resolucion or "Se volvió a publicar.")
    elif decision == "esta_bien":
        # El aviso se mira y se cierra sin bajar nada. Que exista esta salida es
        # lo que hace que avisar no sea automáticamente sacar algo del muro.
        moderacion.atender(abiertos, usuario, resolucion or "Lo miramos y queda.")
    else:
        raise HTTPException(400, "Decisión desconocida.")

    sesion.commit()
    return redirigir("/novedades")


# --- Validación --------------------------------------------------------------


@router.get("/validaciones")
def validaciones(
    request: Request,
    estado: str = "todas",
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Lo que entregaron. **No es una cola de aprobación.**

    Una entrega completa se da por buena sola y suma en el momento: un chico que
    hizo lo que le pidieron no tiene por qué esperar al sábado para que alguien
    le diga que sí. Lo que el equipo hace acá es mirar y, si algo no pasó, darlo
    de baja —«no lo hiciste» es una conversación de una persona, nunca de un
    programa—. Por eso la lista arranca mostrando todo y no solo lo pendiente.

    Queda lo que sí necesita una respuesta: las entregas incompletas, que el
    validador automático nunca rechaza y deriva acá (ver `servicios/validacion`).
    """
    unidad_id = _unidad_de(usuario)
    consulta = (
        select(Entrega)
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .where(Asignacion.unidad_id == unidad_id)
        .order_by(Entrega.enviada_en.desc())
    )
    if estado != "todas":
        consulta = consulta.where(Entrega.estado == estado)

    esperando = sesion.scalar(
        select(func.count(Entrega.id))
        .join(Asignacion, Asignacion.id == Entrega.asignacion_id)
        .where(Asignacion.unidad_id == unidad_id, Entrega.estado == ESTADO_REVISION)
    )
    return render(
        request,
        "educador/validaciones.html",
        usuario=usuario,
        entregas=list(sesion.scalars(consulta.limit(120))),
        estado=estado,
        esperando=esperando or 0,
    )


@router.post("/validaciones/{entrega_id}")
def resolver_validacion(
    entrega_id: int,
    decision: str = Form(...),
    devolucion: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Dar por buena una entrega incompleta, dar de baja una que no pasó, o
    simplemente decirle algo a quien la hizo.

    `felicitar` está para lo último y no toca nada más: ni el estado, ni los
    puntos, ni el muro. Casi todas las entregas se aprueban solas, así que sin
    esta puerta la única forma de escribirle a un chico era bajarle el reto o
    pedirle que amplíe —las dos malas noticias—. Reconocer lo que estuvo bien es
    la mitad de la heteroevaluación (cap. 9) y tiene que costar un botón.
    """
    entrega = sesion.get(Entrega, entrega_id)
    if entrega is None or entrega.asignacion.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Esa entrega no existe.")

    texto = devolucion.strip()
    if decision == "aprobar":
        entrega.estado = ESTADO_APROBADA
        entrega.puntaje_otorgado = entrega.asignacion.reto.puntaje
    elif decision == "rechazar":
        entrega.estado = ESTADO_RECHAZADA
        entrega.puntaje_otorgado = 0
        # Lo que se da de baja sale del muro. No se borra la entrega —el joven
        # la sigue viendo con la devolución— pero deja de estar publicada.
        entrega.compartida = False
    elif decision == "devolver":
        entrega.estado = ESTADO_REVISION
        entrega.puntaje_otorgado = 0
        entrega.compartida = False
    elif decision == "felicitar":
        # Un comentario vacío no es un comentario, y acá no hay nada más que
        # guardar: sin texto esto no haría absolutamente nada.
        if not texto:
            raise HTTPException(400, "Escribile algo: un comentario en blanco no le llega.")
    else:
        raise HTTPException(400, "Decisión desconocida.")

    if texto:
        entrega.devolucion = texto
        entrega.devolucion_por_id = usuario.id
        entrega.devolucion_en = tiempo.ahora()

    # Felicitar no es validar: la entrega ya la había validado alguien —muchas
    # veces el validador automático— y ese registro no se pisa por dejar un
    # comentario. Quién escribió qué queda igual de firmado en `devolucion_por`.
    if decision != "felicitar":
        entrega.validador = "educador"
        entrega.validada_por_id = usuario.id
        entrega.validada_en = tiempo.ahora()
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
        usos=_uso_de_los_retos(sesion, propios),
        areas=list(sesion.scalars(select(Area).order_by(Area.id))),
        competencias=list(sesion.scalars(select(Competencia).order_by(Competencia.numero))),
        puntaje_defecto=PUNTAJE_POR_DEFECTO,
    )


def _uso_de_los_retos(sesion: Session, retos_propios: list[Reto]) -> dict[int, tuple[int, int]]:
    """Cuántas veces se agendó cada reto y cuántas entregas juntó: `{id: (veces, entregas)}`.

    Es lo que la pantalla necesita para avisar antes de dejar corregir. Un reto
    que nadie usó todavía se cambia sin pensarlo; uno que treinta chicos ya
    leyeron y entregaron no, y el que edita tiene que saber de cuál se trata.
    """
    if not retos_propios:
        return {}
    return {
        reto_id: (veces, entregas)
        for reto_id, veces, entregas in sesion.execute(
            select(
                Asignacion.reto_id,
                func.count(func.distinct(Asignacion.id)),
                func.count(Entrega.id),
            )
            .join(Entrega, Entrega.asignacion_id == Asignacion.id, isouter=True)
            .where(Asignacion.reto_id.in_([r.id for r in retos_propios]))
            .group_by(Asignacion.reto_id)
        )
    }


def _carta_y_area(
    sesion: Session, desafio_id: str, area_id: str
) -> tuple[Desafio | None, Area | None]:
    """De qué desafío de carta sale el reto y en qué área cae.

    El área la manda la carta cuando hay carta: son el mismo dato dicho dos
    veces, y si se dejaran sueltos un reto podría terminar clasificado en un
    área que no es la de su desafío. El selector de área es para los retos
    propios, que no cuelgan de ninguna.
    """
    desafio = sesion.get(Desafio, int(desafio_id)) if desafio_id.strip() else None
    if desafio is not None:
        return desafio, desafio.competencia.area
    if area_id.strip():
        return None, sesion.get(Area, int(area_id))
    return None, None


def _reto_de_la_unidad(sesion: Session, reto_id: int, educador: Usuario) -> Reto:
    reto = sesion.get(Reto, reto_id)
    if reto is None or reto.unidad_id != _unidad_de(educador):
        raise HTTPException(404, "Ese reto no existe.")
    return reto


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
    if not titulo.strip() or not consigna.strip():
        raise HTTPException(400, "El reto necesita un título y una consigna.")

    desafio, area = _carta_y_area(sesion, desafio_id, area_id)

    sesion.add(
        Reto(
            titulo=titulo.strip()[:200],
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


@router.post("/retos/{reto_id}")
def actualizar_reto(
    reto_id: int,
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
    """Corrige un reto ya escrito, esté agendado o no.

    Un reto se escribe una vez y se agenda muchas. La consigna que el primer
    día resultó confusa, el título con un error, los puntos que quedaron altos:
    todo eso se arregla acá y no archivando el reto para escribir otro casi
    igual, que era lo único que había y dejaba la lista llena de mellizos.

    Lo que ya pasó no se toca. Los puntos se copian a la entrega en el momento
    de validarla —`puntaje_otorgado`—, así que cambiar el puntaje vale para lo
    que se valide de ahora en adelante y no reescribe ningún tablero. Lo que sí
    cambia para todos, incluso para quien ya entregó, es el texto: es el mismo
    reto, y por eso la pantalla avisa cuántos lo tienen entre manos.

    También cambia lo que se le pide a la próxima entrega. Sumar «pide foto» a
    un reto que ya entregaron sin foto no invalida nada de lo hecho: las
    entregas viejas quedan como estaban y la regla nueva corre para las que
    vengan.
    """
    reto = _reto_de_la_unidad(sesion, reto_id, usuario)
    if not titulo.strip() or not consigna.strip():
        raise HTTPException(400, "El reto necesita un título y una consigna.")

    desafio, area = _carta_y_area(sesion, desafio_id, area_id)

    reto.titulo = titulo.strip()[:200]
    reto.consigna = consigna.strip()
    reto.tipo = TIPO_CARTA if desafio is not None else TIPO_PERSONALIZADO
    reto.desafio_id = desafio.id if desafio else None
    reto.area_id = area.id if area else None
    reto.puntaje = max(0, puntaje)
    reto.pide_texto = pide_texto
    reto.pide_foto = pide_foto
    sesion.commit()
    return redirigir("/retos")


@router.post("/retos/{reto_id}/archivar")
def archivar_reto(
    reto_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    reto = _reto_de_la_unidad(sesion, reto_id, usuario)
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
    todas = list(
        sesion.scalars(
            select(Patrulla).where(Patrulla.unidad_id == unidad_id).order_by(Patrulla.nombre)
        )
    )
    return render(
        request,
        "educador/patrullas.html",
        usuario=usuario,
        patrullas=[p for p in todas if p.activa],
        disueltas=[p for p in todas if not p.activa],
        # Qué va a pasar con cada una si la disuelven, para poder decirlo antes:
        # con gente adentro no se puede, vacía con historia se desactiva, y
        # vacía sin rastro se borra. Ver `servicios/patrulla.py`.
        integrantes={
            p.id: vida_de_patrulla.integrantes_activos(sesion, p.id) for p in todas
        },
        deja_rastro={p.id: hay_referencias_a(sesion, "patrullas", p.id) for p in todas},
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


def _patrulla_de_la_unidad(sesion: Session, patrulla_id: int, educador: Usuario) -> Patrulla:
    patrulla = sesion.get(Patrulla, patrulla_id)
    if patrulla is None or patrulla.unidad_id != _unidad_de(educador):
        raise HTTPException(404, "Esa patrulla no existe.")
    return patrulla


@router.post("/patrullas/{patrulla_id}/disolver")
def disolver_patrulla(
    patrulla_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Saca una patrulla de circulación.

    Con gente adentro no se puede, y no es un trámite: a dónde va cada uno lo
    decide la Unidad, no puede ser el efecto secundario de disolver una etiqueta.
    Vacía se desactiva —el Libro de Oro y los Consejos son la memoria de quienes
    pasaron por ahí, y no se borran porque la patrulla dejó de reunirse— salvo
    que no haya dejado ningún rastro, y ahí sí se borra. Ver `servicios/patrulla.py`.
    """
    patrulla = _patrulla_de_la_unidad(sesion, patrulla_id, usuario)
    if not patrulla.activa:
        raise HTTPException(400, "Esa patrulla ya está disuelta.")

    try:
        vida_de_patrulla.disolver(sesion, patrulla)
    except vida_de_patrulla.NoSePuedeDisolver as error:
        raise HTTPException(400, str(error)) from error

    sesion.commit()
    return redirigir("/patrullas")


@router.post("/patrullas/{patrulla_id}/reabrir")
def reabrir_patrulla(
    patrulla_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Vuelve a estar en juego, con su Libro de Oro y su historia intactos."""
    patrulla = _patrulla_de_la_unidad(sesion, patrulla_id, usuario)
    if patrulla.activa:
        raise HTTPException(400, "Esa patrulla ya está en juego.")

    vida_de_patrulla.reabrir(patrulla)
    sesion.commit()
    return redirigir("/patrullas")


# --- Catálogo de cargos de patrulla (cap. 4) ---------------------------------
#
# El catálogo lo cuida el equipo porque es de la Unidad entera; quién ocupa cada
# cargo lo decide cada patrulla en su Consejo, y eso pasa en `/patrulla/{id}`.


@router.get("/cargos")
def listar_cargos(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    cargos = vida_de_patrulla.catalogo(sesion, unidad_id, incluir_bajas=True)
    en_uso = {
        cargo_id: cuenta
        for cargo_id, cuenta in sesion.execute(
            select(PeriodoCargo.cargo_id, func.count(PeriodoCargo.id))
            .where(PeriodoCargo.cargo_id.in_([c.id for c in cargos] or [0]))
            .group_by(PeriodoCargo.cargo_id)
        )
    }
    return render(
        request,
        "educador/cargos.html",
        usuario=usuario,
        cargos=cargos,
        en_uso=en_uso,
    )


@router.post("/cargos")
def crear_cargo(
    nombre: str = Form(...),
    descripcion: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Un cargo propio de la Unidad.

    La guía dice que los cargos «pueden variar en cantidad y en denominación, de
    acuerdo con las costumbres de las Unidades», y que además pueden aparecer
    otros «producto de las necesidades de (…) las actividades y proyectos que
    emprendan». Así que esto tiene que ser fácil.
    """
    unidad_id = _unidad_de(usuario)
    if not nombre.strip():
        raise HTTPException(400, "Ponele un nombre al cargo.")

    ultimo = sesion.scalar(
        select(func.max(Cargo.orden)).where(Cargo.unidad_id == unidad_id)
    )
    sesion.add(
        Cargo(
            unidad_id=unidad_id,
            nombre=nombre.strip()[:80],
            descripcion=descripcion.strip(),
            orden=(ultimo or 0) + 1,
        )
    )
    sesion.commit()
    return redirigir("/cargos")


@router.post("/cargos/{cargo_id}")
def alternar_cargo(
    cargo_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Da de baja un cargo del catálogo, o lo devuelve.

    No se borra nunca: los períodos ya cumplidos cuelgan de él y son parte de la
    progresión de alguien. Un cargo dado de baja deja de ofrecerse y nada más.
    """
    cargo = sesion.get(Cargo, cargo_id)
    if cargo is None or cargo.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Ese cargo no existe.")
    cargo.activo = not cargo.activo
    sesion.commit()
    return redirigir("/cargos")


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
        jovenes=[j for j in jovenes if j.activo],
        ya_no_estan=[j for j in jovenes if not j.activo],
        # Igual que en el equipo: una ficha que no dejó rastro se borra, una con
        # progresión escrita se archiva. Se dice antes de que aprieten.
        deja_rastro={j.id: cuentas.dejo_rastro(sesion, j.id) for j in jovenes},
        conteos=progresion.conteo_por_joven(sesion, jovenes),
        # Quién está sin teléfono hoy, para poder cerrarle la pausa desde su
        # tarjeta y para que se vea de un vistazo por qué el tablero divide por
        # menos. El motivo se lee solo acá: ver `models.PausaSinTelefono`.
        en_pausa=pausas.vigentes_de(sesion, [j.id for j in jovenes], retos.hoy()),
        motivos_sugeridos=pausas.MOTIVOS_SUGERIDOS,
        patrullas=list(
            sesion.scalars(
                select(Patrulla)
                .where(Patrulla.unidad_id == unidad_id, Patrulla.activa.is_(True))
                .order_by(Patrulla.nombre)
            )
        ),
        etapas=ETAPAS,
        min_cartas=progresion.MIN_CARTAS,
        # Para calcular la edad en la plantilla sin que cada tarjeta pregunte
        # qué día es hoy: la respuesta es la misma para todas.
        hoy=retos.hoy(),
        # Si se viene de un alta o de un blanqueo, la provisoria se muestra acá
        # y desaparece: al recargar ya no está, porque leerla la consume.
        provisoria=tomar_provisoria(request),
    )


@router.post("/jovenes")
def crear_joven(
    request: Request,
    nombre: str = Form(...),
    usuario_nuevo: str = Form(...),
    patrulla_id: str = Form(""),
    etapa: str = Form("pistas"),
    nacimiento: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Da de alta a un joven. La contraseña se sortea y se muestra una sola vez.

    Nunca hubo un campo «contraseña inicial» y sigue sin haberlo: el educador no
    tiene que inventar nada. Lo que cambió es que la provisoria ya no es el
    nombre de usuario —era adivinable, y adivinable en una sola prueba—, así que
    ahora la pantalla se la muestra una vez para que se la diga en el momento.
    """
    unidad_id = _unidad_de(usuario)
    if etapa not in ETAPAS:
        raise HTTPException(400, "Etapa desconocida.")

    try:
        joven, clave = cuentas.alta(
            sesion,
            usuario_nuevo,
            nombre,
            ROL_JOVEN,
            unidad_id=unidad_id,
            patrulla_id=int(patrulla_id) if patrulla_id.strip() else None,
            etapa=etapa,
            nacimiento=_nacimiento(nacimiento),
        )
    except cuentas.DatoInvalido as error:
        raise HTTPException(400, error.motivo) from error

    sesion.commit()
    recordar_provisoria(request, joven.usuario, clave)
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}")
def actualizar_joven(
    joven_id: int,
    request: Request,
    patrulla_id: str = Form(""),
    nacimiento: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Cambia la patrulla y el cumpleaños. La etapa no: esa se toca en /progresion.

    Son decisiones de naturaleza distinta. Mover a alguien de patrulla u ordenar
    un dato de su ficha es organizar la Unidad; cambiarle la etapa es cerrar un
    tramo de su progresión personal, y para eso hay que estar mirando sus cartas.

    El cumpleaños vacío se guarda vacío: es opcional, así que borrarlo tiene que
    ser tan fácil como ponerlo.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    joven.patrulla_id = int(patrulla_id) if patrulla_id.strip() else None
    joven.nacimiento = _nacimiento(nacimiento)
    sesion.commit()
    if quiere_json(request):
        # Acomodar treinta chicos en sus patrullas eran treinta recargas de una
        # lista de treinta. Ahora el select se guarda solo y no se mueve nada.
        return {"ok": True}
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}/blanquear")
def blanquear_joven(
    joven_id: int,
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """«Me olvidé la contraseña». Se sortea una provisoria y se muestra una vez.

    Es todo el sistema de recuperación que hay, y alcanza: el educador está en la
    misma reunión que el joven. La contraseña vieja no se muestra en ningún lado
    —nadie la sabe, ni acá ni en la base— y la definitiva la vuelve a elegir el
    joven en cuanto entre.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    clave = cuentas.blanquear(joven)
    sesion.commit()
    recordar_provisoria(request, joven.usuario, clave)
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}/baja")
def dar_de_baja_joven(
    joven_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Alguien que dejó la Unidad.

    Lo que esa persona escribió es **suyo**: su Bitácora de Aventura, la
    autoevaluación con la que cerró cada carta, lo que contó en cada entrega. Por
    eso una ficha con progresión adentro no se borra, se archiva: deja de entrar,
    sale del tablero y de las listas, y su patrulla deja de contarla —pero los
    puntos que le dio a su patrulla se quedan donde se ganaron, porque esos días
    pasaron. Si nunca llegó a hacer nada, la ficha se borra de verdad.

    Se puede reincorporar: un chico que vuelve el año que viene se encuentra con
    sus cartas donde las dejó, que es exactamente lo que tiene que pasar.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    if not joven.activo:
        raise HTTPException(400, "Esa persona ya está fuera de la Unidad.")

    cuentas.dar_de_baja(sesion, joven)
    sesion.commit()
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}/reincorporar")
def reincorporar_joven(
    joven_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Vuelve, con sus cartas y su bitácora donde las dejó."""
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    if joven.activo:
        raise HTTPException(400, "Esa persona ya está en la Unidad.")

    cuentas.reincorporar(joven)
    sesion.commit()
    return redirigir("/jovenes")


# --- Sin teléfono ------------------------------------------------------------
#
# Un chico rompe el celular un martes y su patrulla pasa dos semanas dividiendo
# por cinco lo que pudieron hacer cuatro. La pausa corta eso: mientras dure, esa
# cabeza sale del divisor del promedio y lo que él haga se lo puede cargar un
# educador o alguien de su patrulla (ver `servicios/pausas.py` y `/sin-telefono`).
#
# La abre y la cierra el equipo, no el propio joven ni su patrulla: mueve el
# tablero de toda la Unidad, y acá lo que afecta a otros lo firma alguien.


@router.post("/jovenes/{joven_id}/pausa")
def abrir_pausa(
    joven_id: int,
    motivo: str = Form(""),
    vuelve_el: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """«Está sin teléfono». Arranca hoy y, si se sabe, con el día que lo recupera.

    Poner ese día es lo que conviene siempre que se sepa: la pausa se vence sola
    y nadie queda fuera del divisor porque el sábado no se acordaron de cerrarla.
    Sin fecha también vale —un teléfono roto no tiene fecha de arreglo— y
    entonces hay que venir a cerrarla a mano.
    """
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    if not joven.activo:
        raise HTTPException(400, "Esa persona ya no está en la Unidad.")

    hoy = retos.hoy()
    if pausas.vigente(sesion, joven.id, hoy) is not None:
        raise HTTPException(400, f"{joven.nombre} ya figura sin teléfono.")

    pausas.abrir(
        sesion, joven, usuario, motivo=motivo, desde=hoy, vuelve_el=_dia_de_vuelta(vuelve_el)
    )
    sesion.commit()
    # Redirige siempre, también cuando el pedido lo hizo `app.js`: los dos
    # formularios son `data-sin-recarga`, que espera la página entera para
    # repintarla. Devolver un `{"ok": true}` acá dejaría la tarjeta mostrando
    # que sigue con teléfono hasta que alguien recargue.
    return redirigir("/jovenes")


@router.post("/jovenes/{joven_id}/pausa/{pausa_id}/cerrar")
def cerrar_pausa(
    joven_id: int,
    pausa_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """«Ya tiene el teléfono». Vuelve a contar en el promedio desde hoy mismo."""
    joven = _joven_de_la_unidad(sesion, joven_id, usuario)
    pausa = sesion.get(PausaSinTelefono, pausa_id)
    if pausa is None or pausa.joven_id != joven.id:
        raise HTTPException(404, "Esa pausa no existe.")

    pausas.cerrar(pausa, usuario, retos.hoy())
    sesion.commit()
    return redirigir("/jovenes")


def _dia_de_vuelta(texto: str) -> date | None:
    """El día que recupera el teléfono, o nada si no se sabe.

    Tiene que ser mañana o después. Una fecha de hoy o anterior se descarta en
    vez de guardarse: dejaría una pausa que nace vencida, y el educador se iría
    de la pantalla creyendo que la registró.
    """
    try:
        fecha = date.fromisoformat((texto or "").strip())
    except (AttributeError, ValueError):
        return None
    return fecha if fecha > retos.hoy() else None


# --- Equipo de educadores ----------------------------------------------------
#
# No hay un rol de administrador aparte: cualquier educador de la Unidad puede
# sumar a otro. El equipo son tres o cuatro personas que se conocen y comparten
# la responsabilidad del programa; inventar una jerarquía adentro sería inventar
# un cargo que en la Unidad no existe. Lo que sí queda cerrado es el borde de
# afuera: solo se ve y se toca el equipo de la propia Unidad.


def _nacimiento(texto: str) -> date | None:
    """La fecha que vino del formulario, o nada si está vacía o no se entiende.

    Vacío es un valor válido y significa «no lo cargó»: el cumpleaños es
    opcional y borrarlo tiene que ser tan fácil como ponerlo. Una fecha futura
    se descarta —nadie nació mañana— y también una imposible, como el año 200 de
    un dedo que se resbaló en el teclado.
    """
    try:
        fecha = date.fromisoformat((texto or "").strip())
    except (AttributeError, ValueError):
        return None
    hoy = retos.hoy()
    if fecha > hoy or fecha.year < hoy.year - 120:
        return None
    return fecha


def _del_equipo(sesion: Session, educador_id: int, usuario: Usuario) -> Usuario:
    """Otro educador de la propia Unidad. El borde de afuera, en un solo lugar."""
    otro = sesion.get(Usuario, educador_id)
    if otro is None or otro.rol != ROL_EDUCADOR or otro.unidad_id != _unidad_de(usuario):
        raise HTTPException(404, "Esa persona no está en el equipo de tu Unidad.")
    return otro


@router.get("/educadores")
def listar_educadores(
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    unidad_id = _unidad_de(usuario)
    equipo = list(
        sesion.scalars(
            select(Usuario)
            .where(Usuario.unidad_id == unidad_id, Usuario.rol == ROL_EDUCADOR)
            .order_by(Usuario.nombre)
        )
    )
    return render(
        request,
        "educador/educadores.html",
        usuario=usuario,
        educadores=[e for e in equipo if e.activo],
        ya_no_estan=[e for e in equipo if not e.activo],
        # Qué va a pasar si se le da de baja a cada uno, para poder decirlo antes
        # de que apriete: una cuenta sin rastro se borra, una con historia se
        # desactiva. Ver el porqué en `servicios/cuentas.py`.
        deja_rastro={
            e.id: cuentas.dejo_rastro(sesion, e.id) for e in equipo if e.id != usuario.id
        },
        provisoria=tomar_provisoria(request),
        hoy=retos.hoy(),
    )


@router.post("/educadores")
def crear_educador(
    request: Request,
    nombre: str = Form(...),
    usuario_nuevo: str = Form(...),
    nacimiento: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Suma a alguien al equipo, en la misma Unidad de quien lo da de alta.

    Entra con una provisoria sorteada y lo primero que hace es cambiarla, igual
    que un joven. Que el alta la pueda hacer cualquiera del equipo es lo que saca
    el `scripts/crear_educador.py` del camino: la consola del servidor queda solo
    para el primer educador de todos.
    """
    try:
        nuevo, clave = cuentas.alta(
            sesion,
            usuario_nuevo,
            nombre,
            ROL_EDUCADOR,
            unidad_id=_unidad_de(usuario),
            nacimiento=_nacimiento(nacimiento),
        )
    except cuentas.DatoInvalido as error:
        raise HTTPException(400, error.motivo) from error

    sesion.commit()
    recordar_provisoria(request, nuevo.usuario, clave)
    return redirigir("/educadores")


@router.post("/educadores/{educador_id}/nacimiento")
def cumpleanos_de_educador(
    educador_id: int,
    request: Request,
    nacimiento: str = Form(""),
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Pone o saca el cumpleaños de alguien del equipo, el propio incluido.

    Cualquiera del equipo puede tocar el de cualquiera, igual que con el alta y
    el blanqueo: son tres o cuatro personas que se conocen y no hay jerarquía
    adentro. Vacío lo borra, porque el dato es opcional y tiene que poder
    sacarse.
    """
    otro = _del_equipo(sesion, educador_id, usuario)
    otro.nacimiento = _nacimiento(nacimiento)
    sesion.commit()
    if quiere_json(request):
        return {"ok": True}
    return redirigir("/educadores")


@router.post("/educadores/{educador_id}/blanquear")
def blanquear_educador(
    educador_id: int,
    request: Request,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Blanquea la contraseña de otro educador del equipo.

    La propia no: para eso está «Cambiar mi contraseña», que pide la actual.
    Blanquearse a sí mismo no serviría para recuperar nada —hay que estar dentro
    de la sesión para poder pedirlo— y dejaría la cuenta con la contraseña más
    fácil de adivinar que existe.
    """
    otro = _del_equipo(sesion, educador_id, usuario)
    if otro.id == usuario.id:
        raise HTTPException(400, "La tuya se cambia desde «Cambiar mi contraseña».")

    clave = cuentas.blanquear(otro)
    sesion.commit()
    recordar_provisoria(request, otro.usuario, clave)
    return redirigir("/educadores")


# --- Sacar a alguien del equipo ----------------------------------------------


@router.post("/educadores/{educador_id}/baja")
def dar_de_baja_educador(
    educador_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Saca a un educador de la Unidad.

    Si esa cuenta firmó algo —una carta acordada, una etapa cambiada, una entrega
    validada— se desactiva y se puede reincorporar: la aplicación entera está
    construida sobre que se sepa quién decidió qué, y borrarla dejaría huecos en
    la progresión de chicos que hoy dice quién los acompañó. Si no firmó nada
    —el usuario que se escribió mal— se borra de verdad. Lo decide
    `cuentas.dar_de_baja` mirando la base, no un botón distinto.

    **Nadie se da de baja a sí mismo.** No es una formalidad: es lo que garantiza
    que la Unidad no se pueda quedar sin ningún educador activo, porque cada baja
    la tiene que firmar alguien que se queda adentro. Quien se va del Grupo le
    pide a un compañero de equipo que lo saque, que además es como pasa afuera.
    """
    otro = _del_equipo(sesion, educador_id, usuario)
    if otro.id == usuario.id:
        raise HTTPException(
            400,
            "No podés darte de baja vos mismo: pedíselo a otra persona del equipo.",
        )
    if not otro.activo:
        raise HTTPException(400, "Esa persona ya está fuera del equipo.")

    cuentas.dar_de_baja(sesion, otro)
    sesion.commit()
    return redirigir("/educadores")


@router.post("/educadores/{educador_id}/reincorporar")
def reincorporar_educador(
    educador_id: int,
    usuario: Usuario = Depends(solo_educador),
    sesion: Session = Depends(obtener_sesion),
):
    """Vuelve al equipo, con la contraseña que tenía. Una baja por error se arregla acá."""
    otro = _del_equipo(sesion, educador_id, usuario)
    if otro.activo:
        raise HTTPException(400, "Esa persona ya está en el equipo.")

    cuentas.reincorporar(otro)
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
        # La otra mitad de la etapa: cargos, especialidades y en qué estuvo.
        periodos=vida_de_patrulla.periodos_de(sesion, joven),
        especialidades=especialidades.de(sesion, joven),
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
    elif accion == "acordar":
        # La carta ya está cerrada por su dueño y ya cuenta. Esto no la aprueba:
        # deja escrito que la conversación del cap. 9 ocurrió.
        if not elegida.lograda:
            raise HTTPException(400, "Esa carta todavía no está cerrada.")
        progresion.acordar_carta(elegida, usuario, nota)
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
