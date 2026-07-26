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
copy .env.example .env             # y poner una CLAVE_SECRETA propia
python scripts/inicializar_db.py --demo
python main.py
```

En http://127.0.0.1:8000 — usuarios de prueba `educador`, `ana`, `bruno`,
`cami`, `dante`, `eli`, todos con contraseña `scout1907`.

El `.env` lo lee `app/config.py` al arrancar y no se versiona: ahí van la clave
secreta y cualquier cosa que no deba viajar en el repositorio. Sin `.env` la
aplicación igual levanta, con los valores por defecto del código. Para generar
una clave: `python -c "import secrets; print(secrets.token_hex(32))"`.

Sin `--demo` se crean las tablas y se cargan las cartas, pero ningún usuario:
para producción hay que dar de alta el primer educador a mano
(`python scripts/crear_educador.py educador "Nombre y Apellido"`). El resto del
equipo se suma después desde la aplicación; ver [Cuentas y
contraseñas](#cuentas-y-contraseñas).

Si ya tenías una base andando, ese mismo comando le agrega las columnas que
falten antes de tocar nada más. Es idempotente y no borra datos; mientras no
haya Alembic, es la vía para actualizar el esquema (ver `COLUMNAS_NUEVAS` en
`scripts/inicializar_db.py`).

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
    auth.py          ingreso, salida y la contraseña propia
    joven.py         hoy, reto, mis retos, mis cartas, bitácora
    educador.py      panel, validaciones, retos, asignar, patrullas, jóvenes,
                     progresión, equipo de educadores
    api.py           la misma lógica en JSON
  servicios/
    cuentas.py       altas, contraseñas iniciales y blanqueos
    retos.py         qué reto ve cada joven hoy
    validacion.py    contrato de validación de evidencias
    puntajes.py      tablero de patrullas y rachas
    progresion.py    cartas elegidas, avance, cierre de cartas y paso de etapa
    medios.py        compresión de fotos y enlaces de video
  static/
    estilos.css      la hoja de estilos, sin framework ni build
    app.js           guardado automático y acciones sin recargar (ver abajo)
    img/             las ilustraciones (SVG hechos a mano, ver abajo)
datos/
  cartas_exploracion.json   las 53 competencias y sus 376 desafíos
scripts/
  inicializar_db.py     crea tablas y carga las cartas (idempotente)
  crear_educador.py     el primer educador, el único que no se da de alta desde
                        la aplicación
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

## Cuentas y contraseñas

**La contraseña inicial de toda cuenta es su propio nombre de usuario.** Vale
igual para un joven y para un educador. Mientras siga siendo esa, la cuenta no
abre ninguna página que no sea `/clave`: la única forma de usarla es ponerle una
contraseña propia. La regla entera vive en `app/servicios/cuentas.py` y el corte
lo hace `usuario_actual` en `dependencias.py`, así que una pantalla nueva queda
cubierta sin que nadie se acuerde de sumarla.

Antes el educador escribía una contraseña inicial en el formulario de alta, y
era el peor de los dos mundos: tenía que inventarla, dictarla en la reunión, y
quedaba sabiendo con qué entra otra persona. Ahora el alta se cuenta en una
frase —«tu usuario es `ana` y tu contraseña también»— y la de verdad la elige
cada uno.

| Qué | Dónde | Quién |
| --- | --- | --- |
| Dar de alta un joven | `/jovenes` | cualquier educador |
| Sumar otro educador | `/educadores` | cualquier educador |
| Cambiar la contraseña propia | `/clave`, desde el pie de página | cada uno |
| Blanquear la de un joven | `/jovenes` | cualquier educador |
| Blanquear la de un educador | `/educadores` | otro educador del equipo |

**Blanquear es volver al día uno**, no elegirle una contraseña a otro: la
devuelve a ser el nombre de usuario y la persona pone la suya al entrar. Es todo
el sistema de recuperación que hay, y alcanza porque el educador está en la
misma reunión que el joven: no pedimos direcciones de correo de menores, así que
no hay «recuperar por mail» ni tiene por qué haberlo. Nadie llega a ver la
contraseña de nadie —se guarda hasheada con scrypt, ver `seguridad.py`—, ni
siquiera quien tenga la base de datos en la mano.

**No hay rol de administrador.** Cualquier educador puede sumar a otro y
blanquear a cualquiera del equipo salvo a sí mismo (para la propia está
«cambiar mi contraseña», que pide la actual). El equipo de una Unidad son tres o
cuatro personas que se conocen y comparten la responsabilidad del programa;
inventar una jerarquía adentro sería inventar un cargo que en la Unidad no
existe. Lo que sí queda cerrado es el borde de afuera: solo se ve y se toca a la
gente de la propia Unidad, y todo lo que se decide queda firmado con nombre.

El primer educador de todos sí va por consola —en una base vacía no hay quien dé
de alta a nadie—, con `scripts/crear_educador.py`. Después de ese, nunca más.

## La pantalla

Quien usa esto tiene entre 10 y 14 años y entra desde el celular, así que la
navegación de verdad es la **barra de abajo** con las siete secciones; en
pantalla ancha esa misma lista se muestra arriba como pestañas. Sale de un solo
listado en `base.html`, así que no hay dos menús que mantener sincronizados.

Las ilustraciones son **SVG escritos a mano** en `app/static/img/`: el campamento
de las cabeceras, un dibujo por área de desarrollo (`img/areas/{codigo}.svg`, el
nombre sale del `codigo` del área en la base) y los de las páginas vacías. Pesan
unos pocos kB, se ven bien en cualquier pantalla y no dependen de ningún CDN:
la aplicación no pide un solo byte a un servidor ajeno.

No hay framework de CSS ni paso de build: `estilos.css` es un archivo, y las
plantillas usan sus clases. Los emojis hacen de íconos, igual que en el resto
del programa —cada área ya tenía el suyo en la base de datos—.

## El JavaScript

`app/static/app.js` es un archivo, sin framework, sin build y sin dependencias.
Todo lo que hace es **mejora progresiva**: si no carga, la aplicación funciona
igual, con sus formularios y sus recargas. Eso no es prolijidad de manual —esto
se usa desde el celular en un campamento, y una señal que se corta no puede
dejar a nadie sin poder marcar lo que hizo—. Las pruebas recorren los dos
caminos: el mismo POST, con y sin la cabecera que manda el JavaScript.

Una plantilla se engancha con un atributo:

| Atributo | Qué hace |
|---|---|
| `data-autoguardar` | El formulario se guarda solo al marcar algo o al dejar de escribir. El botón «Guardar» se esconde por CSS y vuelve si algo falló. |
| `data-sin-recarga="Listo"` | El formulario se envía por detrás y se repinta `<main>` en el lugar, sin saltar arriba ni cerrar lo que estaba desplegado. El texto es el aviso que aparece al terminar. |
| `data-elegir` | El botón de elegir una carta, que tiene su propio camino en JSON. |
| `data-cuenta="…"` | Un número que se actualiza solo (cartas elegidas, logradas, por área). |
| `data-aviso="…"` | Lo que la página nueva quiere decir en lugar del mensaje del formulario: sirve para que «se guardó» no se muestre cuando lo que volvió fue un pedido de confirmación. |
| `data-confirmar="…"` | Pregunta adentro de la tarjeta en vez de abrir el cartel del navegador. El `onsubmit="return confirm(…)"` se deja en la plantilla como plan B y lo saca `app.js` al arrancar. |
| `data-refrescar="30"` | La página se pone al día sola cada tantos segundos. |
| `data-atajos` / `data-entrega` | La lista se puede recorrer y resolver con el teclado. |
| `.solo-js` | Texto que solo tiene sentido con JavaScript andando. |

**El HTML lo sigue armando el servidor.** No hay plantillas en JavaScript.
Cuando algo tiene que repintarse, la ruta devuelve el pedazo ya renderizado por
Jinja (`fragmento()` en `dependencias.py`) y el navegador lo pega en su lugar,
así que lo que se ve al entrar y lo que se ve después de tocar un botón salen
de la misma plantilla y no se pueden despegar. Los parciales son los archivos
que empiezan con `_`.

Del lado de las rutas hay un solo cambio: `quiere_json(request)` mira una
cabecera que solo manda `app.js`. Un formulario común nunca la trae, así que la
misma ruta atiende a los dos casos sin duplicarse.

Detalles que se notan en la pantalla:

- Al elegir una carta se **compensa el alto** de lo que cambió arriba, así que
  el catálogo no se te mueve bajo el dedo. Sin JavaScript eso lo resuelve el
  ancla `#carta-N` de la redirección.
- Las fotos se suben con `XMLHttpRequest` y no con `fetch`, porque es lo único
  que informa cuánto va subiendo. Con señal de campamento, ver que algo avanza
  es la diferencia entre esperar y volver a apretar el botón.
- **El buscador del catálogo no consulta nada**: las cartas ya están en la
  página, así que el índice se arma del propio HTML (título y desafíos) y se
  compara sin acentos ni mayúsculas. Un área que se queda sin resultados
  desaparece entera, con su franja.
- **La foto se achica en el celular** antes de subirla: 1600 px y calidad 82,
  los mismos números que `config.py`. Una de 4 MB sale como 300 kB. Si el
  navegador no la supo abrir, o si achicarla no la hubiera hecho más chica,
  sube la original. La compresión del servidor sigue igual: esto ahorra los
  datos de quien sube, no reemplaza la garantía de allá.
- **Lo que no salió por falta de señal** queda en `localStorage` y se manda
  solo cuando vuelve la conexión, con un cartel a la vista mientras tanto. La
  cola va por usuario (`localStorage["retos-pendientes-{id}"]`, y de ahí el
  `data-usuario` en el `<body>`): lo que quedó a medias en un teléfono no
  puede terminar entrando en la sesión de otra persona. Solo entra ahí lo de
  `data-autoguardar`, que es idempotente; una entrega o una página del libro
  no se reintentan solas porque reintentarlas sería crearlas dos veces. Un
  rechazo del servidor tampoco se encola: reintentar un «no» es un lazo
  infinito.
- **Los atajos de validación** (`J`/`K` para moverse, `A`/`D`/`R` para
  resolver) se anuncian solo donde hay teclado de verdad —`pointer: fine`—, y
  se apagan mientras el foco está en un campo de texto.
- **El tablero se repinta solo** cada 30 s, pero solo si el HTML cambió, solo
  con la pestaña a la vista, y nunca por encima de alguien que está
  escribiendo, mirando una foto o a punto de confirmar algo.

## La progresión personal

Cada joven elige de 12 a 14 cartas para su etapa. Eso vive en `/mis-cartas`, que
tiene tres partes separadas: arriba **las que eligió**, con su avance y el acceso
a trabajarlas; en el medio el **historial** de las etapas anteriores; abajo el
**catálogo** de las que le quedan por explorar. Elegir una carta no mueve la
página: el botón cambia ahí mismo y la lista de arriba se repinta sola. Sin
JavaScript te devuelve al ancla de esa carta, no al principio de la lista.

En `/mis-cartas/{id}` marca cada desafío como hecho y escribe cómo le fue. Eso
es `AvanceDesafio`, y va por etapa: si saca una carta de su elección y después la
vuelve a poner, el trabajo sigue ahí. **No hay que apretar nada para guardar**:
tildar una casilla guarda al instante y el comentario se guarda solo al dejar de
escribir. Si algo no salió, aparece el botón «Guardar» para reintentar a mano, y
si se cierra la pestaña con algo a medio escribir se manda igual (`sendBeacon`).

**El avance se cuenta sobre los requeridos**, que son los mínimos de la carta.
Los opcionales suman y se muestran, pero no mueven la meta.

**Cumplir todos los requeridos no da la carta por lograda.** La app lo dice
—"conversalo con tu educador/a"— y ahí se queda. Cerrar una competencia es una
conversación entre el joven, su patrulla y el equipo de educadores (cap. 9), no
un contador que llega a cero.

## Las cartas y la etapa, en una sola página

Las dos cosas van juntas —las cartas son el recorrido de la etapa— y las dos las
decide un educador, en `/progresion/{joven_id}`: arriba el cambio de etapa,
abajo las cartas elegidas con su avance. Se entra desde el listado de jóvenes,
que muestra de cada uno la etapa y cuántas cartas lleva elegidas y logradas.

**Nada se cierra solo, y nada se cierra a ciegas.** La app no bloquea: avisa. El
camino esperado sale derecho, y todo lo demás pide una confirmación explícita:

| lo que se pide | qué pasa |
|---|---|
| cerrar una carta con todos los requeridos hechos | se cierra; el aviso recuerda que primero se conversa |
| cerrar una carta con requeridos sin marcar | hace falta marcar la casilla; queda guardado que se cerró con pendientes |
| pasar a la etapa siguiente con las 12 cartas logradas | se cambia derecho |
| cambiar de etapa sin eso, o volver a una anterior | hace falta marcar la casilla |

Que falten requeridos no vuelve imposible cerrar una carta, y es a propósito: la
guía dice que un desafío opcional puede reemplazar a uno requerido si se
conversó, y hay chicos que hicieron la competencia sin ir tildando la lista. Lo
que no puede pasar es que ocurra sin que nadie lo mire. Por eso, cuando falta
confirmar, el POST no rompe: vuelve a la página con el aviso abierto sobre esa
carta.

**Cada cierre queda firmado.** Quién lo cerró, cuándo, si tenía pendientes y qué
se conversó. Esa nota la leen el joven y su patrulla, porque es parte de la
conversación; la marca de "con requeridos sin marcar" la ven solo los
educadores.

**El paso de etapa deja historia.** `CambioEtapa` guarda de dónde a dónde, quién
lo decidió y cuántas cartas tenía elegidas y logradas en ese momento. Ese número
hay que guardarlo sí o sí: las cartas viven atadas a su etapa, así que al día
siguiente del cambio la etapa nueva arranca en cero y ya no se puede recalcular.

## Lo que queda de las etapas anteriores

Cambiar de etapa no borra nada, y ahora tampoco lo esconde. Las cartas y las
marcas viven atadas a la etapa en la que se trabajaron, así que al cambiar
quedan enteras y salen por el **historial**: una sección por etapa recorrida,
con cada carta y con lo que escribió en cada desafío. Está en `/mis-cartas`, en
`/cartas-de/{joven_id}` y en la progresión del educador, y sale de una sola
plantilla —`joven/_historial.html`— para que las tres cuenten lo mismo.

Van las logradas, que es lo que el historial viene a guardar, y también las que
quedaron sin cerrar: ahí adentro hay trabajo hecho y no tiene por qué
desaparecer de la pantalla.

**Una carta lograda no vuelve al catálogo.** Esa competencia ya la desarrolló:
ofrecérsela de nuevo en la etapa siguiente sería pedirle que la vuelva a hacer.
Sale del catálogo de `/mis-cartas` —el subtítulo dice cuántas se fueron y enlaza
al historial— y el servidor rechaza el pedido si llega igual, desde una pestaña
vieja o del atajo de alguien curioso. Su página, `/mis-cartas/{id}`, sigue
abriendo: en solo lectura, con la etapa en la que la logró y lo que escribió
entonces.

Nada de esto es una tabla nueva: es la misma `CompetenciaElegida` y el mismo
`AvanceDesafio` de siempre, leídos por etapa. `AvanceCarta` lleva adentro las
marcas de *su* etapa, porque el historial pone cartas de etapas distintas en una
misma pantalla y cada una tiene que contarse con las suyas.

**La etapa no se toca desde el listado de jóvenes.** Ahí solo se cambia la
patrulla. Son dos decisiones distintas: mover a alguien de patrulla es organizar
la Unidad; cambiarle la etapa es cerrar un tramo de su progresión personal, y
para eso hay que estar mirando sus cartas.

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

## Ponerlo en un servidor

La aplicación entera entra en un contenedor: `Dockerfile` la arma y
`docker compose up --build` la levanta igual que va a correr afuera. El paso a
paso para dejarla andando en Azure Container Apps —dentro del nivel gratuito,
apagándose sola mientras nadie la usa— está en [DESPLIEGUE.md](DESPLIEGUE.md),
y el día a día de una que ya está andando —subir un cambio, dar de alta un
educador, respaldar, volver atrás— en [OPERAR.md](OPERAR.md).

Lo único que hay que montar en un volumen es `/datos-persistentes`: ahí viven
`scout.db` y las fotos. El resto de la imagen se rehace construyéndola de nuevo.

### Antes de ponerlo en producción

- Definir `CLAVE_SECRETA` **en el entorno del servidor, como secreto**, no en un
  `.env`: el archivo es para desarrollo y no viaja en la imagen. Sin eso las
  sesiones se invalidan en cada reinicio y el valor por defecto es público.
- Servir por HTTPS y poner `COOKIES_SEGURAS=1`, que es lo que marca la cookie
  de sesión como `Secure`.
- Si la base queda sobre un disco de red (Azure Files, SMB, NFS),
  `SQLITE_JOURNAL=DELETE`: el modo WAL necesita memoria compartida entre
  procesos y ahí no existe.
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
