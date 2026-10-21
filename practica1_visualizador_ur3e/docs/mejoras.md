# Posibles mejoras

## Aprender y copiar (`aprender_copiar.py`)

- **Desbloqueo de la parada protectiva:** ahora el operario la desbloquea en el
  teach pendant y elige `r` para reintentar. Si el robot sigue en parada
  protectiva, el reintento falla de nuevo mostrando el motivo. Opciones a valorar:
  - Esperar a que el estado indique que la parada se ha liberado antes de ofrecer el reintento.
  - Desbloquearla desde el script con el Dashboard Server (puerto 29999). Requiere
    una conexion nueva y una revision de seguridad.
- **Ctrl+C durante un movimiento:** el script se detiene, pero el robot termina el
  `movej` que ya recibio. Se podria enviar `stopj(...)` al salir.
- **Pinza RG2:** incluir acciones de abrir/cerrar en los puntos de la secuencia.
- **Velocidad y aceleracion:** son globales (`ACCELERATION`/`VELOCITY` en
  `escribir.py`). Fijar valores seguros para el robot real y permitir cambiarlos desde la interfaz web.
- **Cargar y ampliar:** cargar una secuencia guardada y anadirle puntos (ahora solo se puede repetir).

## Robot real

- Confirmar que el robot real envia los mensajes `PROGRAM_XXX_STARTED` /
  `PROGRAM_XXX_STOPPED` igual que el simulador.

## Interfaz web (`interfaz_web.py`)

- **Cerrar la ventana del visualizador con la X:** comprobar que la interfaz lo detecta
  y permite reabrirla (con `pybullet.disconnect()` ya se ha comprobado que si).
- **Ejecutable:** hecho con `panel_ur3e.spec`. Solo incluye la interfaz web; los scripts
  de terminal se podrian anadir como comandos del mismo ejecutable.
