"""Crea las tablas, actualiza el esquema y carga las Cartas de Exploración.

    python scripts/inicializar_db.py                  # tablas + cartas
    python scripts/inicializar_db.py --demo           # + unidad, patrullas y usuarios de prueba

Es idempotente: se puede correr las veces que haga falta. Las cartas se
actualizan desde datos/cartas_exploracion.json sin tocar el resto de los datos,
y sobre una base ya existente se agregan las columnas nuevas antes de nada.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import DIR_DATOS  # noqa: E402
from app.db import Base, SesionLocal, motor  # noqa: E402
from app.models import (  # noqa: E402
    CARGOS_INICIALES,
    DESAFIO_ESPECIALIDAD,
    DESAFIO_OPCIONAL,
    DESAFIO_REQUERIDO,
    ROL_EDUCADOR,
    ROL_JOVEN,
    Area,
    Cargo,
    Competencia,
    Desafio,
    Idea,
    Patrulla,
    Unidad,
    Usuario,
)
from app.seguridad import hashear_clave  # noqa: E402


# Columnas que se sumaron después de la primera versión. `create_all` crea las
# tablas que faltan, pero no toca las que ya existen: sin esto, una base vieja
# se queda sin las columnas nuevas. Cuando esto crezca a varias Unidades hay que
# pasar a Alembic; para una base por grupo, esto alcanza y se lee de un vistazo.
COLUMNAS_NUEVAS = {
    "competencias_elegidas": {
        "lograda_por_id": "INTEGER REFERENCES usuarios(id)",
        "con_pendientes": "BOOLEAN DEFAULT 0",
        "nota_cierre": "TEXT DEFAULT ''",
        "autoevaluacion": "TEXT DEFAULT ''",
        # Las cartas que ya estaban cerradas las cerró un educador conversando:
        # arrancan acordadas, que es lo que efectivamente pasó.
        "acordada": "BOOLEAN DEFAULT 0",
        "acordada_en": "DATETIME",
        "acordada_por_id": "INTEGER REFERENCES usuarios(id)",
    },
    # Arranca en 0 y eso es lo correcto: las cuentas que ya existían eligieron su
    # contraseña alguna vez, así que no hay nada que obligarlas a cambiar.
    "usuarios": {
        "debe_cambiar_clave": "BOOLEAN DEFAULT 0",
        # Vacío para todo el mundo, y se llena a mano. No se puede deducir de
        # nada de lo que ya hay, y adivinarlo sería peor que no tenerlo.
        "nacimiento": "DATE",
    },
    "patrullas": {
        "grito": "TEXT DEFAULT ''",
        "emblema": "VARCHAR(10) DEFAULT ''",
        "historia": "TEXT DEFAULT ''",
        "archivo_banderin": "VARCHAR(255)",
        "fundada_en": "DATE",
    },
    "entregas": {
        # Apagada para lo que ya está entregado: compartir lo que un chico
        # escribió cuando nadie se lo preguntó no se hace retroactivamente.
        "compartida": "BOOLEAN DEFAULT 0",
        # Sin fecha para lo ya compartido. `novedades()` cae en `enviada_en`
        # cuando esto está vacío, así que el feed sale ordenado igual.
        "compartida_en": "DATETIME",
        # Nadie bajó nada todavía: NULL es exactamente eso y es el default.
        "oculta_en": "DATETIME",
        "oculta_por_id": "INTEGER REFERENCES usuarios(id)",
        # Vacío para todo lo que ya está entregado, que es lo correcto: hasta
        # ahora la única forma de entregar era desde el propio teléfono, así que
        # todas las entregas viejas las escribió su dueño.
        "dictada_por_id": "INTEGER REFERENCES usuarios(id)",
        # Vacío para las devoluciones que ya estaban escritas. No se puede saber
        # cuáles las escribió un educador y cuáles el validador automático, y
        # firmar con un nombre equivocado es peor que no firmar: sin esto la
        # pantalla del joven dice «tu educador/a» y con esto dice quién fue.
        "devolucion_por_id": "INTEGER REFERENCES usuarios(id)",
        "devolucion_en": "DATETIME",
    },
    "libro_oro": {
        "oculta_en": "DATETIME",
        "oculta_por_id": "INTEGER REFERENCES usuarios(id)",
    },
    "ideas": {
        "respuesta": "TEXT DEFAULT ''",
    },
}

# Tablas que se fueron. Se borran en vez de quedar dando vueltas: una tabla vacía
# que nadie lee es una pregunta que alguien se va a hacer en dos años.
#
# - `votos` y `asambleas`: la Asamblea se reúne en persona, no vota por la app.
# - `especialidades_ofrecidas`: no hay catálogo, la especialidad la pide el joven.
#
# El orden importa: primero la que referencia, después la referida.
TABLAS_RETIRADAS = ("votos", "asambleas", "especialidades_ofrecidas")


def migrar(motor_) -> int:
    """Agrega las columnas que falten. Idempotente y sin tocar los datos."""
    inspector = inspect(motor_)
    tablas = set(inspector.get_table_names())
    agregadas = 0
    nuevas: set[str] = set()
    with motor_.begin() as conexion:
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            if tabla not in tablas:
                continue  # la va a crear create_all, ya con todo
            existentes = {c["name"] for c in inspector.get_columns(tabla)}
            for nombre, definicion in columnas.items():
                if nombre in existentes:
                    continue
                conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}"))
                print(f"  + {tabla}.{nombre}")
                nuevas.add(f"{tabla}.{nombre}")
                agregadas += 1

        # Las cartas que ya estaban cerradas las cerró un educador después de
        # conversarlas: nacen acordadas. Si arrancaran en cero, la aplicación
        # pediría volver a conversar todo lo que ya se conversó.
        if "competencias_elegidas.acordada" in nuevas:
            conexion.execute(
                text(
                    "UPDATE competencias_elegidas "
                    "SET acordada = 1, acordada_en = lograda_en, "
                    "    acordada_por_id = lograda_por_id "
                    "WHERE lograda = 1"
                )
            )
            print("  · las cartas ya cerradas quedan como acordadas")

        # Las ideas que habían quedado «en la Asamblea» pasan a ser propuestas
        # otra vez: esa Asamblea ahora se hace en persona.
        if "ideas" in tablas:
            conexion.execute(
                text("UPDATE ideas SET estado = 'propuesta' WHERE estado = 'en_asamblea'")
            )
        # `especialidades` cambió de forma mientras se afinaba de quién es cada
        # decisión: la pide el joven —la que quiera— y el recorrido lo prepara el
        # equipo para esa persona. La tabla vieja no se puede migrar campo a
        # campo, así que se rehace. Va **antes** que `TABLAS_RETIRADAS` porque
        # apuntaba al catálogo que ahí se borra, y con las claves foráneas
        # encendidas no se puede borrar un padre que todavía tiene hijos.
        if "especialidades" in tablas:
            columnas = {c["name"] for c in inspector.get_columns("especialidades")}
            if "pedida_en" not in columnas:
                cuantas = conexion.execute(
                    text("SELECT COUNT(*) FROM especialidades")
                ).scalar()
                conexion.execute(text("DROP TABLE especialidades"))
                aviso = "  - especialidades (cambió de forma"
                print(f"{aviso}, se perdieron {cuantas})" if cuantas else f"{aviso})")

        for tabla in TABLAS_RETIRADAS:
            if tabla in tablas:
                conexion.execute(text(f"DROP TABLE {tabla}"))
                print(f"  - {tabla}")
    return agregadas


def rehacer_ideas(motor_) -> bool:
    """Saca `ideas.asamblea_id`, que quedó de cuando se votaba por la aplicación.

    SQLite no sabe borrar una columna que aparece en una clave foránea, así que
    hay que rehacer la tabla entera: renombrar la vieja, dejar que el modelo
    cree la nueva, copiar las filas y tirar la vieja.

    Los dos `PRAGMA` no son decorativos. `foreign_keys=OFF` porque durante el
    cambalache las referencias quedan colgando; `legacy_alter_table=ON` porque
    sin eso el `RENAME` sale a corregir a todas las tablas que apuntan a `ideas`
    —o sea `apoyos_idea`— y las deja apuntando a la tabla vieja.
    """
    inspector = inspect(motor_)
    tablas = set(inspector.get_table_names())

    # Restos de un intento anterior que se cortó por la mitad. Se limpian
    # siempre, aunque el resto ya esté hecho: una tabla huérfana que todavía
    # apunta a `asambleas` impide borrar `asambleas`.
    if "ideas_vieja" in tablas:
        with motor_.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
            conexion.execute(text("PRAGMA foreign_keys=OFF"))
            conexion.execute(text("DROP TABLE ideas_vieja"))
            conexion.execute(text("PRAGMA foreign_keys=ON"))
        print("  - ideas_vieja (quedó de una migración a medias)")

    if "ideas" not in tablas:
        return False
    viejas = {c["name"] for c in inspector.get_columns("ideas")}
    if "asamblea_id" not in viejas:
        return False

    comunes = [c.name for c in Idea.__table__.columns if c.name in viejas]
    lista = ", ".join(comunes)
    # Los índices se van con la tabla renombrada pero conservan su nombre, y
    # entonces el modelo no puede volver a crearlos. Se borran a mano.
    indices = [i["name"] for i in inspector.get_indexes("ideas")]

    # Los PRAGMA no hacen nada adentro de una transacción: hay que ir en
    # autocommit.
    with motor_.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
        conexion.execute(text("PRAGMA foreign_keys=OFF"))
        conexion.execute(text("PRAGMA legacy_alter_table=ON"))
        try:
            conexion.execute(text("ALTER TABLE ideas RENAME TO ideas_vieja"))
            for indice in indices:
                conexion.execute(text(f"DROP INDEX IF EXISTS {indice}"))
            Idea.__table__.create(conexion)
            conexion.execute(
                text(f"INSERT INTO ideas ({lista}) SELECT {lista} FROM ideas_vieja")
            )
            conexion.execute(text("DROP TABLE ideas_vieja"))
        finally:
            conexion.execute(text("PRAGMA legacy_alter_table=OFF"))
            conexion.execute(text("PRAGMA foreign_keys=ON"))
    print("  - ideas.asamblea_id (la Asamblea vota en persona)")
    return True


def asegurar_cargos(sesion: Session) -> int:
    """Cada Unidad arranca con el catálogo de cargos de la guía (cap. 4).

    Se agregan los que falten por nombre, así que sumar un cargo propio a mano no
    se pierde y correr esto de nuevo no duplica nada.
    """
    creados = 0
    for unidad_id in sesion.scalars(select(Unidad.id)):
        existentes = {
            nombre
            for nombre in sesion.scalars(
                select(Cargo.nombre).where(Cargo.unidad_id == unidad_id)
            )
        }
        for orden, (nombre, descripcion) in enumerate(CARGOS_INICIALES):
            if nombre in existentes:
                continue
            sesion.add(
                Cargo(
                    unidad_id=unidad_id,
                    nombre=nombre,
                    descripcion=descripcion,
                    orden=orden,
                )
            )
            creados += 1
    sesion.commit()
    return creados


def cargar_cartas(sesion: Session) -> tuple[int, int]:
    datos = json.loads((DIR_DATOS / "cartas_exploracion.json").read_text(encoding="utf-8"))

    areas: dict[str, Area] = {}
    for item in datos["areas"]:
        area = sesion.scalar(select(Area).where(Area.codigo == item["codigo"]))
        if area is None:
            area = Area(codigo=item["codigo"])
            sesion.add(area)
        area.nombre = item["nombre"]
        area.color = item["color"]
        area.icono = item["icono"]
        area.descripcion = item["descripcion"]
        areas[item["codigo"]] = area
    sesion.flush()

    total_desafios = 0
    for item in datos["competencias"]:
        competencia = sesion.scalar(
            select(Competencia).where(Competencia.numero == item["numero"])
        )
        if competencia is None:
            competencia = Competencia(numero=item["numero"])
            sesion.add(competencia)
        competencia.area_id = areas[item["area"]].id
        competencia.titulo = item["titulo"]
        sesion.flush()

        existentes = {d.orden: d for d in competencia.desafios}
        for d in item["desafios"]:
            desafio = existentes.get(d["orden"])
            if desafio is None:
                desafio = Desafio(competencia_id=competencia.id, orden=d["orden"])
                sesion.add(desafio)
            desafio.texto = d["texto"]
            # El JSON manda donde hay clasificación; donde todavía viene en null
            # respetamos lo que se haya cargado a mano en la base.
            if d["tipo"] is not None:
                desafio.tipo = d["tipo"]
            total_desafios += 1

    sesion.commit()

    censo = Counter(d["tipo"] for c in datos["competencias"] for d in c["desafios"])
    print(
        "  requeridos {requerido}  ·  opcionales {opcional}  ·  "
        "especialidades y roles {especialidad}".format(
            requerido=censo.get(DESAFIO_REQUERIDO, 0),
            opcional=censo.get(DESAFIO_OPCIONAL, 0),
            especialidad=censo.get(DESAFIO_ESPECIALIDAD, 0),
        )
    )

    sin_clasificar = sorted(
        c["numero"]
        for c in datos["competencias"]
        if any(d["tipo"] is None for d in c["desafios"])
    )
    if sin_clasificar:
        print(
            f"Aviso: {len(sin_clasificar)} cartas sin clasificar requerido/opcional "
            f"({sin_clasificar[0]} a {sin_clasificar[-1]})."
        )
    return len(datos["competencias"]), total_desafios


def cargar_demo(sesion: Session) -> None:
    if sesion.scalar(select(Unidad.id)) is not None:
        print("Ya hay datos cargados, se omite el demo.")
        return

    unidad = Unidad(nombre="Unidad Scout", grupo="Grupo Scout")
    sesion.add(unidad)
    sesion.flush()

    patrullas = [
        Patrulla(unidad_id=unidad.id, nombre="Halcones", lema="Siempre más alto", color="#2E86AB"),
        Patrulla(unidad_id=unidad.id, nombre="Pumas", lema="Firmes y unidos", color="#D64550"),
        Patrulla(unidad_id=unidad.id, nombre="Ceibos", lema="Raíces profundas", color="#3E8E5A"),
    ]
    sesion.add_all(patrullas)
    sesion.flush()

    sesion.add(
        Usuario(
            usuario="educador",
            nombre="Educador de prueba",
            hash_clave=hashear_clave("scout1907"),
            rol=ROL_EDUCADOR,
            unidad_id=unidad.id,
        )
    )

    jovenes = [
        ("ana", "Ana", patrullas[0], "senda"),
        ("bruno", "Bruno", patrullas[0], "pistas"),
        ("cami", "Camila", patrullas[1], "rumbo"),
        ("dante", "Dante", patrullas[1], "pistas"),
        ("eli", "Elisa", patrullas[2], "senda"),
    ]
    for login, nombre, patrulla, etapa in jovenes:
        sesion.add(
            Usuario(
                usuario=login,
                nombre=nombre,
                hash_clave=hashear_clave("scout1907"),
                rol=ROL_JOVEN,
                unidad_id=unidad.id,
                patrulla_id=patrulla.id,
                etapa=etapa,
            )
        )

    sesion.commit()
    print("Demo cargado. Usuarios: educador / ana / bruno / cami / dante / eli")
    print("Contraseña para todos: scout1907")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa la base de datos.")
    parser.add_argument("--demo", action="store_true", help="carga datos de prueba")
    args = parser.parse_args()

    # Antes que nada: la tabla `ideas` tiene que quedar sin su vínculo a las
    # asambleas, porque `migrar` va a borrar esas tablas.
    rehacer_ideas(motor)
    if migrar(motor):
        print("Base actualizada con las columnas nuevas.")
    Base.metadata.create_all(motor)
    with SesionLocal() as sesion:
        competencias, desafios = cargar_cartas(sesion)
        print(f"Cartas de Exploración: {competencias} competencias, {desafios} desafíos.")
        if args.demo:
            cargar_demo(sesion)
        if creados := asegurar_cargos(sesion):
            print(f"Cargos de patrulla: {creados} agregados al catálogo.")


if __name__ == "__main__":
    main()
