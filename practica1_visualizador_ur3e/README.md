# Practica 1. Visualizador UR3e

Cliente en Python que se conecta al servidor de un robot UR3e, recibe los datos
que este publica y los visualiza.

## Estructura

```
practica1_visualizador_ur3e/
├── src/              # Codigo fuente del cliente y del visualizador
├── tests/            # Pruebas (p. ej. decodificacion de paquetes)
├── data/             # Capturas de datos del robot para pruebas offline
├── docs/             # Enunciado, documentacion del protocolo, notas
├── wheels/           # Libreria UR3e_rg2 del curso (no esta en PyPI)
├── requirements.txt        # Dependencias de Python (versiones probadas)
├── requirements-build.txt  # + PyInstaller, solo para generar el ejecutable
└── panel_ur3e.spec         # Configuracion de PyInstaller
```

## Puesta en marcha

Desde esta carpeta, con Python 3.15:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`pybullet` y `recordclass` no tienen paquetes precompilados para Python 3.15, asi que
`pip` los compila: hace falta tener instaladas las *Microsoft C++ Build Tools*.
Para usar el programa en otro equipo sin instalar nada, mejor el ejecutable (ver abajo).

## Uso

```bash
python src/primaria.py                       # puerto primario (30001), IP por defecto
python src/tiempo_real.py --hosts 192.168.1.157 192.168.1.158   # puerto de tiempo real (30003), dos robots
python src/escribir.py --host 10.172.18.80          # envia un programa y verifica la posicion final
python src/aprender_copiar.py aprender --host 192.168.1.157 --file data/prueba.json   # captura puntos con c + Enter
python src/aprender_copiar.py copiar --file data/prueba.json                          # los repite punto a punto
python src/interfaz_web.py                                # interfaz web local en http://127.0.0.1:8000
```

Cada IP se atiende en su propio hilo; todos comparten un simulador `UR3eRG2` con un robot por IP.
Los scripts se reconectan solos si se pierde la conexion y se detienen con `Ctrl+C`.

## Ejecutable

```bash
pip install -r requirements-build.txt
pyinstaller panel_ur3e.spec
```

Genera `dist/panel_ur3e/`. Para repartirlo, comprimir la carpeta entera y ejecutar
`panel_ur3e.exe`: abre la interfaz web en el navegador y la consola muestra el registro.
Las secuencias se guardan en `dist/panel_ur3e/data/`. El equipo debe estar en la misma
red que el robot y soportar OpenGL para la ventana del visualizador.

Posibles mejoras pendientes: [docs/mejoras.md](docs/mejoras.md).
