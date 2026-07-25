"""Validación de evidencias.

Contrato único para que la evidencia la revise un educador, una IA o cualquier
otra cosa que se sume después. Todo lo que hay del otro lado de este módulo
—rutas, plantillas, puntajes— trabaja contra `Validador` y `ResultadoValidacion`,
así que enchufar un validador nuevo no toca nada más.

Regla de diseño, deliberada: un validador automático nunca rechaza.
Puede aprobar o derivar a un educador, nada más. La guía de la Rama es explícita
en que la heteroevaluación es un diálogo y que ante discrepancias prima la
autoevaluación del joven (cap. 9); un "no" automático a un chico de 12 años
sobre una buena acción que efectivamente hizo es exactamente lo que no queremos.
Rechazar es siempre decisión de una persona.

Para sumar el validador con IA:
  1. Crear una clase que implemente `Validador`.
  2. Registrarla en `_VALIDADORES` con una clave.
  3. Poner VALIDADOR=<clave> en el entorno.
No hace falta tocar ningún otro archivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import VALIDADOR
from app.models import ESTADO_APROBADA, ESTADO_REVISION

Veredicto = Literal["aprobada", "requiere_revision"]


@dataclass(frozen=True)
class ContextoValidacion:
    """Todo lo que un validador necesita saber para opinar sobre una entrega."""

    reto_titulo: str
    reto_consigna: str
    texto_evidencia: str
    tiene_foto: bool
    pide_texto: bool
    pide_foto: bool
    desafio_texto: str | None = None
    competencia_titulo: str | None = None
    area_nombre: str | None = None


@dataclass(frozen=True)
class ResultadoValidacion:
    veredicto: Veredicto
    devolucion: str
    confianza: float
    validador: str

    @property
    def estado(self) -> str:
        return ESTADO_APROBADA if self.veredicto == "aprobada" else ESTADO_REVISION


class Validador(Protocol):
    nombre: str

    def validar(self, ctx: ContextoValidacion) -> ResultadoValidacion: ...


class ValidadorManual:
    """No opina: manda todo a la cola del educador."""

    nombre = "manual"

    def validar(self, ctx: ContextoValidacion) -> ResultadoValidacion:
        return ResultadoValidacion(
            veredicto="requiere_revision",
            devolucion="Tu entrega quedó a la espera de que la mire un educador.",
            confianza=0.0,
            validador=self.nombre,
        )


class ValidadorSimulado:
    """Validador de prueba: revisa que la evidencia esté completa, no su contenido.

    Existe para que el circuito completo (entregar → validar → puntos a la
    patrulla) se pueda probar de punta a punta sin depender de un servicio
    externo. Comprueba lo que se pidió y que haya algo de sustancia escrita;
    cualquier cosa más fina que eso la decide un educador.
    """

    nombre = "simulado"
    MINIMO_CARACTERES = 40

    def validar(self, ctx: ContextoValidacion) -> ResultadoValidacion:
        faltantes: list[str] = []
        if ctx.pide_foto and not ctx.tiene_foto:
            faltantes.append("falta la foto que pedía el reto")

        texto = ctx.texto_evidencia.strip()
        if ctx.pide_texto and len(texto) < self.MINIMO_CARACTERES:
            faltantes.append(
                "contanos un poco más: qué hiciste, cómo te salió y para qué sirve"
            )

        if faltantes:
            return ResultadoValidacion(
                veredicto="requiere_revision",
                devolucion="Antes de darlo por hecho, " + " y ".join(faltantes) + ".",
                confianza=0.3,
                validador=self.nombre,
            )

        return ResultadoValidacion(
            veredicto="aprobada",
            devolucion="¡Buen trabajo! Quedó registrado y suma a tu patrulla.",
            confianza=0.6,
            validador=self.nombre,
        )


_VALIDADORES: dict[str, Validador] = {
    "manual": ValidadorManual(),
    "simulado": ValidadorSimulado(),
}


def obtener_validador(clave: str | None = None) -> Validador:
    return _VALIDADORES.get(clave or VALIDADOR, _VALIDADORES["manual"])
