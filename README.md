# Máster Universitario en Automatización, Electrónica y Control Industrial
## Redes de Comunicación Industrial

Repositorio de los trabajos de la asignatura Redes de Comunicación Industrial.

## Prácticas

| Práctica | Descripción |
|---|---|
| [Práctica 1. Visualizador UR3e](practica1_visualizador_ur3e/) | Monitorización de robots UR3e por las interfaces primaria y de tiempo real, visualizador 3D, movimiento verificado, aprender y copiar, y panel web local (también como ejecutable). Instrucciones completas en su [README](practica1_visualizador_ur3e/README.md). |
| [Práctica 2. Modbus TCP](practica2_modbus_tcp/) | Uso de MODBUS sobre TCP. Agregar header y datos relevantes para modbus sobre una conexion tcp. Permite realizar conexiones a un host con un puerto especifico en linea de comando. |
| [Práctica 3. Pasarela TLS](practica3_tls/) | Comunicación segura con el robot UR3e: pasarela TLS 1.3 con autenticación mutua que reenvía al robot sin interpretar los mensajes, cliente seguro que reutiliza el código de la práctica 1 y menú de texto. Explicación completa en su [README](practica3_tls/README.md). |

## Estructura del repositorio

Cada práctica vive en su propia carpeta `practicaN_<nombre>/`, con su código,
documentación y dependencias independientes.
