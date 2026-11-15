# E2 · Diseño de la pasarela

Práctica: comunicación segura con el robot UR3e mediante una pasarela TLS.
Estudiante n.º 6 · Código: `pasarela.py` (clases `Pasarela` y `Sesion`).

## 1. Qué hace la pasarela

La pasarela es un único programa con dos papeles de red:

- **servidor TLS** hacia los clientes, en su IP del laboratorio y el puerto 3000;
- **cliente TCP** hacia el robot (o hacia el servidor de eco en las pruebas).

Entre los dos hay un reenvío de bytes en los dos sentidos. La pasarela no interpreta los
mensajes del robot ni sabe dónde empieza o acaba cada uno: copia lo que llega.

## 2. Diagrama de conexiones

```
   Cliente (máquina virtual)             Pasarela (PC del laboratorio)             Robot UR3e
 ┌──────────────────────────┐        ┌───────────────────────────────┐        ┌──────────────┐
 │ cliente_seguro.py        │        │ pasarela.py                   │        │              │
 │                          │   C1   │                               │   C2   │              │
 │ ca.crt                   │◄══════►│ 10.172.18.6:3000              │◄──────►│ puerto 30001 │
 │ cliente-a.crt            │  TLS   │ ca.crt                        │  TCP   │ sin          │
 │ cliente-a.key            │  1.3   │ pasarela.crt, pasarela.key    │  en    │ certificado  │
 │                          │        │ lista: ["cliente-a"]          │ claro  │              │
 └──────────────────────────┘        └───────────────────────────────┘        └──────────────┘
```

| Conexión | Quién la abre | Cuándo | Protocolo | Qué viaja |
|---|---|---|---|---|
| C1 | El cliente | Al empezar cada operación | TCP + TLS 1.3 con autenticación mutua | Los mensajes del robot, cifrados |
| C2 | La pasarela | Solo después de autenticar y autorizar al cliente | TCP en claro | Los mismos mensajes, legibles |

Hay una conexión C2 por cada cliente autorizado. La pasarela nunca abre C2 para un
cliente que no ha superado el handshake y la autorización.

## 3. Vida de una conexión

```
 Cliente                          Pasarela                               Robot
    │                                 │                                    │
    │── 1. conexión TCP (3000) ──────►│  accept()                          │
    │                                 │  se crea una Sesion y su hilo      │
    │◄─ 2. handshake TLS 1.3 ────────►│  wrap_socket(), límite de 10 s     │
    │      certificados de los dos    │  valida al cliente con ca.crt      │
    │                                 │                                    │
    │                                 │  3. ¿CN en clientes_autorizados?   │
    │                                 │     no → registrar y cerrar        │
    │                                 │     sí ↓                           │
    │                                 │── 4. conexión TCP ────────────────►│
    │                                 │                                    │
    │══ 5. datos cifrados ═══════════►│── mismos bytes ───────────────────►│
    │◄═ 6. datos cifrados ════════════│◄─ mismos bytes ────────────────────│
    │                                 │                                    │
    │◄─ 7. close_notify y cierre ────►│── cierre ─────────────────────────►│
```

En el código, toda esta secuencia es el método `Sesion.run()`:

```python
if self.handshake() and self.authorize() and self.connect_robot():
    self.forward()
self.close()
```

Cada paso solo se ejecuta si el anterior ha ido bien, y `close()` se ejecuta siempre.

## 4. Diagrama de hilos

```
 Hilo principal                 Hilo de sesión (1 por cliente)         Hilo de reenvío (1 por cliente autorizado)
 ──────────────                 ──────────────────────────────         ──────────────────────────────────────────
 Pasarela.serve()
   accept()  ───── cliente ───► Sesion.run()
   accept()                       handshake()
   accept()                       authorize()
     ...                          connect_robot()
                                  forward() ──────── crea ───────────► copy(robot → cliente)
                                    copy(cliente → robot)                recv del robot, sendall al cliente
                                      recv del cliente,                  ...
                                      sendall al robot
                                      ...
                                    espera al hilo de reenvío ◄──────── termina
                                  close()
                                  se quita de la lista de sesiones
```

| Hilo | Cuántos | Qué hace | Cuándo termina |
|---|---|---|---|
| Principal | 1 | Solo acepta conexiones nuevas (`accept`) y crea un hilo de sesión para cada una | Con `Ctrl+C` |
| De sesión | 1 por cliente conectado | Handshake, autorización, conexión con el robot y copia cliente → robot | Cuando la sesión termina por cualquier motivo |
| De reenvío | 1 por cliente autorizado | Copia robot → cliente | Cuando la sesión termina |

Con 4 clientes autorizados hay 9 hilos: 1 principal, 4 de sesión y 4 de reenvío.

Elementos compartidos entre hilos:

| Elemento | Dónde | Para qué |
|---|---|---|
| `Sesion.finished` (`threading.Event`) | Uno por sesión | Avisa a los dos hilos de la sesión de que hay que terminar |
| `Sesion.lock` (`threading.Lock`) | Uno por sesión | Los dos hilos pueden detectar el final a la vez; solo se registra el primer motivo |
| `Pasarela.lock` (`threading.Lock`) | Uno | Protege la lista de sesiones abiertas, que modifican varios hilos |

## 5. Justificación de las decisiones

| Decisión | Motivo | Requisito |
|---|---|---|
| El hilo principal solo acepta conexiones | Si hiciera el handshake, un cliente que se conecta y no habla bloquearía a todos los demás durante el tiempo límite | P8, P10 |
| Un hilo por cliente | Un cliente lento o bloqueado solo retrasa a su propio hilo. No hay un número máximo de clientes | P10 |
| Dos hilos por cliente autorizado, uno por sentido | La pasarela tiene que esperar datos por dos sitios a la vez (cliente y robot) y `recv` es bloqueante: con un solo hilo se quedaría esperando en un lado mientras el otro tiene datos pendientes | P12 |
| El handshake se hace en el hilo de la sesión, con `settimeout` | Limita el tiempo que un cliente puede ocupar recursos sin completar el handshake | P8 |
| La conexión con el robot se abre después de autorizar | Un cliente no autorizado nunca llega a tocar el robot, ni siquiera para abrir una conexión | P7 |
| Las lecturas tienen un tiempo límite de 1 s | Cuando vence sin datos no es un error: el hilo comprueba si la sesión ha terminado y vuelve a esperar. Así ningún hilo se queda bloqueado para siempre y la pasarela puede pararse de forma ordenada | P14, P16 |
| `copy` reenvía cada bloque tal como llega, con `sendall` | TCP y TLS son flujos de bytes: una lectura puede traer medio mensaje o varios. La pasarela no necesita saberlo, porque de delimitar los mensajes ya se encargan el cliente y el robot | P12 |
| El destino (IP y puerto) está en la configuración | Pasar del servidor de eco al robot es cambiar dos datos de `config.json`, sin tocar el código | P11 |
| La lista de autorizados está en la configuración | Se puede autorizar o retirar un cliente sin tocar el código | P7 |
| El cierre TLS se hace con `unwrap()` | Envía la alerta `close_notify`, para que el cliente distinga un final normal de un corte | P13, P16 |
| Cada línea del registro lleva IP, CN, versión TLS y suite | Permite saber quién se conectó, con qué seguridad y por qué terminó cada conexión | P9 |
| La contraseña de la clave se pide con `getpass` al arrancar | No queda en el código, en la configuración ni en pantalla | P2 |
| El contexto TLS se crea con `SSLContext` y `load_verify_locations`, no con `create_default_context` | Así la pasarela confía solo en la CA del laboratorio y no en las CA del sistema | P5 |

## 6. Qué se cierra en cada caso

| Caso | Cómo se detecta | Qué se cierra y en qué orden | Qué queda en el registro |
|---|---|---|---|
| **El cliente se va** | El hilo de sesión lee 0 bytes del socket TLS (el cliente envió `close_notify`) o `recv` lanza una excepción (corte sin aviso) | 1. Se marca la sesión como terminada. 2. El hilo de reenvío lo ve y termina. 3. Se cierra el socket del robot. 4. Se cierra el socket TLS del cliente | `cierre: el cliente ha cerrado la conexión` o `cierre: desconexión del cliente: …` |
| **El robot se cae** | El hilo de reenvío lee 0 bytes del socket del robot o `recv` lanza una excepción | 1. Se marca la sesión como terminada. 2. El hilo de sesión lo ve y termina su copia. 3. Se cierra el socket del robot. 4. El cliente recibe un cierre TLS ordenado (`close_notify`) y se cierra su socket | `cierre: el destino ha cerrado la conexión` o `cierre: desconexión del destino: …` |
| **Cliente no autorizado** (cliente-b) | El handshake es correcto, pero el CN no está en `clientes_autorizados` | No se abre la conexión con el robot ni se crea el hilo de reenvío. El cliente recibe un cierre TLS ordenado y se cierra su socket | `handshake correcto` y después `rechazado: el CN no está en la lista de autorizados` |
| **Handshake fallido** (sin certificado, CA desconocida, certificado con `serverAuth`, TLS 1.2, cliente que no habla) | `wrap_socket` lanza una excepción | Solo existe el socket del cliente, y se cierra. No hay TLS que cerrar ni conexión con el robot | `handshake rechazado: <motivo>` |
| **Robot no disponible al conectar** | `create_connection` lanza una excepción | No se crea el hilo de reenvío. El cliente recibe un cierre TLS ordenado y se cierra su socket | `no se puede conectar con el destino IP:puerto: <motivo>` |
| **Parada de la pasarela** (`Ctrl+C`) | El hilo principal recibe `KeyboardInterrupt` | 1. Se deja de aceptar y se cierra el socket de escucha. 2. Se marcan todas las sesiones como terminadas. 3. Cada sesión cierra su socket del robot y hace el cierre TLS ordenado con su cliente. 4. El hilo principal espera a todos los hilos | `Parada solicitada…`, `cierre: la pasarela se detiene` por cada sesión y `Pasarela detenida` |

En todos los casos el cierre lo hace el mismo método, `Sesion.close()`, que siempre se
ejecuta al final de `Sesion.run()`: cierra el socket del robot si existe y después el del
cliente, con `unwrap()` si el handshake se completó.

## 7. Formato del registro

Líneas de ejemplo que muestran el formato del fichero de registro. Las direcciones IP y
las horas son ilustrativas.

```
2026-11-13 14:22:04,129 INFO ip=10.172.18.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | handshake correcto
2026-11-13 14:22:04,130 INFO ip=10.172.18.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | conectado con el destino 10.172.18.80:30001
2026-11-13 14:22:04,331 INFO ip=10.172.18.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | cierre: el cliente ha cerrado la conexión
2026-11-13 14:22:04,532 WARNING ip=10.172.18.21 cn=cliente-b tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | rechazado: el CN no está en la lista de autorizados
2026-11-13 14:22:05,292 WARNING ip=10.172.18.21 cn=- tls=- suite=- | handshake rechazado: [SSL: PEER_DID_NOT_RETURN_A_CERTIFICATE] peer did not return a certificate
```
