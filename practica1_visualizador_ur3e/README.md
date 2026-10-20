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
└── requirements.txt  # Dependencias de Python
```

## Puesta en marcha

```bash
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
python src/primaria.py                       # puerto primario (30001), IP por defecto
python src/tiempo_real.py --hosts 192.168.1.157 192.168.1.158   # puerto de tiempo real (30003), dos robots
```

Cada IP se atiende en su propio hilo con su propia instancia de `UR3eRG2`.
Los scripts se reconectan solos si se pierde la conexion y se detienen con `Ctrl+C`.
