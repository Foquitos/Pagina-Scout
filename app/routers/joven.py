"""Lo que ve y hace un joven protagonista."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import aparatos, tiempo
from app.db import obtener_sesion
from app.dependencias import (
    fragmento,
    quiere_json,
    redirigir,
    render,
    solo_joven,
    usuario_actual,
)
from app.models import (
    ALCANCE_JOVEN,
    ALCANCE_PATRULLA,
    ESTADO_APROBADA,
    ESTADO_REVISION,
    ETAPAS_NOMBRE,
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
from app.servicios import (
    agenda,
    cumpleanos,
    medios,
    moderacion,
    muro,
    pausas,
    progresion,
    puntajes,
    rastros,
    retos,
)
from app.servicios import patrulla as vida_de_patrulla
from app.servicios.progresion import MAX_CARTAS, MIN_CARTAS
from app.servicios.validacion import ContextoValidacion, obtener_validador

router = APIRouter()


def _guardar_foto(archivo: UploadFile) -> str:
    """Toda foto pasa por el servicio de medios: se comprime antes de ir a disco."""
    return _guardar_contenido(archivo.filename, _leer_foto(archivo))


def _leer_foto(archivo: UploadFile) -> bytes:
    try:
        return medios.leer_subida(archivo)
    except medios.MedioInvalido as error:
        raise HTTPException(400, str(error)) from error


def _guardar_contenido(nombre: str | None, contenido: bytes) -> str:
    try:
        return medios.guardar_foto(nombre, contenido)
    except medios.MedioInvalido as error:
        raise HTTPException(400, str(error)) from error


# Cuánto se lee de la cabecera del original. Los bloques de metadatos de un JPEG
# van pegados al principio del archivo, así que con esto sobra de sobra.
CABECERA_MAXIMA = 1024 * 1024


def _senales_de_la_foto(cabecera: UploadFile | None, contenido: bytes) -> medios.SenalesFoto:
    """Lo que la foto trae escrito adentro, leído del original.

    Hace falta el original y no lo que se subió: `app/static/app.js` achica la
    foto en el celular antes de mandarla —para no gastarle los datos a quien la
    sube— y esa copia sale de un lienzo, o sea sin un solo metadato. Por eso el
    formulario manda aparte los primeros kilobytes del archivo tal como salió de
    la cámara, que es donde viven la marca del teléfono y el sello C2PA.

    Sin JavaScript no hay copia achicada ni cabecera: sube el original entero y
    los metadatos se leen de ahí. Las dos formas terminan en el mismo lugar.
    """
    if cabecera is not None and cabecera.filename:
        try:
            crudo = medios.leer_subida(cabecera, tope=CABECERA_MAXIMA)
        except medios.MedioInvalido:
            crudo = b""
        if crudo:
            return medios.senales_de_foto(crudo)
    return medios.senales_de_foto(contenido)


def _como_se_escribio(request: Request, pegado: int, tecleado: int, segundos: int):
    """Lo que contó el navegador, junto con el aparato del que vino el pedido."""
    return rastros.ComoSeEscribio(
        aparato=aparatos.de(request),
        pegado=pegado,
        tecleado=tecleado,
        segundos=segundos,
    )


@router.get("/hoy")
def hoy(
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    if usuario.unidad_id is None:
        return render(request, "joven/hoy.html", usuario=usuario, asignaciones=[],
                      fecha=retos.hoy(), cumples=[], sin_telefono=[], mi_pausa=None)

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
        # Lo que viene y lo que se comprometió. Un acuerdo que se queda en un
        # acta es una anotación; uno que te espera al entrar es un compromiso.
        proximas=agenda.proximas(sesion, usuario, fecha, tope=3),
        acuerdos=vida_de_patrulla.acuerdos_a_cargo_de(sesion, usuario),
        # Quién cumple años en los próximos días. Sin la edad: acá se muestra
        # para saludar, y para eso alcanza con el día. Ver `servicios/cumpleanos.py`.
        cumples=cumpleanos.proximos(sesion, usuario.unidad_id, fecha, dias=14, tope=5),
        # Quién de la patrulla está sin teléfono. Acá y no en una pantalla
        # aparte: si esto no aparece donde todos entran todos los días, cargarle
        # los retos a alguien es algo que no se le ocurre a nadie.
        sin_telefono=pausas.a_quienes_puede_cargar(sesion, usuario, fecha),
        # Y si el que está en pausa es él. Puede llegar acá igual —una compu
        # prestada, el teléfono de la casa— y tiene derecho a saber qué está
        # pasando con su nombre.
        mi_pausa=pausas.vigente(sesion, usuario.id, fecha),
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


def _registrar_entrega(
    sesion: Session,
    asignacion: Asignacion,
    joven: Usuario,
    texto: str,
    foto: UploadFile | None,
    compartir: bool,
    como: rastros.ComoSeEscribio,
    cabecera: UploadFile | None = None,
    dictada_por: Usuario | None = None,
) -> Entrega | None:
    """Guarda la evidencia y la pasa por el validador. `None` si ya estaba validada.

    Es el mismo camino para las dos formas de entregar —el joven desde su
    teléfono, o alguien cargando lo que le dictó porque no tiene— y por eso está
    en una sola función: si mañana cambia cómo se valida o cómo se puntúa, cambia
    para las dos. La única diferencia es la firma de `dictada_por`, que después
    se muestra en todas partes.
    """
    ya_entregada = sesion.scalar(
        select(Entrega).where(
            Entrega.asignacion_id == asignacion.id, Entrega.joven_id == joven.id
        )
    )
    if ya_entregada is not None and ya_entregada.estado == ESTADO_APROBADA:
        return None

    nombre_foto = None
    senales_foto = None
    if foto is not None and foto.filename:
        contenido = _leer_foto(foto)
        # Se mira lo que la foto trae adentro **antes** de guardarla: al guardarla
        # se le borra el EXIF entero, que es lo correcto porque ahí va el GPS.
        senales_foto = _senales_de_la_foto(cabecera, contenido)
        nombre_foto = _guardar_contenido(foto.filename, contenido)

    entrega = ya_entregada or Entrega(
        asignacion_id=asignacion.id,
        joven_id=joven.id,
        patrulla_id=joven.patrulla_id,
    )
    entrega.texto = texto.strip()
    if nombre_foto:
        # La foto que se reemplaza se va del disco. Antes quedaba ahí para
        # siempre, sin nada que la referenciara y accesible por su dirección:
        # una foto de un chico que ya nadie sabía que existía.
        medios.borrar_foto(entrega.archivo_foto)
        entrega.archivo_foto = nombre_foto
    entrega.enviada_en = tiempo.ahora()
    entrega.patrulla_id = joven.patrulla_id
    # Se pisa en las dos direcciones, y la segunda importa: si el chico recupera
    # el teléfono y reescribe lo que le habían cargado, la firma se va. Volvió a
    # ser lo que escribió él, y decir que la cargó otro sería mentir.
    entrega.dictada_por_id = dictada_por.id if dictada_por else None

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
    # La devolución que había era sobre la entrega vieja. Si la escribió alguien
    # del equipo, su firma se va con ella: dejarla puesta haría pasar por suyo el
    # texto que acaba de escribir el validador automático.
    entrega.devolucion_por_id = None
    entrega.devolucion_en = None
    entrega.validador = resultado.validador
    entrega.validada_en = tiempo.ahora() if resultado.estado == ESTADO_APROBADA else None
    entrega.puntaje_otorgado = reto.puntaje if resultado.estado == ESTADO_APROBADA else 0

    # De qué aparato salió y cómo entró el texto. Se anota siempre, se haya visto
    # algo o no: el rastro de las entregas normales es lo que le da sentido al de
    # las otras, y una tabla que solo tuviera lo sospechoso sería una lista de
    # sospechosos. El `flush` es para que la entrega y su rastro existan en la
    # base antes de contar cuántas cuentas usaron este aparato: sin él, la que se
    # está recibiendo —que es la que completa el patrón— no se contaría.
    rastros.anotar(sesion, entrega, como, senales_foto)
    sesion.add(entrega)
    sesion.flush()

    # Señales fuertes: no se valida sola y la mira una persona. **No la rechaza**,
    # que sigue siendo decisión de un educador (ver `servicios/validacion.py`), y
    # al joven le dice lo mismo que a cualquiera que quedó esperando: qué se vio
    # es para el equipo, porque contarle cuál fue la señal es enseñarle a
    # esquivarla. Que esto se registra sí se le dice, y antes de que escriba: lo
    # avisa el propio formulario de entrega.
    if entrega.estado == ESTADO_APROBADA and rastros.hay_que_mirarla(sesion, entrega):
        entrega.estado = ESTADO_REVISION
        entrega.devolucion = "Tu entrega quedó a la espera de que la mire un educador."
        entrega.validada_en = None
        entrega.puntaje_otorgado = 0

    # Al muro solo va lo validado. Si pidió compartirlo y todavía se está
    # mirando, la marca queda apagada y se puede prender después desde la
    # entrega: no se publica algo que la Unidad no dio por hecho.
    entrega.compartida = compartir and muro.puede_compartir(entrega)
    # Cuándo se publicó, para que el equipo lo vea arriba en /novedades.
    entrega.compartida_en = tiempo.ahora() if entrega.compartida else None

    return entrega


@router.post("/reto/{asignacion_id}")
def entregar_reto(
    asignacion_id: int,
    request: Request,
    texto: str = Form(""),
    compartir: bool = Form(False),
    foto: UploadFile | None = File(None),
    # Lo que midió el navegador mientras se escribía, y la cabecera del original
    # de la foto. Los cuatro vienen con valor por defecto porque sin JavaScript no
    # llega ninguno, y sin JavaScript se tiene que poder entregar igual: es el
    # celular prestado de un chico de doce. Ver `servicios/rastros.py`.
    pegado: int = Form(0),
    tecleado: int = Form(0),
    segundos: int = Form(0),
    foto_cabecera: UploadFile | None = File(None),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    asignacion = _asignacion_visible(sesion, asignacion_id, usuario)
    _registrar_entrega(
        sesion,
        asignacion,
        usuario,
        texto,
        foto,
        compartir,
        como=_como_se_escribio(request, pegado, tecleado, segundos),
        cabecera=foto_cabecera,
    )
    sesion.commit()
    return redirigir(f"/reto/{asignacion.id}")


# --- Cargar lo que hizo alguien que está sin teléfono -------------------------
#
# Que la pausa lo saque del divisor del tablero le arregla el número a su
# patrulla, pero a él no le devuelve nada: sigue sin poder registrar lo que hace
# y su progresión se frena igual. Esto es la otra mitad. Le cuenta a alguien lo
# que hizo y esa persona lo escribe; la entrega es suya, le suma a su patrulla y
# le cuenta para su carta, con la firma de quien la tipeó a la vista.
#
# Pueden hacerlo un educador o alguien de su misma patrulla. Los compañeros no
# están por comodidad: los retos son diarios, el educador no está todos los días
# y el Guía sí. Es para lo que existe el sistema de patrullas (cap. 4).
#
# Lo que no se hace por otro es **publicar en el muro**: compartir lo decide
# quien lo hizo (ver `servicios/muro.py`), así que esto nace sin compartir y el
# interruptor lo aprieta su dueño cuando recupera el teléfono.


def _a_quien_le_cargo(sesion: Session, joven_id: int, quien: Usuario, dia):
    """El joven en pausa y su pausa, si esta persona le puede cargar entregas.

    Un 404 y no un 403 cuando no corresponde: mismo criterio que el resto de la
    aplicación —el Libro de Oro de otra patrulla tampoco «existe»—, así que de
    acá no se deduce quién está sin teléfono en una patrulla que no es la tuya.
    """
    joven = sesion.get(Usuario, joven_id)
    if joven is None or not joven.activo or joven.es_educador:
        raise HTTPException(404, "Esa persona no está en tu Unidad.")
    pausa = pausas.vigente(sesion, joven.id, dia)
    if not pausas.puede_dictar(quien, joven, pausa):
        raise HTTPException(404, "Esa persona no está en tu Unidad.")
    return joven, pausa


@router.get("/sin-telefono/{joven_id}")
def cargar_lo_que_hizo(
    joven_id: int,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Los retos de los días que estuvo sin teléfono, para cargarlos uno por uno."""
    fecha = retos.hoy()
    joven, pausa = _a_quien_le_cargo(sesion, joven_id, usuario, fecha)
    pendientes = pausas.retos_a_cargar(sesion, joven, pausa, fecha)
    return render(
        request,
        "sin_telefono.html",
        usuario=usuario,
        joven=joven,
        pausa=pausa,
        fecha=fecha,
        pendientes=pendientes,
        faltan=pausas.cuantos_faltan(pendientes),
        dias_para_atras=pausas.DIAS_PARA_ATRAS,
    )


@router.post("/sin-telefono/{joven_id}/reto/{asignacion_id}")
def dictar_entrega(
    joven_id: int,
    asignacion_id: int,
    request: Request,
    texto: str = Form(""),
    foto: UploadFile | None = File(None),
    pegado: int = Form(0),
    tecleado: int = Form(0),
    segundos: int = Form(0),
    foto_cabecera: UploadFile | None = File(None),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Carga la entrega de otro. Queda a su nombre, firmada por quien la escribió."""
    fecha = retos.hoy()
    joven, _ = _a_quien_le_cargo(sesion, joven_id, usuario, fecha)
    # El alcance del reto se mide contra **él**, no contra quien está cargando:
    # el reto puede ser de su patrulla, y quien carga puede ser un educador que
    # no está en ninguna.
    asignacion = _asignacion_visible(sesion, asignacion_id, joven)

    # El rastro se anota igual, y el aparato que queda es el de quien escribe.
    # Que sea el de otro es lo esperado acá y no cuenta como cuenta compartida:
    # esto está firmado en `dictada_por_id` y lo habilitó el equipo, así que
    # `servicios/rastros.py` lo deja expresamente afuera de esa cuenta.
    _registrar_entrega(
        sesion,
        asignacion,
        joven,
        texto,
        foto,
        compartir=False,
        como=_como_se_escribio(request, pegado, tecleado, segundos),
        cabecera=foto_cabecera,
        dictada_por=usuario,
    )
    sesion.commit()
    return redirigir(f"/sin-telefono/{joven.id}")


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


@router.get("/muro")
def ver_muro(
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Lo que cada uno quiso mostrar de lo que hizo.

    Ver que otro lo hizo es lo que más empuja a un chico de doce a hacerlo. Acá
    no hay puntos al lado de ningún nombre: el muro muestra qué hizo cada uno,
    nunca cuánto sumó.
    """
    if usuario.unidad_id is None:
        return render(request, "muro.html", usuario=usuario, publicaciones=[], avisados=set())
    avisados, _ = moderacion.avisados_por(sesion, usuario)
    return render(
        request,
        "muro.html",
        usuario=usuario,
        publicaciones=muro.publicaciones(sesion, usuario.unidad_id),
        avisados=avisados,
    )


@router.post("/reto/{asignacion_id}/compartir")
def compartir_entrega(
    asignacion_id: int,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """Prende o apaga el compartir. Lo decide quien la escribió, y solo esa persona."""
    asignacion = _asignacion_visible(sesion, asignacion_id, usuario)
    entrega = sesion.scalar(
        select(Entrega).where(
            Entrega.asignacion_id == asignacion.id, Entrega.joven_id == usuario.id
        )
    )
    if entrega is None:
        raise HTTPException(404, "Todavía no entregaste este reto.")
    if not muro.puede_compartir(entrega):
        raise HTTPException(
            400, "Se comparte cuando la entrega está validada."
        )

    muro.alternar(entrega, usuario)
    sesion.commit()
    return redirigir(f"/reto/{asignacion.id}#compartir")


# --- Avisar al equipo ---------------------------------------------------------
#
# Acá se publica en el momento, sin que un adulto lo mire antes. Esto es la
# contraparte: quien ve algo que no debería estar puede decirlo en dos toques,
# sin esperar a la reunión del sábado. Sobre todo quien aparece en la foto.
#
# No oculta nada. Pone la publicación arriba de todo en `/novedades` para que la
# mire un educador, que es quien decide. Ver `servicios/moderacion.py`.


@router.post("/muro/{entrega_id}/avisar")
def avisar_del_muro(
    entrega_id: int,
    motivo: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    entrega = sesion.get(Entrega, entrega_id)
    # Solo se avisa de lo que se está viendo: si no está en el muro de tu
    # Unidad, para vos no existe y tampoco hay de qué avisar.
    if (
        entrega is None
        or entrega.asignacion.unidad_id != usuario.unidad_id
        or not entrega.en_el_muro
    ):
        raise HTTPException(404, "Esa publicación no existe.")

    try:
        moderacion.avisar(sesion, usuario, motivo, entrega=entrega)
    except moderacion.NoSePuede as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()
    return redirigir("/muro")


@router.post("/libro-de-oro/{patrulla_id}/{entrada_id}/avisar")
def avisar_del_libro(
    patrulla_id: int,
    entrada_id: int,
    motivo: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    _patrulla_visible(sesion, patrulla_id, usuario)
    entrada = sesion.get(EntradaLibroOro, entrada_id)
    if entrada is None or entrada.patrulla_id != patrulla_id or entrada.oculta:
        raise HTTPException(404, "Esa página no existe.")

    try:
        moderacion.avisar(sesion, usuario, motivo, pagina=entrada)
    except moderacion.NoSePuede as error:
        raise HTTPException(400, str(error)) from error
    sesion.commit()
    return redirigir(f"/libro-de-oro/{patrulla_id}")


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

    # Lo ya logrado en otra etapa sale del catálogo: esa competencia la
    # desarrolló, no hay nada que volver a elegir. Sigue estando en el historial.
    logradas_antes = progresion.logradas_de_otras_etapas(sesion, usuario)
    catalogo = [c for c in competencias if c.id not in logradas_antes]

    return render(
        request,
        "joven/mis_cartas.html",
        usuario=usuario,
        areas=areas,
        competencias=catalogo,
        avances=avances,
        elegidas={a.elegida.competencia_id: a.elegida for a in avances},
        historial=progresion.historial_de_cartas(sesion, usuario),
        min_cartas=MIN_CARTAS,
        max_cartas=MAX_CARTAS,
        total_cartas=len(competencias),
        en_catalogo=len(catalogo),
        logradas_antes=len(logradas_antes),
    )


@router.post("/mis-cartas/{competencia_id}")
def alternar_carta(
    competencia_id: int,
    request: Request,
    quedarse: bool = Form(False),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    # Sin JavaScript vuelve al ancla de la carta: elegir la número 47 no
    # debería devolverte al principio de una lista de 53. `quedarse` lo manda
    # la página de la carta, que es donde ya estabas; no viaja ninguna URL del
    # navegador, así que no hay a dónde desviar a nadie.
    destino = f"/mis-cartas/{competencia_id}" if quedarse else f"/mis-cartas#carta-{competencia_id}"

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
    else:
        if sesion.get(Competencia, competencia_id) is None:
            raise HTTPException(404, "Esa carta no existe.")
        # No está en el catálogo, pero el formulario podría llegar igual: de una
        # pestaña vieja, o del atajo de alguien curioso.
        ya_lograda = progresion.carta_de_otra_etapa(sesion, usuario, competencia_id)
        if ya_lograda is not None:
            raise HTTPException(
                400,
                f"Esa carta ya la lograste en la etapa "
                f"{ETAPAS_NOMBRE.get(ya_lograda.etapa, ya_lograda.etapa)}. "
                f"Está guardada en tu historial.",
            )
        sesion.add(
            CompetenciaElegida(
                joven_id=usuario.id, competencia_id=competencia_id, etapa=usuario.etapa
            )
        )
        sesion.commit()

    if quiere_json(request):
        return _eleccion_al_dia(sesion, usuario, competencia_id)
    return redirigir(destino)


def _eleccion_al_dia(sesion: Session, joven: Usuario, competencia_id: int) -> dict:
    """Lo que cambia en /mis-cartas al elegir o sacar una carta.

    Se devuelve el pedazo de página ya armado por Jinja y los contadores
    sueltos. Volver a mandar las 53 cartas para cambiar un botón sería tirar
    a la basura casi todo lo que se transmite.
    """
    avances = progresion.cartas_elegidas(sesion, joven)
    cuentas: dict[str, int] = {
        "elegidas": len(avances),
        "logradas": sum(1 for a in avances if a.elegida.lograda),
    }
    # Todas las áreas, no solo las que tienen cartas elegidas: si un área
    # queda en cero, ese cero también tiene que llegar a la pantalla.
    for area_id in sesion.scalars(select(Area.id)):
        cuentas[f"area-{area_id}"] = sum(
            1 for a in avances if a.competencia.area_id == area_id
        )

    elegida = any(a.elegida.competencia_id == competencia_id for a in avances)
    return {
        "elegida": elegida,
        "aviso": "Carta agregada a tu elección." if elegida else "Carta sacada de tu elección.",
        "cuentas": cuentas,
        "fragmentos": {
            "#eleccion": fragmento(
                "joven/_eleccion.html",
                avances=avances,
                min_cartas=MIN_CARTAS,
                max_cartas=MAX_CARTAS,
            )
        },
    }


def _pagina_de_carta(
    request: Request,
    sesion: Session,
    usuario: Usuario,
    competencia_id: int,
    **extra,
):
    """La página de una carta. La arman el GET y el cierre que pide confirmar."""
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
    de_otra_etapa = None if elegida else progresion.carta_de_otra_etapa(sesion, usuario, competencia_id)
    if de_otra_etapa is not None:
        elegida = de_otra_etapa
    marcas = progresion.marcas_de(sesion, usuario, elegida.etapa if elegida else None)

    contexto = {
        "usuario": usuario,
        "competencia": competencia,
        "desafios": progresion.desafios_de(sesion, competencia_id),
        "elegida": elegida,
        "marcas": marcas,
        "avance": progresion.avance_de_carta(elegida, marcas) if elegida else None,
        "de_otra_etapa": de_otra_etapa,
        "preguntas": progresion.PREGUNTAS_AUTOEVALUACION,
        "confirmar": "",
        "borrador": "",
    }
    contexto.update(extra)
    return render(request, "joven/carta.html", **contexto)


@router.get("/mis-cartas/{competencia_id}")
def trabajar_carta(
    competencia_id: int,
    request: Request,
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """La página de trabajo de una carta: marcar desafíos y comentarlos.

    Si la carta la logró en una etapa anterior, la misma página la muestra
    cerrada y de solo lectura, con lo que había escrito entonces: no se puede
    volver a elegir ni a marcar, pero tampoco desaparece.
    """
    return _pagina_de_carta(request, sesion, usuario, competencia_id)


@router.post("/mis-cartas/{competencia_id}/cerrar")
def cerrar_mi_carta(
    competencia_id: int,
    request: Request,
    autoevaluacion: str = Form(""),
    confirmado: bool = Form(False),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    """El joven cierra su propia carta (cap. 9).

    «La joven o el joven son los principales protagonistas de la evaluación de la
    progresión personal.» No pide permiso: cuando el equipo no coincide, la guía
    dice que «siempre primará la autoevaluación». Lo que queda pendiente después
    de esto no es una autorización, es una conversación.
    """
    elegida = progresion.carta_elegida(sesion, usuario, competencia_id)
    if elegida is None:
        raise HTTPException(404, "Esa carta no está en tu elección de esta etapa.")
    if elegida.lograda:
        return redirigir(f"/mis-cartas/{competencia_id}#cierre")

    avance = progresion.avance_de_carta(elegida, progresion.marcas_de(sesion, usuario))
    try:
        progresion.cerrar_carta_el_joven(
            elegida, avance, usuario, autoevaluacion, confirmado
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except progresion.NecesitaConfirmacion as falta:
        # Faltan requeridos. Acá no se redirige, se vuelve a dibujar la página:
        # lo que la persona escribió no se puede perder en el camino.
        return _pagina_de_carta(
            request,
            sesion,
            usuario,
            competencia_id,
            confirmar=falta.motivo,
            borrador=autoevaluacion,
        )

    sesion.commit()
    return redirigir(f"/mis-cartas/{competencia_id}#cierre")


@router.post("/mis-cartas/{competencia_id}/desafios/{desafio_id}")
def marcar_desafio(
    competencia_id: int,
    desafio_id: int,
    request: Request,
    hecho: bool = Form(False),
    comentario: str = Form(""),
    usuario: Usuario = Depends(solo_joven),
    sesion: Session = Depends(obtener_sesion),
):
    desafio = sesion.get(Desafio, desafio_id)
    if desafio is None or desafio.competencia_id != competencia_id:
        raise HTTPException(404, "Ese desafío no existe.")

    elegida = sesion.scalar(
        select(CompetenciaElegida).where(
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

    if quiere_json(request):
        # No se manda la hora: el servidor guarda en UTC y no tiene por qué
        # saber en qué huso está quien escribe. La pone el navegador.
        de_la_carta = progresion.avance_de_carta(elegida, progresion.marcas_de(sesion, usuario))
        return {
            "hecho": avance.hecho,
            "fragmentos": {
                "#resumen-carta": fragmento("joven/_resumen_carta.html", avance=de_la_carta)
            },
        }
    return redirigir(f"/mis-cartas/{competencia_id}#desafio-{desafio_id}")


# `/mi-patrulla` y todo lo que pasa adentro de una patrulla —cargos, Consejo,
# acuerdos, identidad— vive en `routers/patrulla.py`.


# Las especialidades viven en `routers/especialidades.py`: el catálogo del
# equipo y el recorrido de cada joven son la misma dirección.


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
        historial=progresion.historial_de_cartas(sesion, joven),
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
    # Una página bajada por el equipo la siguen viendo el equipo y su autor, y
    # aparece marcada. Para el resto de la patrulla no está: mostrarla tachada
    # sería publicar dos veces lo que se pidió bajar.
    if not usuario.es_educador:
        entradas = [e for e in entradas if not e.oculta or e.autor_id == usuario.id]
    _, avisados = moderacion.avisados_por(sesion, usuario)
    return render(
        request,
        "libro_oro.html",
        usuario=usuario,
        patrulla=patrulla,
        entradas=entradas,
        hoy=retos.hoy(),
        con_foto=sum(1 for e in entradas if e.archivo_foto),
        con_video=sum(1 for e in entradas if e.video_id),
        avisados=avisados,
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
