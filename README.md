# Retos de Unidad

Aplicación web para una Unidad Scout (Rama Scouts): los jóvenes protagonistas
reciben retos diarios —derivados de las Cartas de Exploración o escritos por el
equipo de educadores—, entregan la evidencia de lo que hicieron, y esa entrega
se valida y suma puntos **a la patrulla**.

## Cómo arrancar

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python scripts/inicializar_db.py --demo
python main.py
```

En http://127.0.0.1:8000 — usuarios de prueba `educador`, `ana`, `bruno`,
`cami`, `dante`, `eli`, todos con contraseña `scout1907`.

Sin `--demo` se crean las tablas y se cargan las cartas, pero ningún usuario:
para producción hay que dar de alta el primer educador a mano.

Probado sobre **Python 3.14**.

## Cómo está armado

FastAPI sirve las dos cosas desde un solo proceso: las páginas HTML con Jinja2
—el mismo motor de plantillas que usa Flask— y una API JSON en `/api`. No hay
un segundo framework en juego: una sola sesión, una sola configuración, un solo
despliegue, y la API ya lista si más adelante querés una app móvil.

```
app/
  main.py            arranque, middleware de sesión, manejo de errores
  config.py          variables de entorno
  db.py              motor SQLite + sesión por request
  models.py          el modelo de datos, con el vocabulario del método
  seguridad.py       hash de contraseñas (scrypt, sin dependencias)
  dependencias.py    usuario de sesión y guardas por rol
  routers/
    auth.py          ingreso y salida
    joven.py         hoy, reto, mis retos, mis cartas, bitácora
    educador.py      panel, validaciones, retos, asignar, patrullas, jóvenes
    api.py           la misma lógica en JSON
  servicios/
    retos.py         qué reto ve cada joven hoy
    validacion.py    contrato de validación de evidencias
    puntajes.py      tablero de patrullas y rachas
    progresion.py    cartas elegidas y avance de cada joven
    medios.py        compresión de fotos y enlaces de video
datos/
  cartas_exploracion.json   las 53 competencias y sus 376 desafíos
scripts/
  inicializar_db.py     crea tablas y carga las cartas (idempotente)
  probar_circuito.py    prueba de punta a punta sobre una base temporal
```

## Decisiones que vale la pena conocer

**El puntaje es de la patrulla, nunca de la persona.** No hay ranking de
jóvenes ni una vista que los ordene por puntos. Lo que aporta cada uno se
guarda —hace falta para acreditar el desafío en su progresión— pero no se
expone como número comparable. La guía de la Rama es explícita en que la
progresión personal no es una carrera por insignias y que la evaluación es
personalizada; un marcador individual empuja justo para el otro lado.

**Un validador automático nunca rechaza.** Puede aprobar o derivar a un
educador, nada más. Rechazar es siempre decisión de una persona. La guía dice
que ante discrepancias entre la evaluación del educador y la autoevaluación del
joven prima la segunda, "es preferible que se exceda en la estimación de sus
logros y no que se afecte su autoestima"; un "no" automático a un chico de 12
sobre una buena acción que efectivamente hizo es exactamente lo que hay que
evitar.

**Si el educador no asigna nada, la app propone un desafío de las cartas.** Es
una red para que la página nunca aparezca vacía, no un reemplazo: la elección es
determinista por (unidad, fecha), así que toda la Unidad ve el mismo reto y
recargar no lo cambia. En cuanto el educador asigna algo para ese día, el
automático deja de aparecer.

**Los puntos quedan en la patrulla donde se ganaron.** Cada entrega guarda una
copia del `patrulla_id` del momento; si el joven se cambia de patrulla después,
el historial no se mueve con él.

## La progresión personal

Cada joven elige de 12 a 14 cartas para su etapa. Eso vive en `/mis-cartas`, que
tiene dos partes separadas: arriba **las que eligió**, con su avance y el acceso
a trabajarlas; abajo el **catálogo** de las 53 para seguir eligiendo. Elegir una
carta te devuelve al ancla de esa carta, no al principio de la lista.

En `/mis-cartas/{id}` marca cada desafío como hecho y escribe cómo le fue. Eso
es `AvanceDesafio`, y va por etapa: si saca una carta de su elección y después la
vuelve a poner, el trabajo sigue ahí.

**El avance se cuenta sobre los requeridos**, que son los mínimos de la carta.
Los opcionales suman y se muestran, pero no mueven la meta.

**Cumplir todos los requeridos no da la carta por lograda.** La app lo dice
—"conversalo con tu educador/a"— y ahí se queda. Cerrar una competencia es una
conversación entre el joven, su patrulla y el equipo de educadores (cap. 9), no
un contador que llega a cero.

**Lo escrito lo leen tres personas.** `/cartas-de/{joven_id}` es una sola página
de solo lectura para quien la escribió, su patrulla y los educadores, porque es
una sola conversación: autoevaluación, coevaluación y heteroevaluación. Un joven
de otra patrulla recibe 404.

`/mi-patrulla` lista a la patrulla **por nombre, nunca por avance**, y sin
puntos. Misma razón que el tablero: acompañarse no es competir.

## El Libro de Oro

La memoria colectiva de cada patrulla, en `/libro-de-oro/{patrulla_id}`: título,
texto, una foto y un video por página. Es la contraparte de la Bitácora de
Aventura, que es personal. Lo escribe y lo lee la patrulla, más el equipo de
educadores; otra patrulla recibe 404. Borrar puede quien escribió la página, o
un educador —hace falta poder moderar.

### Cuánto ocupa

Es la restricción de diseño de esta parte, y define las dos decisiones:

**Ninguna foto se guarda como vino.** Se reescribe a JPEG con el lado mayor en
1600 px antes de tocar el disco. Una foto de celular de 12 megapíxeles queda
entre 100 y 400 kB según el detalle que tenga: cien páginas con foto ocupan del
orden de 20 a 35 MB. El original no se conserva, y es a propósito. Se ajusta con
`FOTO_LADO_MAXIMO` y `FOTO_CALIDAD`.

Se descarta también el EXIF, que en una foto de celular trae las coordenadas de
dónde se sacó. No queremos guardar dónde vive un chico.

**Ningún video se guarda.** Un minuto de video de celular pesa más que el Libro
de Oro entero de un año. Se guarda el enlace a YouTube o Vimeo y se muestra su
reproductor: cero bytes en disco y cero ancho de banda al servirlo. La
recomendación en pantalla es subirlo como **no listado**, para que no aparezca
en búsquedas y solo entre quien tiene el link.

Del enlace se guardan el servicio y el identificador, nunca la URL cruda: la del
reproductor la arma `servicios/medios.py`. El host se valida contra una lista
blanca —buscar `youtu.be/xxx` dentro del texto no alcanza, porque
`https://otro.sitio/youtu.be/xxx.mp4` lo pasaría—. Un `iframe` con `src` armado
a partir de un formulario es una puerta abierta.

El panel del educador muestra cuánto disco llevan usado las fotos.

## La validación con IA

La interfaz está lista y el resto del sistema ya trabaja contra ella; falta
enchufar el modelo. En `app/servicios/validacion.py`:

- `ContextoValidacion` — todo lo que un validador necesita para opinar.
- `ResultadoValidacion` — veredicto (`aprobada` o `requiere_revision`),
  devolución en texto y confianza.
- `Validador` — el protocolo a implementar.

Hay dos implementaciones: `ValidadorManual` (todo va a la cola del educador) y
`ValidadorSimulado` (revisa que la evidencia esté completa —que haya foto si se
pidió, que el relato tenga sustancia— pero no juzga el contenido). Se elige con
`VALIDADOR=manual|simulado`.

Para sumar el de IA: escribir la clase, registrarla en `_VALIDADORES` y cambiar
la variable de entorno. No hay que tocar ningún otro archivo.

## Los desafíos y su tipo

Cada desafío está clasificado según las cartas impresas:

| tipo | qué significa |
|---|---|
| `requerido` | los mínimos indispensables para lograr la competencia |
| `opcional` | enriquecen; pueden reemplazar a un requerido conversándolo con el equipo de educadores |
| `especialidad` | especialidades, insignias e iniciativas, y roles de patrulla — la guía los cuenta dentro de los opcionales |

Cuántos hay de cada uno lo imprime `inicializar_db.py` al cargar. No está escrito
acá a propósito: la clasificación se sigue afinando contra las cartas impresas y
un número congelado en el README envejece mal.

Los de tipo `especialidad` quedan fuera del sorteo del reto diario automático:
"desarrollo la especialidad de cocina" o "me desempeño como tesorero por un
ciclo de programa" son recorridos de meses, no algo que se entregue hoy. El
educador sí puede armar un reto a partir de ellos si quiere.

### Si corregís una clasificación

El JSON es la **semilla**, no lo que lee la página: la app consulta `scout.db`.
Editar `datos/cartas_exploracion.json` no cambia nada hasta volver a cargarlo.

```bash
python scripts/inicializar_db.py
```

Es idempotente y no toca usuarios, entregas ni puntajes: solo reescribe áreas,
competencias y desafíos. El JSON manda para el `texto` y para el `tipo` (donde
traiga `null` respeta lo que ya haya en la base).

## Probar

```bash
pip install -r requirements-dev.txt
python scripts/probar_circuito.py
```

Recorre lo que importa de punta a punta: un joven entra, ve el reto del día,
entrega, el validador decide, el educador confirma, los puntos aparecen en la
patrulla. Usa una base de datos temporal, no toca `scout.db`.

## Antes de ponerlo en producción

- Definir `CLAVE_SECRETA` (ver `.env.example`). Sin eso las sesiones se
  invalidan en cada reinicio y el valor por defecto es público.
- Servir por HTTPS y poner `https_only=True` en el `SessionMiddleware`
  (`app/main.py`).
- Las fotos viven en `uploads/`, fuera de la base. Entran en el backup por
  separado: si copiás solo `scout.db`, el Libro de Oro queda sin imágenes.
- `/fotos/{nombre}` pide sesión, pero no comprueba a qué patrulla pertenece cada
  archivo: alguien con cuenta que consiga la URL de una foto de otra patrulla la
  puede abrir. El nombre es un uuid y solo aparece en páginas a las que esa
  persona no entra, así que hay que conseguirlo a propósito. Si el grupo crece,
  vale atar cada archivo a su entrada y verificar el permiso ahí.
- SQLite aguanta bien una Unidad. Si esto crece a varios grupos, migrar a
  PostgreSQL es cambiar `BASE_DATOS_URL`, pero conviene sumar Alembic para las
  migraciones antes de tener datos que no se puedan perder.

## Documentación de referencia

`Docs/` tiene los 10 capítulos de la Guía de la Rama Scouts, las Cartas de
Exploración, el Manual Scout de Cabullería y el de tipos de fuego. El capítulo 9
(progresión personal) y el 4 (sistema de equipos) son los que definen el modelo
de datos de esta aplicación.
