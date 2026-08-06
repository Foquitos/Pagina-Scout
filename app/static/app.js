/* =============================================================
   Retos de Unidad — la capa de JavaScript

   Todo lo de acá es mejora progresiva: sin JavaScript la aplicación
   funciona igual, con sus formularios y sus recargas de siempre. Eso
   no es prolijidad de manual: esto se usa desde el celular en un
   campamento, y una señal que se corta no puede dejar a nadie sin
   poder marcar lo que hizo.

   Lo que hace:

     1. Guardado automático — los formularios con `data-autoguardar`
        se guardan solos al marcar una casilla o al dejar de escribir.
        El botón «Guardar» se esconde, y vuelve si algo falla.

     2. Acciones sin recargar — los formularios con `data-sin-recarga`
        se envían por detrás y la página se repinta en el lugar, sin
        saltar arriba de todo ni perder lo que estaba abierto.

     3. Elegir cartas en el momento — /mis-cartas contesta en JSON y
        acá se acomodan el catálogo, los contadores y la lista de las
        elegidas sin volver a pedir las 53 cartas.

     4. Buscar en el catálogo — las 53 cartas ya están en la página,
        así que filtrarlas por palabra, área o estado no le cuesta
        nada al servidor.

     5. Achicar la foto antes de subirla — 4 MB se vuelven 300 kB en
        el celular. El servidor la comprime igual: esto ahorra los
        datos de quien sube, no reemplaza la garantía de allá.

     6. Cola de reintentos — lo que no salió por falta de señal queda
        guardado en el teléfono y se manda solo cuando vuelve.

     7. Detalles de pantalla — ver una foto en grande sin salir de la
        página, confirmar un borrado adentro de la tarjeta, el tablero
        que se actualiza solo, atajos de teclado para validar y el menú
        de la cuenta que se cierra al tocar afuera.

   El HTML lo sigue armando el servidor: acá no hay plantillas. Cuando
   algo tiene que repintarse, la ruta devuelve el pedazo ya renderizado
   por Jinja y esto lo pega en su lugar. Así lo que se ve al entrar y
   lo que se ve después de tocar un botón salen de la misma plantilla
   y no se pueden despegar.
   ============================================================= */

(function () {
  "use strict";

  // La cabecera le avisa al servidor quién pregunta. Un formulario
  // normal nunca la manda, así que la misma ruta sirve a los dos.
  var CABECERA = "X-Sin-Recarga";
  var ESPERA_TIPEO = 900; // ms sin teclear antes de guardar solo

  function uno(selector, raiz) {
    return (raiz || document).querySelector(selector);
  }

  function todos(selector, raiz) {
    return Array.prototype.slice.call((raiz || document).querySelectorAll(selector));
  }

  /* --- Avisos flotantes ------------------------------------------------- */

  function avisar(texto, tono) {
    var zona = uno("#avisos");
    if (!zona || !texto) return;
    var globo = document.createElement("div");
    globo.className = "globo" + (tono ? " " + tono : "");
    globo.textContent = texto;
    zona.appendChild(globo);
    setTimeout(function () { globo.classList.add("yendose"); }, 2600);
    setTimeout(function () { globo.remove(); }, 3300);
  }

  /* --- Hablar con el servidor ------------------------------------------- */

  function cuerpoDe(form, boton) {
    var datos = new FormData(form);
    // FormData no incluye el botón que se apretó, y hay formularios
    // —la cola de validaciones— donde el botón *es* la decisión.
    if (boton && boton.name) datos.append(boton.name, boton.value);
    // Si la foto se pudo achicar en el celular, sube la achicada.
    todos("input[type=file]", form).forEach(function (entrada) {
      if (entrada.name && entrada._achicada) {
        datos.set(entrada.name, entrada._achicada.blob, entrada._achicada.nombre);
      }
    });
    return datos;
  }

  // XHR y no fetch a propósito: es lo único que informa cuánto va
  // subiendo un archivo, y acá se suben fotos de 4 MB desde el celular.
  function enviarAlServidor(form, cuerpo, modo, alProgresar) {
    return new Promise(function (resolver, rechazar) {
      var peticion = new XMLHttpRequest();
      peticion.open("POST", form.action, true);
      peticion.setRequestHeader(CABECERA, modo);
      if (alProgresar && peticion.upload) {
        peticion.upload.addEventListener("progress", function (evento) {
          if (evento.lengthComputable) alProgresar(evento.loaded / evento.total);
        });
      }
      peticion.addEventListener("load", function () {
        resolver({
          estado: peticion.status,
          url: peticion.responseURL || form.action,
          texto: peticion.responseText
        });
      });
      peticion.addEventListener("error", function () { rechazar(new Error("sin red")); });
      peticion.addEventListener("abort", function () { rechazar(new Error("cancelado")); });
      peticion.send(cuerpo);
    });
  }

  function leerJSON(respuesta) {
    try {
      return JSON.parse(respuesta.texto);
    } catch (error) {
      // La ruta contestó HTML: no hay nada que repintar, pero guardó.
      return null;
    }
  }

  // Un error puede volver de dos formas: la página de error, o el JSON pelado
  // que arma FastAPI cuando una ruta levanta un 400 («ese usuario ya existe»).
  function motivoDeError(respuesta, documento) {
    try {
      var suelto = JSON.parse(respuesta.texto);
      if (suelto && suelto.detail) return String(suelto.detail);
    } catch (error) { /* era HTML */ }
    var detalle = uno("main .vacio p", documento);
    if (detalle && detalle.textContent.trim()) return detalle.textContent.trim();
    var titulo = uno("main .vacio strong", documento);
    if (titulo) return titulo.textContent.trim();
    return "No se pudo completar la acción.";
  }

  /* --- Repintar sin que se mueva el piso -------------------------------- */

  // Si lo que cambia de tamaño está más arriba de lo que se está mirando,
  // todo lo de abajo se corre. Elegir la carta 47 no puede empujarte la
  // pantalla: se compensa el alto que cambió.
  function conservarPosicion(nodo, accion) {
    var antes = nodo.getBoundingClientRect();
    accion();
    var despues = nodo.getBoundingClientRect();
    if (antes.top < 0) window.scrollBy(0, despues.height - antes.height);
  }

  function aplicarRespuesta(datos) {
    if (!datos) return;
    var fragmentos = datos.fragmentos || {};
    Object.keys(fragmentos).forEach(function (selector) {
      var destino = uno(selector);
      if (!destino) return;
      conservarPosicion(destino, function () {
        destino.innerHTML = fragmentos[selector];
      });
    });
    var cuentas = datos.cuentas || {};
    Object.keys(cuentas).forEach(function (nombre) {
      todos('[data-cuenta="' + nombre + '"]').forEach(function (nodo) {
        nodo.textContent = cuentas[nombre];
      });
    });
  }

  /* --- 1. Guardado automático ------------------------------------------- */

  function firma(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function hora() {
    return new Date().toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
  }

  function estadoGuardado(form, clase, texto) {
    var marca = uno("[data-estado]", form);
    form.classList.toggle("con-error", clase === "error");
    if (!marca) return;
    // Se escribe solo si cambió: si no, cada tecla apretada mueve el DOM.
    if (marca.dataset.estado === clase && marca.textContent === texto) return;
    marca.dataset.estado = clase;
    marca.textContent = texto;
  }

  function programarGuardado(form) {
    clearTimeout(form._reloj);
    if (firma(form) !== form.dataset.firma) estadoGuardado(form, "escribiendo", "escribiendo…");
    form._reloj = setTimeout(function () { guardar(form); }, ESPERA_TIPEO);
  }

  // Marca imposible de igualar: es lo que queda cuando algo no se pudo
  // guardar, para que el próximo intento vuelva a salir sí o sí.
  var SIN_GUARDAR = " pendiente";

  function guardar(form) {
    clearTimeout(form._reloj);
    var actual = firma(form);
    if (actual === form.dataset.firma) {
      // Nada cambió: no se toca lo que ya decía («guardado el 12/07»).
      if (form.dataset.ultimo) estadoGuardado(form, "guardado", form.dataset.ultimo);
      return Promise.resolve();
    }
    if (form._enviando) {
      // Siguió escribiendo mientras viajaba lo anterior: se reintenta al volver.
      form._repetir = true;
      return Promise.resolve();
    }

    form._enviando = true;
    form.dataset.firma = actual;
    estadoGuardado(form, "guardando", "guardando…");

    return enviarAlServidor(form, cuerpoDe(form, null), "json", null)
      .then(function (respuesta) {
        if (respuesta.estado < 200 || respuesta.estado >= 300) {
          var rechazo = new Error("rechazado");
          rechazo.delServidor = true;
          throw rechazo;
        }
        aplicarRespuesta(leerJSON(respuesta));
        // La hora la pone el navegador: el servidor guarda en UTC y no
        // tiene por qué saber en qué huso está quien escribe.
        form.dataset.ultimo = "guardado " + hora();
        estadoGuardado(form, "guardado", form.dataset.ultimo);
      })
      .catch(function (error) {
        form.dataset.firma = SIN_GUARDAR;
        if (error && error.delServidor) {
          // El servidor lo miró y dijo que no: reintentarlo no lo va a mejorar.
          estadoGuardado(form, "error", "no se guardó — probá otra vez");
          return;
        }
        // Fue la señal. Queda anotado en el teléfono y sale solo cuando vuelva.
        encolar(form);
        estadoGuardado(form, "error", "sin señal — se manda cuando vuelva");
      })
      .then(function () {
        form._enviando = false;
        if (form._repetir) {
          form._repetir = false;
          guardar(form);
        }
      });
  }

  // Si se cierra la pestaña con algo a medio escribir, se manda igual.
  // sendBeacon sale aunque la página ya se esté yendo.
  function despedirse() {
    todos("form[data-autoguardar]").forEach(function (form) {
      if (firma(form) === form.dataset.firma) return;
      var salio = navigator.sendBeacon &&
        navigator.sendBeacon(form.action, cuerpoDe(form, null));
      // Si ni eso salió, queda en la cola para el próximo arranque.
      if (!salio) encolar(form);
      form.dataset.firma = firma(form);
    });
  }

  /* --- 2. Acciones sin recargar ----------------------------------------- */

  function claveDetalle(detalle) {
    if (detalle.id) return "#" + detalle.id;
    var titulo = uno("summary", detalle);
    return titulo ? titulo.textContent.trim() : "";
  }

  function reemplazarPagina(documento, url) {
    var nuevo = uno("main", documento);
    var actual = uno("main");
    if (!nuevo || !actual) {
      location.reload();
      return;
    }

    // Lo que el educador tenía desplegado sigue desplegado. Los que no tienen
    // ni id ni título quedan afuera: sin nombre no hay forma de reconocerlos.
    var abiertos = {};
    todos("details[open]", actual).forEach(function (d) {
      var clave = claveDetalle(d);
      if (clave) abiertos[clave] = true;
    });

    var alto = window.scrollY;
    actual.innerHTML = nuevo.innerHTML;
    todos("details", actual).forEach(function (d) {
      var clave = claveDetalle(d);
      if (clave && abiertos[clave]) d.open = true;
    });

    if (documento.title) document.title = documento.title;
    if (url) history.replaceState(null, "", url);
    window.scrollTo(0, alto);
    acomodar();
  }

  function barraDeSubida(form) {
    var hayArchivo = todos("input[type=file]", form).some(function (entrada) {
      return entrada.files && entrada.files.length;
    });
    if (!hayArchivo) return null;

    var barra = document.createElement("div");
    barra.className = "barra-avance subida";
    barra.innerHTML = '<div style="width:0%"></div>';
    form.appendChild(barra);
    return {
      avanzar: function (fraccion) {
        barra.firstChild.style.width = Math.round(fraccion * 100) + "%";
      },
      sacar: function () { barra.remove(); }
    };
  }

  function prepararEnvio(form, boton, cambiarTexto) {
    form.setAttribute("aria-busy", "true");
    if (boton) {
      boton.disabled = true;
      if (cambiarTexto) {
        boton.dataset.textoOriginal = boton.textContent;
        boton.textContent = boton.dataset.cargando || "Enviando…";
      }
    }
    return barraDeSubida(form);
  }

  function terminarEnvio(form, boton, barra) {
    form.removeAttribute("aria-busy");
    if (boton) {
      boton.disabled = false;
      if (boton.dataset.textoOriginal) {
        boton.textContent = boton.dataset.textoOriginal;
        delete boton.dataset.textoOriginal;
      }
    }
    if (barra) barra.sacar();
  }

  function enviarYRepintar(form, boton) {
    var barra = prepararEnvio(form, boton, true);
    enviarAlServidor(form, cuerpoDe(form, boton), "pagina", barra && barra.avanzar)
      .then(function (respuesta) {
        var documento = new DOMParser().parseFromString(respuesta.texto, "text/html");
        if (respuesta.estado >= 400) {
          // No se repinta: se deja el formulario como estaba, con lo escrito
          // adentro, y se dice qué pasó.
          avisar(motivoDeError(respuesta, documento), "mal");
          return;
        }
        reemplazarPagina(documento, respuesta.url);
        // La página nueva puede tener algo mejor que decir que el formulario:
        // «se guardó» sería mentira si lo que volvió fue un pedido de confirmar.
        var propio = uno("[data-aviso]", documento);
        avisar(propio ? propio.dataset.aviso : form.dataset.sinRecarga, propio ? "mal" : "bien");
      })
      .catch(function () {
        avisar("No se pudo conectar. Fijate la señal y probá otra vez.", "mal");
      })
      .then(function () { terminarEnvio(form, boton, barra); });
  }

  /* --- 3. Elegir y sacar cartas ----------------------------------------- */

  function pintarCarta(form, elegida) {
    var tarjeta = form.closest("[data-carta]");
    var boton = uno("button", form);
    if (boton) {
      boton.textContent = elegida ? "Sacar de mi elección" : "＋ Elegir esta carta";
      boton.classList.toggle("secundario", elegida);
    }
    if (!tarjeta) return;
    tarjeta.classList.toggle("elegida", elegida);
    var trabajar = uno("[data-trabajar]", tarjeta);
    if (trabajar) trabajar.hidden = !elegida;
    // Si estaba filtrando por «las que elegí», la carta acaba de cambiar de lado.
    refiltrar();
  }

  function alternarCarta(form, boton) {
    prepararEnvio(form, boton, false);
    enviarAlServidor(form, cuerpoDe(form, boton), "json", null)
      .then(function (respuesta) {
        if (respuesta.estado >= 400) {
          // El servidor puede tener un motivo concreto —«esa carta ya la
          // lograste en Senda»— y decirlo vale más que un «no se pudo».
          var documento = new DOMParser().parseFromString(respuesta.texto, "text/html");
          avisar(motivoDeError(respuesta, documento), "mal");
          return;
        }
        var datos = leerJSON(respuesta);
        if (!datos) throw new Error("respuesta rara");
        aplicarRespuesta(datos);
        pintarCarta(form, datos.elegida);
        avisar(datos.aviso, "bien");
      })
      .catch(function () {
        avisar("No se pudo guardar tu elección. Probá otra vez.", "mal");
      })
      .then(function () { terminarEnvio(form, boton, null); });
  }

  /* --- 4. Buscar y filtrar el catálogo ---------------------------------- */

  // El rango de las tildes se arma con fromCharCode y no con un escape dentro
  // de la expresión regular: escritas a mano son marcas invisibles que
  // cualquier editor puede comerse sin avisar.
  var TILDES = new RegExp(
    "[" + String.fromCharCode(0x300) + "-" + String.fromCharCode(0x36f) + "]", "g"
  );

  // Sin acentos y en minúscula, para que «reflexion» encuentre «reflexión».
  function normalizar(texto) {
    return texto.toLowerCase().normalize("NFD").replace(TILDES, "");
  }

  var refiltrar = function () {};

  function armarFiltros() {
    var caja = uno("#filtros-cartas");
    if (!caja || caja.dataset.listo) return;

    // El texto de cada carta sale del propio HTML —título y desafíos, que ya
    // están en la página—. No hace falta mandar ni un byte de más.
    var cartas = todos("[data-carta]").map(function (nodo) {
      var titulo = uno("h3", nodo);
      var desafios = uno("details", nodo);
      return {
        nodo: nodo,
        texto: normalizar(
          (titulo ? titulo.textContent : "") + " " + (desafios ? desafios.textContent : "")
        ),
        area: nodo.dataset.area || ""
      };
    });
    if (!cartas.length) return;

    var buscador = uno("#buscar-carta", caja);
    var cuenta = uno("#cuenta-filtro", caja);
    var sinNada = uno("#sin-resultados");
    var elegido = { texto: "", area: "", cuales: "" };

    function aplicar() {
      var visibles = 0;
      cartas.forEach(function (carta) {
        var esMia = carta.nodo.classList.contains("elegida");
        var pasa =
          (!elegido.texto || carta.texto.indexOf(elegido.texto) >= 0) &&
          (!elegido.area || carta.area === elegido.area) &&
          (!elegido.cuales || (elegido.cuales === "elegidas") === esMia);
        carta.nodo.hidden = !pasa;
        if (pasa) visibles++;
      });
      // Un área sin nada que mostrar desaparece entera, con su franja.
      todos("[data-bloque-area]").forEach(function (bloque) {
        bloque.hidden = !uno("[data-carta]:not([hidden])", bloque);
      });
      if (sinNada) sinNada.hidden = visibles > 0;
      if (cuenta) {
        var filtrando = elegido.texto || elegido.area || elegido.cuales;
        cuenta.textContent = !filtrando
          ? cartas.length + " cartas"
          : visibles + " de " + cartas.length + " cartas";
      }
    }

    if (buscador) {
      buscador.addEventListener("input", function () {
        elegido.texto = normalizar(buscador.value.trim());
        aplicar();
      });
    }
    todos("[data-filtro]", caja).forEach(function (chip) {
      chip.addEventListener("click", function () {
        var grupo = chip.dataset.filtro;
        if (grupo === "area") elegido.area = chip.dataset.valor;
        else elegido.cuales = chip.dataset.valor;
        todos('[data-filtro="' + grupo + '"]', caja).forEach(function (otro) {
          otro.setAttribute("aria-pressed", otro === chip ? "true" : "false");
        });
        aplicar();
      });
    });

    caja.dataset.listo = "1";
    caja.hidden = false;
    refiltrar = aplicar;
    aplicar();
  }

  /* --- 5. Achicar la foto antes de subirla ------------------------------ */

  // Los mismos números que app/config.py: lo que el servidor iba a hacer de
  // todos modos, hecho antes de gastar los datos de quien sube la foto.
  var FOTO_LADO = 1600;
  var FOTO_CALIDAD = 0.82;

  function cajaDeFoto(entrada) {
    if (entrada._caja) return entrada._caja;
    var caja = document.createElement("div");
    caja.className = "vista-previa";
    caja.hidden = true;
    caja.innerHTML = '<img alt="La foto que se va a subir"><p class="meta"></p>';
    entrada.insertAdjacentElement("afterend", caja);
    entrada._caja = caja;
    return caja;
  }

  function achicarFoto(entrada) {
    var archivo = entrada.files && entrada.files[0];
    var caja = cajaDeFoto(entrada);
    if (entrada._previa) URL.revokeObjectURL(entrada._previa);
    entrada._achicada = null;
    entrada._previa = null;
    if (!archivo || archivo.size === 0) {
      caja.hidden = true;
      return;
    }

    caja.hidden = false;
    var leyenda = uno("p", caja);
    leyenda.hidden = false;
    leyenda.textContent = "Preparando la foto…";

    var origen = URL.createObjectURL(archivo);
    var imagen = new Image();
    imagen.onload = function () {
      var escala = Math.min(1, FOTO_LADO / Math.max(imagen.naturalWidth, imagen.naturalHeight));
      var ancho = Math.max(1, Math.round(imagen.naturalWidth * escala));
      var alto = Math.max(1, Math.round(imagen.naturalHeight * escala));
      var lienzo = document.createElement("canvas");
      lienzo.width = ancho;
      lienzo.height = alto;
      lienzo.getContext("2d").drawImage(imagen, 0, 0, ancho, alto);
      lienzo.toBlob(
        function (blob) {
          URL.revokeObjectURL(origen);
          // Solo se cambia si de verdad conviene: hay fotos que ya venían
          // chicas, y rehacerlas sería empeorarlas.
          var sirve = blob && blob.size < archivo.size;
          var mostrar = sirve ? blob : archivo;
          if (sirve) {
            entrada._achicada = { blob: blob, nombre: nombreJPEG(archivo.name) };
          }
          entrada._previa = URL.createObjectURL(mostrar);
          uno("img", caja).src = entrada._previa;
          // La vista previa muestra la foto y se calla: cuánto pesaba y si se
          // pudo achicar es asunto de acá adentro, no de quien la sube.
          leyenda.hidden = true;
        },
        "image/jpeg",
        FOTO_CALIDAD
      );
    };
    imagen.onerror = function () {
      // El navegador no supo abrirla: que la mande tal cual y decida el servidor.
      URL.revokeObjectURL(origen);
      caja.hidden = true;
    };
    imagen.src = origen;
  }

  function nombreJPEG(nombre) {
    return (nombre || "foto").replace(/\.[^.]*$/, "") + ".jpg";
  }

  /* --- 6. Cola de reintentos sin señal ---------------------------------- */

  var DIAS_QUE_ESPERA = 7;

  // La cola va por usuario: lo que quedó a medio mandar en este teléfono no
  // puede terminar entrando en la sesión de otra persona.
  function claveCola() {
    var id = document.body && document.body.dataset.usuario;
    return id ? "retos-pendientes-" + id : "";
  }

  function leerCola() {
    var clave = claveCola();
    if (!clave || !window.localStorage) return [];
    try {
      var viejo = Date.now() - DIAS_QUE_ESPERA * 24 * 3600 * 1000;
      return JSON.parse(localStorage.getItem(clave) || "[]").filter(function (item) {
        return item && item.url && item.cuando > viejo;
      });
    } catch (error) {
      return [];
    }
  }

  function escribirCola(cola) {
    var clave = claveCola();
    if (clave && window.localStorage) {
      try { localStorage.setItem(clave, JSON.stringify(cola.slice(-40))); } catch (error) { /* lleno */ }
    }
    var cartel = uno("#pendientes");
    if (!cartel) return;
    cartel.hidden = cola.length === 0;
    cartel.textContent = cola.length === 1
      ? "1 cambio esperando señal"
      : cola.length + " cambios esperando señal";
  }

  function encolar(form) {
    var campos = {};
    new FormData(form).forEach(function (valor, nombre) {
      // Solo texto: un archivo no entra en la cola, y tampoco tendría que.
      if (typeof valor === "string") campos[nombre] = valor;
    });
    var cola = leerCola().filter(function (item) { return item.url !== form.action; });
    cola.push({ url: form.action, campos: campos, cuando: Date.now() });
    escribirCola(cola);
  }

  function vaciarCola() {
    if (window.navigator.onLine === false) return;
    var cola = leerCola();
    if (!cola.length) return;

    var item = cola[0];
    var peticion = new XMLHttpRequest();
    peticion.open("POST", item.url, true);
    peticion.setRequestHeader("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
    peticion.setRequestHeader(CABECERA, "json");
    peticion.addEventListener("load", function () {
      // Se saca de la cola pase lo que pase. Si el servidor lo rechazó, volver
      // a intentarlo sería quedarse en un lazo para siempre.
      var resto = leerCola().filter(function (otro) {
        return !(otro.url === item.url && otro.cuando === item.cuando);
      });
      escribirCola(resto);
      if (resto.length) vaciarCola();
      else avisar("Se guardó lo que estaba esperando señal.", "bien");
    });
    // Si vuelve a fallar, se queda donde está y se prueba en el próximo intento.
    peticion.addEventListener("error", function () {});
    peticion.send(new URLSearchParams(item.campos).toString());
  }

  /* --- 7. Ver una foto en grande ---------------------------------------- */

  function hayDialogos() {
    return typeof HTMLDialogElement === "function" && !!HTMLDialogElement.prototype.showModal;
  }

  function verFoto(url, descripcion) {
    var visor = uno("#visor");
    if (!visor) {
      visor = document.createElement("dialog");
      visor.id = "visor";
      visor.className = "visor";
      visor.innerHTML =
        '<img alt=""><form method="dialog"><button class="secundario">Cerrar</button></form>';
      document.body.appendChild(visor);
      // Tocar el fondo también cierra: es lo que espera cualquiera.
      visor.addEventListener("click", function (evento) {
        if (evento.target === visor) visor.close();
      });
    }
    var imagen = uno("img", visor);
    imagen.src = url;
    imagen.alt = descripcion || "";
    visor.showModal();
  }

  /* --- 8. Confirmar sin salir de la página ------------------------------ */

  function confirmarAcá(form, seguir) {
    if (uno(".confirmacion", form)) return;
    var boton = uno("button", form);
    var caja = document.createElement("div");
    caja.className = "confirmacion";

    var texto = document.createElement("span");
    texto.textContent = form.dataset.confirmar;
    var si = document.createElement("button");
    si.type = "button";
    si.className = "peligro";
    si.textContent = "Sí";
    var no = document.createElement("button");
    no.type = "button";
    no.className = "secundario";
    no.textContent = "No";
    caja.appendChild(texto);
    caja.appendChild(si);
    caja.appendChild(no);

    if (boton) boton.hidden = true;
    form.appendChild(caja);
    no.focus(); // el foco arranca en «No»: borrar es lo que hay que querer

    function cerrar() {
      caja.remove();
      if (boton) boton.hidden = false;
    }
    no.addEventListener("click", cerrar);
    si.addEventListener("click", function () {
      cerrar();
      seguir();
    });
  }

  /* --- 9. Refresco solo y atajos de teclado ----------------------------- */

  function hayAlgoSinGuardar() {
    return todos("form[data-autoguardar]").some(function (form) {
      return form.dataset.firma && firma(form) !== form.dataset.firma;
    });
  }

  function refrescoSolo() {
    var marca = uno("[data-refrescar]");
    if (!marca) return;
    var cada = (parseInt(marca.dataset.refrescar, 10) || 30) * 1000;

    setInterval(function () {
      // Nada de repintar por detrás de alguien que está escribiendo, mirando
      // una foto o a punto de confirmar algo.
      if (document.visibilityState !== "visible") return;
      if (uno("form[aria-busy]") || uno(".confirmacion") || uno("dialog[open]")) return;
      if (hayAlgoSinGuardar()) return;

      var peticion = new XMLHttpRequest();
      peticion.open("GET", location.pathname + location.search, true);
      peticion.setRequestHeader(CABECERA, "pagina");
      peticion.addEventListener("load", function () {
        if (peticion.status !== 200) return;
        var documento = new DOMParser().parseFromString(peticion.responseText, "text/html");
        var nuevo = uno("main", documento);
        var actual = uno("main");
        // Si no cambió nada no se toca la pantalla: repintar por repintar hace
        // parpadear la página y le borra la selección a quien está leyendo.
        if (!nuevo || !actual || nuevo.innerHTML === actual.innerHTML) return;
        reemplazarPagina(documento, null);
      });
      peticion.send();
    }, cada);
  }

  var entregaEnfoque = "";

  function enfocarEntrega(id) {
    var lista = todos("[data-entrega]");
    if (!lista.length) return;
    var elegida = null;
    lista.forEach(function (tarjeta) {
      var suya = tarjeta.dataset.entrega === id;
      tarjeta.classList.toggle("enfocada", suya);
      if (suya) elegida = tarjeta;
    });
    if (!elegida) {
      elegida = lista[0];
      elegida.classList.add("enfocada");
    }
    entregaEnfoque = elegida.dataset.entrega;
    return elegida;
  }

  function moverEnfoque(paso) {
    var lista = todos("[data-entrega]");
    if (!lista.length) return;
    var donde = 0;
    lista.forEach(function (tarjeta, indice) {
      if (tarjeta.dataset.entrega === entregaEnfoque) donde = indice;
    });
    var siguiente = Math.min(lista.length - 1, Math.max(0, donde + paso));
    var tarjeta = enfocarEntrega(lista[siguiente].dataset.entrega);
    if (tarjeta) tarjeta.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function atajosDeValidacion(evento) {
    if (!uno("[data-atajos='validaciones']")) return;
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    var donde = evento.target;
    if (donde && (donde.isContentEditable ||
        /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(donde.tagName))) return;

    var tecla = evento.key.toLowerCase();
    if (tecla === "j" || evento.key === "ArrowDown") {
      evento.preventDefault();
      moverEnfoque(1);
    } else if (tecla === "k" || evento.key === "ArrowUp") {
      evento.preventDefault();
      moverEnfoque(-1);
    } else if (tecla === "a" || tecla === "f" || tecla === "d" || tecla === "r") {
      var decisiones = { a: "aprobar", f: "felicitar", d: "devolver", r: "rechazar" };
      var tarjeta = uno("[data-entrega].enfocada") || uno("[data-entrega]");
      var boton = tarjeta && uno('button[value="' + decisiones[tecla] + '"]', tarjeta);
      if (boton) {
        evento.preventDefault();
        // Felicitar sin escribir nada no manda nada: el atajo deja el cursor
        // donde hay que escribir en vez de rebotar contra el servidor.
        var texto = uno("textarea[name=devolucion]", tarjeta);
        if (tecla === "f" && texto && !texto.value.trim()) texto.focus();
        else boton.click();
      }
    }
  }

  /* --- Enganches -------------------------------------------------------- */

  // `evento.submitter` es nuevo para algunos celulares viejos: se anota
  // a mano cuál fue el último botón apretado por si no viene.
  document.addEventListener("click", function (evento) {
    var boton = evento.target.closest && evento.target.closest("button, input[type=submit]");
    if (boton && boton.form) boton.form._ultimoBoton = boton;
  }, true);

  document.addEventListener("submit", function (evento) {
    // Un `onsubmit` que devolvió false ya canceló el envío: es el
    // «¿seguro que querés borrar?». No hay que pasarle por encima.
    if (evento.defaultPrevented) return;
    var form = evento.target;
    if (!(form instanceof HTMLFormElement)) return;
    var boton = evento.submitter || form._ultimoBoton || null;

    if (form.matches("[data-autoguardar]")) {
      evento.preventDefault();
      guardar(form);
    } else if (form.matches("[data-elegir]")) {
      evento.preventDefault();
      alternarCarta(form, boton);
    } else if (form.matches("[data-sin-recarga]")) {
      evento.preventDefault();
      if (form.dataset.confirmar) {
        confirmarAcá(form, function () { enviarYRepintar(form, boton); });
      } else {
        enviarYRepintar(form, boton);
      }
    }
  });

  // Una foto elegida se achica antes de que nadie apriete «enviar».
  document.addEventListener("change", function (evento) {
    var entrada = evento.target;
    if (entrada.type === "file" && /image/.test(entrada.accept || "")) achicarFoto(entrada);
  });

  // Ver una foto en grande sin irse de la página.
  document.addEventListener("click", function (evento) {
    if (evento.defaultPrevented || evento.button || evento.metaKey || evento.ctrlKey ||
        evento.shiftKey || !hayDialogos()) return;
    var enlace = evento.target.closest && evento.target.closest('a[href^="/fotos/"]');
    if (!enlace) return;
    var imagen = uno("img", enlace);
    evento.preventDefault();
    verFoto(enlace.getAttribute("href"), imagen ? imagen.alt : "");
  });

  document.addEventListener("keydown", atajosDeValidacion);

  // El menú de la cuenta se cierra solo al tocar en cualquier otro lado. Sin
  // esto sigue andando —es un <details>, se cierra tocando el avatar otra vez—,
  // pero un menú que se queda abierto tapando la página se siente roto.
  document.addEventListener("click", function (evento) {
    todos("[data-menu-usuario][open]").forEach(function (menu) {
      if (!menu.contains(evento.target)) menu.open = false;
    });
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "Escape") return;
    todos("[data-menu-usuario][open]").forEach(function (menu) {
      menu.open = false;
      var boton = uno("summary", menu);
      if (boton) boton.focus();
    });
  });

  window.addEventListener("online", vaciarCola);

  document.addEventListener("input", function (evento) {
    var form = evento.target.closest && evento.target.closest("form[data-autoguardar]");
    if (form) programarGuardado(form);
  });

  document.addEventListener("change", function (evento) {
    var campo = evento.target;
    var form = campo.closest && campo.closest("form[data-autoguardar]");
    if (!form) return;
    // La casilla se pinta antes de que conteste el servidor: tildar algo
    // que hiciste tiene que sentirse inmediato.
    if (campo.type === "checkbox") {
      var tarjeta = campo.closest(".desafio");
      if (tarjeta) tarjeta.classList.toggle("hecho", campo.checked);
    }
    guardar(form);
  });

  // Al salir de un campo no se espera el temporizador.
  document.addEventListener("focusout", function (evento) {
    var form = evento.target.closest && evento.target.closest("form[data-autoguardar]");
    if (form) guardar(form);
  });

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") despedirse();
  });
  window.addEventListener("pagehide", despedirse);

  // La firma de arranque es lo que vino del servidor: hasta que alguien
  // toque algo, no hay nada para guardar.
  function memorizarFirmas() {
    todos("form[data-autoguardar]").forEach(function (form) {
      if (!form.dataset.firma) form.dataset.firma = firma(form);
    });
  }

  // Todo lo que hay que rehacer cuando la página se repinta sola.
  function acomodar() {
    memorizarFirmas();
    armarFiltros();
    // El `confirm()` del navegador es el plan B para quien no tiene
    // JavaScript. Con JavaScript se pregunta adentro de la tarjeta.
    todos("form[data-confirmar]").forEach(function (form) {
      form.removeAttribute("onsubmit");
      form.onsubmit = null;
    });
    // Los atajos se anuncian solo donde hay teclado de verdad: en un celular
    // serían tres renglones que no le sirven a nadie.
    var atajos = uno("[data-atajos]");
    if (atajos && window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
      atajos.hidden = false;
    }
    // El recuadro naranja recién aparece cuando alguien usó el teclado.
    if (entregaEnfoque && uno("[data-entrega]")) enfocarEntrega(entregaEnfoque);
  }

  function arrancar() {
    acomodar();
    escribirCola(leerCola()); // muestra el cartel si quedó algo de la vez pasada
    vaciarCola();
    refrescoSolo();
    // El evento `online` no siempre llega —el celular cree que hay señal y no
    // la hay—, así que además se prueba cada tanto mientras quede algo.
    setInterval(function () {
      if (document.visibilityState === "visible" && leerCola().length) vaciarCola();
    }, 45000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", arrancar);
  } else {
    arrancar();
  }
  // Después de repintar la página aparecen formularios nuevos.
  new MutationObserver(memorizarFirmas).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
