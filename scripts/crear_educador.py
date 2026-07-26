"""Da de alta un educador desde la consola.

    python scripts/crear_educador.py educador "Nombre y Apellido" "la-contraseña"

Existe para romper un círculo: los jóvenes los da de alta un educador desde la
pantalla, pero al primer educador no lo puede crear nadie. En una base recién
inicializada no hay ninguna cuenta, así que sin esto no se puede ni entrar.

También sirve para sumar el resto del equipo de educadores, que tampoco tiene
un alta propia en la aplicación.

Si no existe ninguna Unidad todavía la crea, porque un usuario sin Unidad no
puede ver nada. Si el nombre de usuario ya está tomado no lo pisa: avisa y sale
con error, que es lo que corresponde cuando lo que se pide es un alta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if not (RAIZ / "app").is_dir():
    # Corriendo desde fuera del repositorio —por ejemplo, subido al volumen del
    # servidor para no tener que reconstruir la imagen—. Ahí el paquete está en
    # el directorio de trabajo, que en el contenedor es /app.
    RAIZ = Path.cwd()
sys.path.insert(0, str(RAIZ))

from sqlalchemy import select  # noqa: E402

from app.db import SesionLocal  # noqa: E402
from app.models import ROL_EDUCADOR, Unidad, Usuario  # noqa: E402
from app.seguridad import hashear_clave  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Da de alta un educador.")
    parser.add_argument("usuario", help="con qué nombre ingresa")
    parser.add_argument("nombre", help="cómo se llama, para mostrar en pantalla")
    parser.add_argument("clave", help="su contraseña")
    parser.add_argument("--unidad", default="Unidad Scout", help="solo si hay que crearla")
    parser.add_argument("--grupo", default="Grupo Scout", help="solo si hay que crearla")
    args = parser.parse_args()

    login = args.usuario.strip().lower()

    with SesionLocal() as sesion:
        if sesion.scalar(select(Usuario.id).where(Usuario.usuario == login)) is not None:
            print(f"El usuario «{login}» ya existe. No se tocó nada.")
            return 1

        unidad = sesion.scalar(select(Unidad))
        if unidad is None:
            unidad = Unidad(nombre=args.unidad, grupo=args.grupo)
            sesion.add(unidad)
            sesion.flush()
            print(f"Se creó la Unidad «{unidad.nombre}» del {unidad.grupo}.")

        sesion.add(
            Usuario(
                usuario=login,
                nombre=args.nombre.strip(),
                hash_clave=hashear_clave(args.clave),
                rol=ROL_EDUCADOR,
                unidad_id=unidad.id,
            )
        )
        sesion.commit()

    print(f"Educador «{login}» dado de alta. Ya puede entrar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
