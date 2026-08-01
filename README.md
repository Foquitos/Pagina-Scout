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

`python main.py` **pone la base al día antes de levantar el servidor**, igual que
hace el contenedor en el servidor (`docker/entrypoint.sh`). Así, después de un
`git pull` que traiga una tabla o una columna nueva, no hay ningún paso que
acordarse: arranca y ya está. Correr `scripts/inicializar_db.py` a mano sigue
sirviendo —es idempotente— y es lo que hay que hacer si la base está en otro
lado o si se quieren los usuarios de prueba con `--demo`.

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
    joven.py         hoy, reto, mis retos, el muro, mis cartas, bitácora
    patrulla.py      la patrulla por dentro: identidad, cargos, Consejo, acuerdos
    participacion.py las ideas para el ciclo
    agenda.py        el calendario del ciclo y el «estuve»
    especialidades.py  lo que pide el joven y lo que prepara el equipo
    educador.py      panel, validaciones, retos, asignar, patrullas, jóvenes,
                     progresión, cargos, equipo de educadores
    api.py           la misma lógica en JSON
  servicios/
    cuentas.py       altas, contraseñas iniciales y blanqueos
    retos.py         qué reto ve cada joven hoy
    validacion.py    contrato de validación de evidencias
    puntajes.py      tablero de patrullas y rachas
    progresion.py    cartas elegidas, avance, cierre de cartas y paso de etapa
    patrulla.py      cargos, Consejo de Patrulla y acuerdos
    participacion.py ideas, apoyos y en qué anda cada una
    agenda.py        actividades del calendario y participación
    especialidades.py  pedir, preparar y las tres fases
    muro.py          lo que cada uno quiso mostrar de lo que hizo
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

**Y el tablero ordena por promedio, no por total.** El capítulo 4 avisa que las
patrullas son desparejas y que eso está bien —«es frecuente que en una Unidad
Scout haya patrullas desparejas en número (…) Esta heterogeneidad nos muestra que
estamos en buen camino»— y hasta pide no repartir a los que llegan para
emparejarlas. Si el marcador sumara nomás, la aplicación estaría premiando
exactamente lo que la guía dice que no hay que hacer: una patrulla de ocho le
gana siempre a una de cuatro sin que nadie se haya esforzado más. Así que la
cifra grande es **puntos por integrante**; el total sigue a la vista, pero no
decide quién va arriba. Los educadores no cuentan para el promedio: no entregan
retos.

**Un validador automático nunca rechaza, y la sección del educador no es una
cola de aprobación.** Una entrega completa se da por buena sola y suma en el
momento: un chico que hizo lo que le pidieron no tiene por qué esperar al sábado
para que alguien le diga que sí. `/validaciones` muestra todo lo entregado, y lo
que el equipo hace ahí es mirar y —si algo no pasó— darlo de baja. Un validador
automático puede aprobar o derivar a un educador, nada más: rechazar es siempre
decisión de una persona. La guía dice
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

**La contraseña inicial de toda cuenta es provisoria y sorteada**, y se muestra
una sola vez. Vale igual para un joven y para un educador. Mientras siga siendo
esa, la cuenta no abre ninguna página que no sea `/clave`: la única forma de
usarla es ponerle una contraseña propia. La regla entera vive en
`app/servicios/cuentas.py` y el corte lo hace `usuario_actual` en
`dependencias.py`, así que una pantalla nueva queda cubierta sin que nadie se
acuerde de sumarla.

Antes el educador escribía una contraseña inicial en el formulario de alta, y
era el peor de los dos mundos: tenía que inventarla, dictarla en la reunión, y
quedaba sabiendo con qué entra otra persona. Sigue sin haber ese campo: la
aplicación sortea una provisoria del tipo `fogata-remo-47` y la muestra una sola
vez para que el educador se la diga ahí mismo. La de verdad la elige cada uno al
entrar.

Durante un tiempo la provisoria fue el propio nombre de usuario, y la idea era
buena —nadie tenía que inventar ni anotar nada—, pero los nombres de usuario de
una Unidad son adivinables (`ana`, `mateo`, `juanp`) y eso convertía cada cuenta
recién dada de alta en una puerta que se abría en **una sola prueba**. Un freno
a la fuerza bruta no sirve contra un ataque que acierta al primer intento, así
que hubo que cambiar la provisoria. El freno está igual, en `app/seguridad.py`:
cinco intentos fallidos por cuenta y la cuenta descansa quince minutos.

| Qué | Dónde | Quién |
| --- | --- | --- |
| Dar de alta un joven | `/jovenes` | cualquier educador |
| Sumar otro educador | `/educadores` | cualquier educador |
| Cambiar la contraseña propia | `/clave` | cada uno |
| Blanquear la de un joven | `/jovenes` | cualquier educador |
| Blanquear la de un educador | `/educadores` | otro educador del equipo |
| Sacar a un educador del equipo | `/educadores` | otro educador del equipo |

### Sacar a alguien del equipo

Un educador **firma** cosas: la carta que acordó, la etapa que cambió, la entrega
que validó, la página que bajó del libro. La aplicación entera está construida
sobre que se sepa quién decidió qué, así que borrar la cuenta dejaría huecos en
el historial de progresión de chicos que hoy dice quién los acompañó.

Por eso hay dos caminos y la aplicación **elige sola** mirando la base
(`cuentas.dejo_rastro` recorre el esquema buscando filas que apunten a esa
persona; se recorre el esquema y no una lista escrita a mano para que una tabla
nueva quede cubierta el día que se crea):

- **Firmó algo** → se desactiva. Deja de entrar, la sesión abierta se corta en el
  pedido siguiente —`usuario_opcional` la vacía al ver la cuenta inactiva—, su
  nombre sigue donde está, y se puede reincorporar con la contraseña que tenía.
- **No firmó nada** → se borra de verdad. Es el usuario que se escribió mal:
  no existió para nadie, y dejarlo como «inactivo» sería guardar basura con
  nombre de persona.

La pantalla dice cuál de las dos va a pasar **antes** de que aprieten.

**Nadie se da de baja a sí mismo.** No es una formalidad: es lo que garantiza que
la Unidad no pueda quedarse sin ningún educador activo, porque cada baja la firma
alguien que se queda adentro.

A `/clave` y a `/educadores` se llega desde el **menú de la cuenta**, arriba a la
derecha: son cosas de la persona, no secciones del programa (ver [La
pantalla](#la-pantalla)).

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

En esa barra van **solo las secciones del programa**. Lo que es de la persona
—su contraseña, el equipo de educadores, cerrar sesión— vive en el **menú de la
cuenta**, arriba a la derecha, detrás del avatar. Están separados porque compiten
por lugar: siete secciones ya llenan el ancho de un teléfono, y cuando «Equipo» y
«Salir» estaban en la barra de arriba —la que el celular esconde entera— desde el
teléfono no había forma de tocarlos.

El menú es un `<details>` y no un botón con JavaScript: abre y cierra igual sin
JS, que es la regla de toda la aplicación. Lo único que agrega `app.js` es que se
cierre al tocar afuera o con Escape, que es comodidad y no funcionamiento.

**Siete y no ocho.** Cada sección que se suma tiene que sacar a otra o entrar
adentro de una. Las que hay para un joven son Hoy, Muro, Cartas, Patrulla, Ideas,
Bitácora y Tablero; el resto se llega desde su lugar natural, que además es el
que le corresponde en el método: el **Libro de Oro** desde la patrulla —porque es
de la patrulla—, el **calendario** desde «Hoy», las **especialidades** desde las
cartas, y **mis retos** desde el muro. Del lado del educador, `/calendario`,
`/ideas` y `/cargos` cuelgan del Panel, y `/especialidades` de «Jóvenes».

**El encabezado va de borde a borde de la pantalla; el contenido no.** La barra
de arriba no se limita a nada, así la marca queda pegada a la izquierda del todo
y el avatar a la derecha del todo, como en cualquier aplicación. El contenido sí
tiene tope (`--ancho`, 1400px): a una rejilla de tarjetas el ancho le viene bien
—entran cuatro columnas en una notebook en vez de dos—, pero a un renglón de
texto hay que ponerle un final. Por eso hay un segundo tope, `--ancho-lectura`,
que se aplica solo donde se lee y se escribe: los párrafos de entrada de cada
sección y los `textarea`. En una tarjeta angosta no cambia nada, porque un
`max-width` nunca achica lo que ya es más chico.

Las tres cosas que sostienen que el encabezado no se parta en dos renglones:
`flex-wrap: nowrap` en la barra, `margin-right: auto` en la marca y
`flex-wrap: wrap` adentro del `<nav>`. Lo que cede cuando no entra todo es la
navegación, que se acomoda en dos líneas en su propia caja; la marca y el avatar
se quedan donde están.

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

## Quién cierra una carta

La cierra el joven, escribiendo su autoevaluación. No es una preferencia de
diseño: el capítulo 9 dice que «la joven o el joven son los principales
protagonistas de la evaluación de la progresión personal» y, para cuando el
equipo no coincide, que «siempre primará la autoevaluación. Es preferible que la
o el joven se exceda en la estimación de sus logros y no que se afecte su
autoestima o se le desanime para seguir avanzando».

En la práctica: al pie de cada carta hay un cuadro de texto con las seis
preguntas de la guía —qué aprendiste, qué hiciste para aprenderlo, qué se te hizo
difícil, quién te ayudó, cómo te sentiste, qué te quedaron ganas de aprender—.
Sin texto no se cierra: la autoevaluación **es** el cierre, no el trámite para
destrabarlo. Si quedan requeridos sin marcar, se avisa y se pide una casilla,
igual que en todos lados; la página se vuelve a dibujar en vez de redirigir, para
que nadie pierda lo que escribió.

La carta queda `lograda` y cuenta desde ese momento. Lo que falta después no es
un permiso: es la conversación. El educador la registra con **«Ya la
conversamos»** (`acordada`), y el panel lista las que esperan esa charla. Un
educador puede seguir cerrando cartas él mismo —hay chicos que no van a escribir
solos, y cerrar una carta en la conversación cara a cara es legítimo—; cuando lo
hace, queda acordada de entrada, porque la conversación ya pasó.

Reabrir no borra la autoevaluación. La escribió el joven y es suya, igual que los
comentarios de los desafíos.

## Los cargos de patrulla

«El propósito principal del sistema de patrullas es asignar verdadera
responsabilidad al mayor número posible de jóvenes» (Baden-Powell, 1919, citado
en el cap. 4). Cada Unidad tiene su catálogo en `/cargos` —arranca con los ocho
de la guía y se le agregan los propios—, y **quién ocupa cada uno lo decide la
patrulla**, desde `/patrulla/{id}`, no el educador.

Un período nace abierto y lo cierra el Consejo diciendo si se cumplió. No hay
duración fija, y es a propósito: la guía pide «dejar que la evaluación interna de
la patrulla regule este aspecto». **Una misma persona puede tener varios cargos a
la vez**: en una patrulla de cinco no hay uno por cabeza, y son responsabilidades,
no puestos. Para la etapa se cuentan cargos **distintos** cumplidos, así que
repetir el mismo tres ciclos no suma de nuevo. Un cargo dado de baja del catálogo deja de
ofrecerse pero nunca se borra: los períodos ya cumplidos son parte de la
progresión de alguien.

### Esto cambia el paso de etapa

Antes la aplicación miraba solo las cartas logradas, y por eso decía «listo para
avanzar» antes de tiempo. El capítulo 9 pide, además:

| etapa | además de las cartas |
|---|---|
| Pistas | un cargo cumplido |
| Senda | dos cargos distintos + una descubierta |
| Rumbo | lo anterior + un proyecto de Unidad y uno de Patrulla |
| Travesía | tres cargos + apoyar a alguien que empieza + la Exploración de Travesía |

Están en `REQUISITOS_ETAPA` (`servicios/progresion.py`) y salen en la página de
progresión como una lista con lo que la persona ya tiene al lado. Las dos últimas
de Travesía no se cuentan: ninguna base de datos puede saberlas, así que se
muestran con otro ícono para que alguien se acuerde de conversarlas.

Como siempre, **avisa y no bloquea**: el educador puede pasar a alguien de etapa
igual, confirmando.

## Voz y voto: las ideas del ciclo

El capítulo 8 no deja lugar a dudas: «En nuestra organización, las y los jóvenes
tienen voz y voto respecto de las actividades que desean realizar».

**La Asamblea que decide no está en la aplicación, y es a propósito.** Se reúne
en persona y así tiene que seguir: es donde se aprende a defender una idea, a
escuchar la de otro y a bancarse perder una votación mirando a la cara al que la
ganó. Una pantalla no enseña eso. Lo que la aplicación hace es lo que un papelito
en el bolsillo hace mal: juntar las propuestas para que lleguen enteras a esa
reunión, y anotar después lo que ahí se decidió.

```
alguien la propone  →  el equipo mira si se puede  →  la Asamblea decide (en persona)
      /ideas                    /ideas                →  se anota y va al calendario
```

Los cuatro estados de una idea son los cuatro momentos reales de una propuesta:

| estado | qué significa | quién lo pone |
|---|---|---|
| propuesta | alguien la escribió, nadie la miró | nace así |
| se puede hacer | el equipo la miró y es viable: va a la Asamblea | el equipo |
| elegida | la Asamblea la eligió, en persona | el equipo, después de la reunión |
| guardada | no salió esta vez; vuelve el ciclo que viene | el equipo |

Quién puede qué: **proponer**, cualquiera —a los educadores la guía se lo pide
expresamente, «para introducir nuevas temáticas»—; **apoyar** («me sumo»), solo
las y los jóvenes, y no decide nada: es un dato para llevar a la reunión;
**mover el estado y agendar**, el equipo; **borrar**, el equipo, o quien la
escribió mientras nadie la haya mirado —arrepentirse de lo propio es barato,
borrar lo de otro no—.

La `respuesta` importa sobre todo cuando algo se guarda. A un chico que propuso
algo se le contesta: que su idea desaparezca sin una palabra es la forma más
rápida de que no vuelva a proponer nada.

## El Consejo de Patrulla y los acuerdos

«La instancia formal de la toma de decisiones relevantes de la patrulla», y la
guía dice dónde se anota: «Los acuerdos del Consejo pueden registrarse en el
Libro de Oro o Libro de Patrulla».

Un acta es fecha, quiénes estuvieron y de qué hablaron. La diferencia con un
cuaderno es lo que pasa después: un acuerdo con responsable **aparece en el
`/hoy` de esa persona** hasta que se da por hecho. Un acuerdo que se queda
escrito en un acta es una anotación; uno que te espera al entrar es un
compromiso.

Los acuerdos sin responsable existen a propósito —hay cosas que son de toda la
patrulla— y los puede marcar cualquiera del grupo, no solo quien se comprometió:
el que lo hizo bien no siempre es el que se acuerda de venir a tildarlo.

## El calendario del ciclo

`/calendario`. Lo arma el equipo de educadores, porque la fase de organización es
del Consejo de Unidad; adentro van tanto lo que se eligió como las fijas
—campamentos, celebraciones, entregas de insignia—. Lo próximo también asoma en
`/hoy`, con los días que faltan.

Lo que hacen las y los jóvenes ahí es marcar **«estuve»**. No es una lista de
asistencia que toma un adulto: es cada uno diciendo dónde estuvo, y es lo que
alimenta los requisitos de descubiertas y proyectos de la etapa. Coherente con
que la evaluación de la progresión sea suya.

Una actividad de otra patrulla no se ve, igual que el Libro de Oro.

## Las especialidades

Dos cosas que parecen contradecirse y no:

**La pide el joven, y pide la que quiere.** «Tanto la decisión de desarrollar una
especialidad como la elección del tema específico son personales y voluntarias de
cada joven», y el único requisito es que lo desee. Por eso el pedido es un campo
de texto libre y no una lista: si a alguien le interesa la apicultura, escribe
apicultura. Un catálogo cerrado convertiría en «no se puede» todo lo que a los
adultos no se les ocurrió, que es lo contrario de lo que la guía busca acá. Los
desafíos de tipo especialidad de las Cartas de Exploración se ofrecen como
sugerencias —en un `datalist`, no en un `select`—, porque ayudan a quien no sabe
por dónde empezar sin cerrarle la puerta a nadie.

**Pero el recorrido lo prepara el equipo.** Pedirla no es empezarla. La guía les
encarga a los educadores conocer el tema, contactar a la persona experta e
informarle el sentido de las especialidades en el Programa de Jóvenes, y pensar
qué se espera en cada fase. Hasta que eso pasa, la especialidad está pedida y el
joven ve «tu educador/a la está preparando».

```
la pide el joven  →  el equipo la prepara  →  el joven la recorre  →  el equipo
   (la que quiera)     (experto + fases)        (tres fases)           la concluye
```

Los requisitos se escriben **para esa persona**, no para todas: «son solo una
referencia, pudiendo ser modificadas, teniendo en cuenta las particularidades de
cada joven, así como las diferencias geográficas, culturales, económicas y
sociales». Por eso se pueden ajustar en cualquier momento, también con la
especialidad ya en marcha.

Voluntaria, individual, de dos a seis meses, **sin puntaje ni validación**. Las
tres fases son las de la guía, con su verbo:

1. **Exploración (conocer)** — qué averiguaste, qué herramientas se usan.
2. **Taller (hacer)** — la parte práctica.
3. **Desafío (servir)** — a quién le sirvió lo que aprendiste.

La tercera no es un examen: es lo que hace que una especialidad scout no sea un
curso. La fase que muestra la pantalla es la más avanzada que tenga algo escrito
—nadie tiene que apretar «siguiente»—.

**La cierra un educador**, y es lo único de la progresión personal que la guía
deja explícitamente del lado del equipo: la insignia «constituye un testimonio
permanente de la actitud de servicio», y eso lo atestigua una persona.

El panel del equipo cuenta las dos cosas que esperan respuesta: los **pedidos sin
armar** y las que **llegaron a la fase de servicio**. Las dos mitades viven en un
solo router (`routers/especialidades.py`) porque son la misma URL, y partirlas
hizo que una le tapara las rutas a la otra.

## La identidad de la patrulla

Nombre, lema, grito, emblema, banderín, desde cuándo existe y su historia. No es
adorno: en el momento de ambientación la guía describe la integración como «la
suma de la relación social y de lo simbólico, identificándose con el nombre de la
Patrulla, lema, colores y más elementos de pertenencia».

Lo escribe la patrulla. El **nombre** no está ahí a propósito: cambiarlo es una
decisión de la Unidad, no un campo de texto, y sigue en `/patrullas` del lado del
educador. El banderín es una foto y pasa por la misma compresión que todas; hay
uno por patrulla, y al reemplazarlo el anterior se borra del disco.

## El muro de la Unidad

Un reto entregado lo ven quien lo entregó y el equipo, y nadie más. Eso está bien
para lo íntimo, pero desaprovecha lo que más empuja a un chico de doce años a
hacer algo: ver que otro lo hizo. La guía lo llama educación entre pares.

`/muro` muestra lo que cada uno **quiso** mostrar. Cuatro reglas, y las cuatro
importan:

- **Se comparte porque uno quiso.** El interruptor arranca apagado, está en el
  formulario de entrega y también en la entrega ya hecha, y lo mueve solamente
  quien la escribió, en cualquier momento y para los dos lados.
- **Solo lo validado.** Al muro no llega algo que todavía se está mirando ni algo
  que se dio de baja: dar de baja una entrega la saca del muro sola.
- **No hay número al lado.** Se ve qué hizo cada uno, no cuánto sumó. Convertir
  el muro en un ranking de personas es exactamente lo que evita que el puntaje
  sea siempre de la patrulla.
- **Se publica en el momento, y por eso hay que poder bajarlo en el momento.**
  Ver más abajo.

## El Libro de Oro

La memoria colectiva de cada patrulla, en `/libro-de-oro/{patrulla_id}`: título,
texto, una foto y un video por página. Es la contraparte de la Bitácora de
Aventura, que es personal. Lo escribe y lo lee la patrulla, más el equipo de
educadores; otra patrulla recibe 404. Borrar puede quien escribió la página, o
un educador.

## Publicar en el momento, y qué lo sostiene

Ni el muro ni el Libro de Oro esperan que un adulto mire la foto antes de que la
vean los demás. Es una decisión, no un olvido: el libro es **de la patrulla**, y
pedirle permiso a un grande para escribir en el propio libro lo desnaturaliza
(cap. 4). La alternativa —pre-moderar— también convierte al equipo en un cuello
de botella para algo que pasa todos los días.

Lo que esa inmediatez obliga a tener está en `app/servicios/moderacion.py`:

- **`/novedades`.** Todo lo que se publicó en la Unidad, lo último primero, con
  la foto a la vista: el muro y las páginas de los siete libros en una sola
  pantalla. No es una cola de aprobación —todo lo que está ahí ya está
  publicado—; es dónde el equipo se entera sin recorrer siete libros.
- **Avisar.** Cualquiera puede pedir que el equipo mire una publicación, y sobre
  todo quien aparece en la foto: es el que primero se da cuenta y el que antes no
  tenía forma de decirlo hasta la reunión del sábado. Un aviso no baja nada: la
  pone arriba de todo en `/novedades` y aparece en el panel.
- **Bajar, y poder deshacerlo.** `oculta_en` saca la publicación de circulación
  sin borrar nada: la entrega conserva sus puntos y la página sigue en el libro
  para su autor y el equipo. Tampoco toca `compartida`, que es el interruptor del
  joven. Un educador que baja algo por error a las once de la noche lo devuelve
  desde la misma pantalla, sin entrar a la base.

Un aviso también se puede cerrar **sin** bajar nada («lo miramos y queda»). Que
esa salida exista es lo que impide que avisar sea, en los hechos, sacar del muro.

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

## Sacar un reto de la agenda

Arrepentirse tiene que ser barato. En `/asignar`, cada fila de la agenda tiene
su **Quitar**, y si nadie entregó nada el reto se saca derecho, con una
pregunta y listo.

Con entregas adentro es otra cosa, y la app no la trata igual: ahí hay lo que
escribió un chico y puntos que ya están en el tablero de una patrulla. Sigue el
mismo criterio que el cierre de cartas —no bloquea, avisa—: vuelve a la agenda
con la cuenta exacta de lo que se estaría borrando (cuántas entregas, cuántas
validadas, cuántos puntos y a qué patrullas se les sacan) y hace falta marcar
una casilla. La pantalla además ofrece la salida obvia: **dejarlo donde está**,
porque un reto viejo en la agenda no molesta a nadie.

Dos cosas que el borrado respeta:

- **La Bitácora de Aventura no se toca.** Es el registro personal del joven
  —"esto es tuyo y no se puntúa"— y no es de nadie más: que el educador se
  arrepienta de un reto no puede borrarle a un chico lo que escribió. Si una
  entrada apuntaba a una entrega que se va, queda la entrada y se suelta el
  vínculo.
- **Las fotos de las entregas se borran del disco**, igual que al borrar una
  página del Libro de Oro. Un archivo huérfano ocupa lo mismo que uno en uso.

Del reto **propuesto por la aplicación** (🤖) se borra también el `Reto` que
inventó para ese día: nació para esa asignación y para nada más. Los que
escribió el educador quedan en `/retos`, que para eso los escribió. Ojo con
esto: si sacás el propuesto y ese día se queda sin ningún reto, la aplicación
vuelve a proponer **el mismo** —la elección es determinista por (unidad,
fecha)—. Para que no vuelva, asigná uno propio.

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

Son **320 verificaciones** sobre una base de datos temporal: no toca `scout.db`.
Recorre lo que importa de punta a punta —un joven entra, ve el reto del día,
entrega, el validador decide, el educador confirma, los puntos aparecen en la
patrulla— y también lo que no se ve: que un educador no vote en la Asamblea, que
una patrulla no lea la de al lado, que la carta la cierre su dueño, que sacar un
reto no borre la Bitácora de nadie y que ninguna pantalla se rompa para quien
todavía no tiene patrulla.

El último bloque entra a **todas** las páginas con los dos roles: una plantilla
rota no se nota hasta que alguien abre esa pantalla.

Si el terminal de Windows corta la salida con un error de codificación, es la
consola y no la prueba:

```powershell
$env:PYTHONIOENCODING = "utf-8"; python scripts/probar_circuito.py
```

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
- `/fotos/{nombre}` resuelve de quién es cada archivo y aplica la misma regla que
  la página donde se muestra (`moderacion.puede_ver_foto`). Tener sesión no
  alcanza: la foto del Libro de Oro de una patrulla no se sirve a otra ni con el
  uuid en la mano. Es importante que siga siendo así —un uuid se filtra solo, en
  el historial o en una captura reenviada— y por eso hay pruebas que lo fijan.
- Hay dos topes contra un archivo hostil: el cuerpo de la petición se corta por
  `Content-Length` en `app/main.py` antes de leer un byte, y ninguna imagen de
  más de `MAX_PIXELES_FOTO` se descomprime. Un PNG de 300 kB puede declarar
  20000×20000 y convertirse en 1,2 GB abiertos, y el contenedor tiene 0,5 GiB.
- SQLite aguanta bien una Unidad. Si esto crece a varios grupos, migrar a
  PostgreSQL es cambiar `BASE_DATOS_URL`, pero conviene sumar Alembic para las
  migraciones antes de tener datos que no se puedan perder.

## Documentación de referencia

`Docs/` tiene los 10 capítulos de la Guía de la Rama Scouts, las Cartas de
Exploración, el Manual Scout de Cabullería y el de tipos de fuego. El capítulo 9
(progresión personal) y el 4 (sistema de equipos) son los que definen el modelo
de datos de esta aplicación.
