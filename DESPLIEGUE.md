# Poner la aplicación en Azure Container Apps

La aplicación entera es un contenedor: un proceso de Python que sirve las
páginas y la API, con la base SQLite y las fotos en un directorio aparte.
Container Apps la puede tener apagada mientras nadie la usa y encenderla sola
cuando alguien entra, que es lo que la deja adentro del nivel gratuito.

Lo que hay que tener instalado: [Docker](https://docs.docker.com/get-docker/)
para construir la imagen y la [CLI de Azure](https://learn.microsoft.com/cli/azure/install-azure-cli)
para el resto. En esta máquina hoy no está ninguno de los dos.

## Lo que ya está creado

Los pasos 2, 3 y 4 de más abajo ya se corrieron una vez. Quedaron estos recursos,
todos en **Brazil South** —la región madura más cercana a Argentina, unos 40 ms
desde Buenos Aires—, y los nombres son los que usan los comandos de acá en
adelante:

| recurso | nombre |
|---|---|
| suscripción | `Azure subscription 1` (`0f782193-8410-4948-9621-1b3d8e1a09ab`) |
| grupo de recursos | `retos-unidad` |
| cuenta de almacenamiento | `retosdatos268291` |
| recurso de archivos | `retos-datos`, 5 GB |
| entorno | `retos-entorno`, con el almacenamiento enganchado como `datos` |

Falta la aplicación en sí, que es el paso 5: necesita la imagen publicada.

## Antes que nada, probarlo en casa

Vale la pena ver el contenedor andando en la máquina antes de subirlo. Es el
mismo que va a correr en el servidor.

```bash
docker compose up --build
docker compose run --rm web python scripts/inicializar_db.py --demo   # usuarios de prueba
```

En http://localhost:8000, con `educador` / `scout1907`. Si eso anda, lo que
falta es solamente dónde ponerlo.

## Lo que la imagen da por sentado

| | |
|---|---|
| `/datos-persistentes` | la base y las fotos. **Es lo único que hay que montar en un volumen**: todo lo demás se rehace construyendo la imagen de nuevo. |
| puerto `8000` | lo que escucha uvicorn; se cambia con `PUERTO`. |
| un solo proceso | SQLite quiere un único escritor. Por eso el máximo de réplicas es 1. |
| arranque | corre `scripts/inicializar_db.py` solo, así que sobre un volumen vacío la base se arma sin que nadie entre por consola. |

## Las variables que hay que definir

| variable | en el servidor | por qué |
|---|---|---|
| `CLAVE_SECRETA` | una cadena larga y aleatoria, **como secreto** | sin ella todas las sesiones se caen en cada reinicio, y el valor por defecto es público. |
| `COOKIES_SEGURAS` | `1` | Container Apps sirve por HTTPS; la cookie de sesión tiene que ir marcada `Secure`. |
| `SQLITE_JOURNAL` | `DELETE` | sobre Azure Files el modo WAL no funciona: necesita memoria compartida entre procesos, que en un recurso de red no existe. |
| `ZONA_HORARIA` | `America/Argentina/Buenos_Aires` | con qué reloj se decide qué día es hoy para los retos. |
| `VALIDADOR` | `simulado` o `manual` | quién revisa las evidencias. |

Para generar la clave:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Los pasos

Los nombres van en variables para no repetirlos; `CUENTA` tiene que ser único en
todo Azure y admite solo minúsculas y números.

```bash
GRUPO=retos-unidad
UBICACION=eastus
ENTORNO=retos-entorno
APP=retos-unidad
CUENTA=retosdatos$RANDOM
RECURSO=retos-datos
USUARIO_GH=tu-usuario-de-github
IMAGEN=ghcr.io/$USUARIO_GH/retos-unidad:latest
```

### 1. La imagen, en un registro público

Azure tiene su propio registro, pero el más chico cuesta unos 5 USD por mes.
El de GitHub es gratis, así que la imagen va ahí. En el contenedor no hay
ningún secreto —la clave la pone Azure al arrancarlo—, así que puede ser
público sin problema.

Hace falta un token de GitHub con permiso `write:packages`
(Settings → Developer settings → Personal access tokens).

```bash
docker build -t $IMAGEN .
echo $TOKEN_GH | docker login ghcr.io -u $USUARIO_GH --password-stdin
docker push $IMAGEN
```

La primera vez el paquete queda privado: hay que entrar a
`github.com/users/$USUARIO_GH/packages`, abrir `retos-unidad` y ponerlo en
público. Si no, Azure no lo va a poder bajar.

### 2. La cuenta de Azure y el grupo

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

az group create --name $GRUPO --location $UBICACION
```

### 3. El disco donde viven la base y las fotos

El contenedor se apaga y se vuelve a crear cada vez que Azure quiere; su disco
se va con él. Sin esto se pierde todo en el primer reinicio.

5 GB es varias veces más de lo que esto va a ocupar —el Libro de Oro entero de
un año son decenas de MB— y es el mínimo cómodo.

```bash
az storage account create --name $CUENTA --resource-group $GRUPO \
    --location $UBICACION --sku Standard_LRS --kind StorageV2

az storage share-rm create --resource-group $GRUPO \
    --storage-account $CUENTA --name $RECURSO --quota 5

CLAVE_CUENTA=$(az storage account keys list --resource-group $GRUPO \
    --account-name $CUENTA --query "[0].value" --output tsv)
```

### 4. El entorno, y el disco enganchado al entorno

```bash
az containerapp env create --name $ENTORNO --resource-group $GRUPO \
    --location $UBICACION

az containerapp env storage set --name $ENTORNO --resource-group $GRUPO \
    --storage-name datos \
    --azure-file-account-name $CUENTA \
    --azure-file-account-key $CLAVE_CUENTA \
    --azure-file-share-name $RECURSO \
    --access-mode ReadWrite
```

### 5. La aplicación

El volumen no se puede declarar con banderas sueltas, así que la aplicación se
crea desde un archivo. Está en [azure/containerapp.yaml](azure/containerapp.yaml)
y hay cuatro cosas para completar adentro, todas marcadas con `PONER-`.

Para el identificador del entorno:

```bash
az containerapp env show --name $ENTORNO --resource-group $GRUPO \
    --query id --output tsv
```

Y con el archivo completo:

```bash
az containerapp create --name $APP --resource-group $GRUPO \
    --yaml azure/containerapp.yaml

az containerapp show --name $APP --resource-group $GRUPO \
    --query properties.configuration.ingress.fqdn --output tsv
```

Eso último imprime la dirección. Andá a `https://` + eso.

### 6. El primer educador

La aplicación no trae ninguna cuenta: el resto —patrullas y jóvenes— se carga
después desde la propia pantalla del educador, pero el primero hay que crearlo
por consola.

Con `minReplicas: 0` el contenedor está apagado hasta que alguien entra, así que
primero abrí la dirección en el navegador y recién después:

```bash
az containerapp exec --name $APP --resource-group $GRUPO --command sh
```

Ya adentro, con el nombre y la contraseña que quieras:

```bash
python scripts/crear_educador.py educador "Nombre y Apellido" "una-contraseña-buena"
```

Si no hay ninguna Unidad todavía la crea de paso, y si el usuario ya existe
avisa y no pisa nada. El mismo script sirve para el resto del equipo de
educadores, que tampoco tiene un alta propia en la aplicación.

**Elegí bien la contraseña la primera vez: la aplicación no tiene pantalla para
cambiarla.** Cambiarla es volver a entrar por acá.

> **No sirve pasar el comando con `--command`.** `az containerapp exec
> --command "python ... 'Nombre y Apellido' ..."` **no** respeta las comillas:
> parte todo por espacios y los argumentos llegan cortados. Hay que abrir la
> consola con `--command sh` y escribir la línea ahí adentro, donde el shell del
> contenedor sí las interpreta.

## Actualizar la aplicación

Tres pasos: construir, empujar, y avisarle a Azure.

```bash
SHA=$(git rev-parse --short HEAD)
docker build -t ghcr.io/$USUARIO_GH/retos-unidad:latest \
             -t ghcr.io/$USUARIO_GH/retos-unidad:$SHA .
docker push ghcr.io/$USUARIO_GH/retos-unidad:$SHA
docker push ghcr.io/$USUARIO_GH/retos-unidad:latest
az containerapp update --name $APP --resource-group $GRUPO \
    --image ghcr.io/$USUARIO_GH/retos-unidad:$SHA
```

**La etiqueta con el commit no es un adorno.** Si se despliega siempre
`:latest`, `az containerapp update` ve la misma cadena de texto que ya tenía y
puede no crear una revisión nueva: la aplicación se queda con la imagen vieja y
no hay ningún error que lo delate. Con una etiqueta distinta por commit el
despliegue es inequívoco, y además se puede volver atrás apuntando a la
anterior:

```bash
az containerapp revision list --name $APP --resource-group $GRUPO --output table
```

Las columnas nuevas del esquema las agrega el propio arranque, así que no hay
un paso de migración aparte (ver `COLUMNAS_NUEVAS` en
`scripts/inicializar_db.py`).

## Qué es lo gratuito, y hasta dónde

Container Apps regala por mes y por suscripción **180.000 vCPU-segundo,
360.000 GiB-segundo y 2 millones de peticiones**. Con los 0,25 vCPU y 0,5 GiB
del archivo, esos 180.000 vCPU-segundo son unas **200 horas de contenedor
encendido al mes**.

Ahí está la razón de `minReplicas: 0`: el contenedor solo está prendido mientras
alguien lo usa y se apaga solo a los pocos minutos de quedar quieto. Una Unidad
que entra un rato después del colegio y el sábado a la mañana no llega ni cerca
del tope. Con una réplica prendida las 24 horas, en cambio, se pasa el día 9 del
mes.

Lo que se paga igual: el recurso de Azure Files, unos centavos por mes con
menos de 1 GB adentro. Los registros del entorno van a Log Analytics, que tiene
sus primeros 5 GB por mes sin cargo y esto no los va a rozar. Los precios
cambian; conviene mirar la
[calculadora](https://azure.microsoft.com/pricing/calculator/) antes de dar por
sentado un número.

El costo de tener el contenedor apagado es que la primera visita después de un
rato quieto tarda unos segundos en levantar. Para esto no molesta.

## Si algo no anda

**La primera visita tarda y después va rápido.** Es el arranque en frío. Se
saca poniendo `minReplicas: 1`, pero eso deja de ser gratis.

**`database is locked` o `disk I/O error`.** Es SQLite peleándose con el disco
de red. Lo primero para revisar es que `SQLITE_JOURNAL` esté en `DELETE` y que
`maxReplicas` sea 1: dos contenedores escribiendo el mismo archivo por SMB no
terminan bien. Si aun así aparece, el que falta es el bloqueo por rangos de
bytes, que SMB no maneja igual que un disco local, y se desactiva con `nobrl`
entre las opciones de montaje del recurso. Ojo que **la extensión `containerapp`
1.3.0b4 no tiene ninguna bandera para eso**: `az containerapp env storage set`
no expone `mountOptions`, así que habría que tocar el recurso por ARM/REST.
Vale revisarlo recién si el problema aparece de verdad: con un solo escritor y
el journal en `DELETE` puede no aparecer nunca.

**Se pierden los datos al reiniciar.** El volumen no quedó montado.
`az containerapp show --name $APP --resource-group $GRUPO --query
properties.template.volumes` tiene que devolver el de tipo `AzureFile`.

**Azure no puede bajar la imagen.** El paquete de GitHub quedó privado.

**Entra al ingreso pero vuelve a pedir la contraseña.** La cookie de sesión no
está volviendo: revisar que `CLAVE_SECRETA` esté definida y que
`COOKIES_SEGURAS` sea `1`.

**Ver qué pasó:**

```bash
az containerapp logs show --name $APP --resource-group $GRUPO --follow
```

## Llevarse los datos

Todo lo que importa está en el recurso de Azure Files: `scout.db` y `uploads/`.
Se puede montar como unidad de red desde el Explorador de Windows —Azure da el
comando hecho en el portal, en la pestaña *Conectar* del recurso— y copiarlo
como cualquier carpeta. Las dos cosas van juntas: la base sin las fotos deja al
Libro de Oro sin imágenes.
