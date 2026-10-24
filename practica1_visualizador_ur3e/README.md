# Práctica 1. Visualizador UR3e

Conjunto de herramientas en Python para comunicarse con un robot **Universal Robots UR3e**
a través de sus interfaces TCP:

- **Monitorizar** uno o varios robots (posición articular en directo) por la interfaz
  primaria (puerto 30001, 10 Hz) o por la de tiempo real (puerto 30003, 500 Hz), y
  representarlos en un visualizador 3D (`UR3eRG2`, basado en PyBullet).
- **Mover** el robot a una posición enviando un programa URScript y **verificar** que la
  ha alcanzado.
- **Aprender y copiar**: capturar posiciones moviendo el robot a mano y reproducirlas
  punto a punto.
- Hacer todo lo anterior desde un **panel web local**, también disponible como
  **ejecutable de Windows** que no necesita Python.

## Índice

1. [Estructura del proyecto](#estructura-del-proyecto)
2. [Requisitos e instalación](#requisitos-e-instalación)
3. [Uso de cada script desde la línea de comandos](#uso-de-cada-script-desde-la-línea-de-comandos)
4. [Panel web desde la terminal](#panel-web-desde-la-terminal)
5. [Ejecutable (.exe)](#ejecutable-exe)
6. [Comportamiento común y seguridad](#comportamiento-común-y-seguridad)

## Estructura del proyecto

```
practica1_visualizador_ur3e/
├── src/
│   └── visualizador_ur3e/          # paquete principal
│       ├── comun/
│       │   └── ur_protocol.py      # decodificación de la interfaz primaria y del Dashboard Server
│       ├── clientes/               # monitorización (solo lectura)
│       │   ├── primaria.py         # interfaz primaria, puerto 30001, 10 Hz
│       │   └── tiempo_real.py      # interfaz de tiempo real, puerto 30003, 500 Hz
│       ├── control/                # herramientas que MUEVEN el robot
│       │   ├── escribir.py         # mover a una posición y verificarla
│       │   └── aprender_copiar.py  # capturar posiciones y reproducirlas
│       └── web/                    # panel web local
│           ├── interfaz_web.py     # servidor HTTP (127.0.0.1)
│           └── interfaz/           # página: index.html, estilos.css, app.js
├── data/                           # secuencias guardadas (.json, no se versionan)
├── docs/                           # posibles mejoras (mejoras.md)
├── wheels/                         # aquí se copia la librería UR3e_rg2 (no se versiona)
├── requirements.txt                # dependencias con las versiones probadas
├── requirements-build.txt          # + PyInstaller, solo para generar el ejecutable
└── panel_ur3e.spec                 # configuración de PyInstaller
```

| Paquete | Para qué sirve | ¿Mueve el robot? |
|---|---|---|
| `comun` | Código compartido: lectura de mensajes del robot. No se ejecuta por sí solo. | No |
| `clientes` | Leer la posición articular de uno o varios robots y mostrarla en el visualizador 3D. | No |
| `control` | Enviar movimientos al robot y comprobar que se han realizado. | **Sí** |
| `web` | Panel en el navegador que reúne las funciones de `clientes` y `control`. | **Sí** (Enseñar y reproducir) |

Puertos del robot utilizados:

| Puerto | Interfaz | Uso |
|---|---|---|
| 30001 | Primaria | Estado del robot (10 Hz) y envío de programas URScript |
| 30003 | Tiempo real | Posición articular (500 Hz) |
| 29999 | Dashboard Server | Consulta de control remoto (`is in remote control`), solo en el panel web |

En `docs/` está [`mejoras.md`](docs/mejoras.md) con posibles mejoras.

Documentación de referencia de Universal Robots utilizada (no se incluye en el
repositorio por derechos de autor; se descarga desde la web de soporte de Universal
Robots):

- *Client Interfaces*: formato de los mensajes de la interfaz primaria (30001).
- *Client Interfaces*: formato de los mensajes de la interfaz de tiempo real (30003).
- *The URScript Programming Language* (e-Series): instrucciones como `movej`.

## Requisitos e instalación

- **Python 3.15** (es la versión probada; el código necesita como mínimo Python 3.10).
- El PC en la **misma red** que el robot y con soporte **OpenGL** para la ventana del
  visualizador.
- La librería del curso **`UR3e_rg2`** (`ur3e_rg2-0.1.0-py3-none-any.whl`). No está en
  PyPI ni se incluye en este repositorio: se obtiene de los materiales de la asignatura
  y se copia en la carpeta `wheels/`.
- `pybullet` y `recordclass` no tienen paquetes precompilados para Python 3.15, así que
  `pip` los compila: hacen falta las **Microsoft C++ Build Tools**. Para usar el panel
  sin instalar nada, mejor el [ejecutable](#ejecutable-exe).

Instalación, desde la carpeta `practica1_visualizador_ur3e/`:

```powershell
python -m venv .venv
.venv\Scripts\activate             # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Uso de cada script desde la línea de comandos

Los scripts forman parte del paquete `visualizador_ur3e`, así que se ejecutan como
módulos con `python -m` **desde la carpeta `src/`**:

```powershell
cd src
python -m visualizador_ur3e.<paquete>.<script> [opciones]
```

En Linux/macOS se usa `python3` en lugar de `python`. Todos los scripts aceptan `--help`.
Cuando no se indica la IP se usa `10.172.18.80`, la IP por defecto del laboratorio:
**comprueba siempre la IP del robot antes de ejecutar cualquier script.**

### `clientes/primaria.py`: monitorización por la interfaz primaria

Se conecta al puerto 30001 de cada robot, lee su posición articular (10 Hz) y la
reproduce en el visualizador 3D, con un robot simulado por IP separados 0,8 m.

```powershell
python -m visualizador_ur3e.clientes.primaria --hosts <IP>
python -m visualizador_ur3e.clientes.primaria --hosts 192.168.1.157 192.168.1.158
```

| Opción | Descripción | Por defecto |
|---|---|---|
| `--hosts IP [IP ...]` | Una o varias IP de robots; cada una se atiende en su propio hilo | `10.172.18.80` |

### `clientes/tiempo_real.py`: monitorización por la interfaz de tiempo real

Igual que `primaria.py`, pero por el puerto 30003, a 500 Hz. Si el visualizador es más
lento que el robot, se aplica siempre la posición más reciente, de modo que no se acumula
retraso.

```powershell
python -m visualizador_ur3e.clientes.tiempo_real --hosts <IP>
```

| Opción | Descripción | Por defecto |
|---|---|---|
| `--hosts IP [IP ...]` | Una o varias IP de robots | `10.172.18.80` |

### `control/escribir.py`: mover el robot y verificar la posición

Envía un programa URScript con un `movej` a la posición objetivo (`TARGET_JOINTS` en el
script, `[0, -1,5, 0, -1,5, 0, 0]` rad), sigue su ejecución y comprueba que todas las
articulaciones quedan a menos de 0,01 rad del objetivo. Se detiene si el robot entra en
parada de emergencia o protectiva. **El robot se mueve.**

```powershell
python -m visualizador_ur3e.control.escribir --host <IP>
python -m visualizador_ur3e.control.escribir --host <IP> --test-failure
```

| Opción | Descripción | Por defecto |
|---|---|---|
| `--host IP` | IP del robot | `10.172.18.80` |
| `--startup-timeout S` | Segundos que se espera a que el programa empiece | `2.0` |
| `--test-failure` | Envía una instrucción inválida para probar el informe de errores | desactivado |

Devuelve el código de salida 0 si la posición se ha verificado y 1 en cualquier otro caso.

### `control/aprender_copiar.py`: aprender y copiar

Tiene dos modos.

**`aprender`**: mueve el robot con el teach pendant y captura cada posición desde la
terminal.

```powershell
python -m visualizador_ur3e.control.aprender_copiar aprender --host <IP>
python -m visualizador_ur3e.control.aprender_copiar aprender --host <IP> --file ..\data\mi_secuencia.json
```

| Tecla + Enter | Acción |
|---|---|
| `c` | Capturar la posición actual |
| `d` | Borrar el último punto |
| `l` | Listar los puntos |
| `f` | Terminar y guardar |
| `q` | Salir sin guardar |

Sin `--file`, la secuencia se guarda en `data/secuencia_<fecha>_<hora>.json`. Nunca se
sobrescribe un archivo existente.

**`copiar`**: reproduce una secuencia guardada punto a punto, verificando cada movimiento.
Antes de empezar muestra los puntos y pide confirmación con `y`. **El robot se mueve**
desde su posición actual hasta el punto 1.

```powershell
python -m visualizador_ur3e.control.aprender_copiar copiar --file ..\data\mi_secuencia.json
python -m visualizador_ur3e.control.aprender_copiar copiar --file ..\data\mi_secuencia.json --host <IP>
```

Sin `--host` se usa el robot en el que se grabó la secuencia. Si un punto falla, se
puede elegir: `r` reintentar el punto, `s` empezar de nuevo desde el punto 1, `x` cancelar.

| Opción | Modo | Descripción | Por defecto |
|---|---|---|---|
| `--host IP` | aprender | IP del robot | `10.172.18.80` |
| `--host IP` | copiar | IP del robot | la guardada en la secuencia |
| `--file RUTA` | aprender | Dónde guardar la secuencia | `data/secuencia_<fecha>.json` |
| `--file RUTA` | copiar | Secuencia a reproducir (obligatorio) | — |

Formato del archivo de secuencia:

```json
{
  "format_version": 1,
  "created": "2026-10-22T10:15:03",
  "host": "10.172.18.80",
  "units": "rad",
  "points": [
    [0.0, -1.5708, 0.0, -1.5708, 0.0, 0.0],
    [0.5236, -1.2217, -0.6981, -1.2217, 1.5708, 0.0]
  ]
}
```

## Panel web desde la terminal

```powershell
cd src
python -m visualizador_ur3e.web.interfaz_web
```

Abre el navegador en `http://127.0.0.1:8000`. La terminal muestra el registro y el panel
se detiene con `Ctrl+C`.

| Opción | Descripción | Por defecto |
|---|---|---|
| `--port N` | Puerto local del panel | `8000` |
| `--no-browser` | No abrir el navegador automáticamente | desactivado |

Páginas del panel:

- **Monitorización**: escribe la IP de un robot, elige *Primaria · 30001* o
  *Tiempo real · 30003* y pulsa **Añadir host**. Cada robot muestra su estado de
  conexión, su posición articular y, por la interfaz primaria, el selector de modo de
  operación y el control remoto. Se pueden añadir y quitar robots en cualquier momento.
- **Abrir visualizador**: abre la ventana 3D `UR3eRG2` con un robot por host. Si se
  cierra con la X, se puede volver a abrir.
- **Enseñar y reproducir**: indica el **host de captura** y pulsa **Capturar punto** para
  cada posición. **Guardar puntos en JSON** y **Cargar JSON** usan la carpeta `data/`.
  **Guardar y ejecutar** reproduce la secuencia (en el *host de ejecución* si se indica,
  si no en el de captura) tras pedir confirmación. Si un punto falla, el panel pregunta
  si reintentar, empezar de nuevo o cancelar.

El panel solo escucha en `127.0.0.1`: no es accesible desde otros equipos de la red. La
página se actualiza unas 3 veces por segundo; el visualizador 3D sigue la frecuencia
del robot.

## Ejecutable (.exe)

### Usarlo

1. Descomprime `panel_ur3e.zip` (se entrega junto con la URL de este repositorio).
2. Ejecuta `panel_ur3e\panel_ur3e.exe`. Se abre el panel en el navegador y una consola
   con el registro. Para cerrarlo, cierra la consola o pulsa `Ctrl+C` en ella.
3. Las secuencias se guardan en la carpeta `data\` junto al `.exe`.

Las opciones son las mismas que en la terminal, por ejemplo
`panel_ur3e.exe --port 8080 --no-browser`. No hace falta tener Python instalado. El
ejecutable contiene solo el panel web; los scripts de línea de comandos se usan con
Python como se explica arriba.

### Generarlo

Desde `practica1_visualizador_ur3e/`, con el entorno virtual activado y la librería
`UR3e_rg2` instalada:

```powershell
pip install -r requirements-build.txt
pyinstaller panel_ur3e.spec
```

El resultado queda en `dist/panel_ur3e/`. Para repartirlo, comprime la carpeta entera.

## Comportamiento común y seguridad

- Cada robot se atiende en su propio hilo. Si se pierde la conexión, el script la
  detecta (o tras 2 s sin datos) y se reconecta cada segundo; datos con un formato
  inesperado detienen solo ese robot.
- Todos los scripts se detienen con `Ctrl+C` sin mostrar errores.
- **`escribir.py`, `aprender_copiar.py copiar` y el panel (Enseñar y reproducir) mueven
  el robot.** Comprueba que la zona de trabajo está despejada y que el robot está en
  control remoto antes de usarlos. La aceleración y la velocidad (`ACCELERATION` y
  `VELOCITY` en `escribir.py`) deben ajustarse a los límites de seguridad del laboratorio.
- `Ctrl+C` detiene el script, pero el robot termina el movimiento que ya ha recibido.
