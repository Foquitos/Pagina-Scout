"""Da de alta el primer educador desde la consola.

    python scripts/crear_educador.py educador "Nombre y Apellido"

Existe para romper un círculo: los jóvenes y los demás educadores se dan de alta
desde la pantalla, pero al primero no lo puede crear nadie. En una base recién
inicializada no hay ninguna cuenta, así que sin esto no se puede ni entrar. Una
vez adentro, el resto del equipo se suma desde `/educadores` y esta consola no
hace falta nunca más.

La contraseña no se pide: como toda cuenta, arranca siendo el mismo nombre de
usuario y la aplicación obliga a cambiarla al entrar. Se puede pasar otra como
tercer argumento —por si el usuario es demasiado obvio en un servidor expuesto—
y sigue siendo provisoria igual.

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
from app.models import ROL_EDUCADOR, Unidad  # noqa: E402
from app.servicios import cuentas  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Da de alta un educador.")
    parser.add_argument("usuario", help="con qué nombre ingresa")
    parser.add_argument("nombre", help="cómo se llama, para mostrar en pantalla")
    parser.add_argument(
        "clave",
        nargs="?",
        help="opcional: contraseña provisoria. Por defecto, el mismo nombre de usuario",
    )
    parser.add_argument("--unidad", default="Unidad Scout", help="solo si hay que crearla")
    parser.add_argument("--grupo", default="Grupo Scout", help="solo si hay que crearla")
    args = parser.parse_args()

    with SesionLocal() as sesion:
        unidad = sesion.scalar(select(Unidad))
        if unidad is None:
            unidad = Unidad(nombre=args.unidad, grupo=args.grupo)
            sesion.add(unidad)
            sesion.flush()
            print(f"Se creó la Unidad «{unidad.nombre}» del {unidad.grupo}.")

        try:
            educador = cuentas.alta(
                sesion, args.usuario, args.nombre, ROL_EDUCADOR, unidad_id=unidad.id
            )
        except cuentas.DatoInvalido as error:
            print(f"{error.motivo} No se tocó nada.")
            return 1

        if args.clave:
            cuentas.establecer_provisoria(educador, args.clave)
        sesion.commit()
        login = educador.usuario

    provisoria = "la que pasaste" if args.clave else f"«{login}», su mismo usuario"
    print(f"Educador «{login}» dado de alta. Entra con {provisoria}.")
    print("Al entrar la aplicación le va a pedir que elija una contraseña propia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
