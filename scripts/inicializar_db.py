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
    DESAFIO_ESPECIALIDAD,
    DESAFIO_OPCIONAL,
    DESAFIO_REQUERIDO,
    ROL_EDUCADOR,
    ROL_JOVEN,
    Area,
    Competencia,
    Desafio,
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
    },
    # Arranca en 0 y eso es lo correcto: las cuentas que ya existían eligieron su
    # contraseña alguna vez, así que no hay nada que obligarlas a cambiar.
    "usuarios": {
        "debe_cambiar_clave": "BOOLEAN DEFAULT 0",
    },
}


def migrar(motor_) -> int:
    """Agrega las columnas que falten. Idempotente y sin tocar los datos."""
    inspector = inspect(motor_)
    tablas = set(inspector.get_table_names())
    agregadas = 0
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
                agregadas += 1
    return agregadas


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

    if migrar(motor):
        print("Base actualizada con las columnas nuevas.")
    Base.metadata.create_all(motor)
    with SesionLocal() as sesion:
        competencias, desafios = cargar_cartas(sesion)
        print(f"Cartas de Exploración: {competencias} competencias, {desafios} desafíos.")
        if args.demo:
            cargar_demo(sesion)


if __name__ == "__main__":
    main()
