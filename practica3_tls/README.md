# Práctica 3. Pasarela TLS para el robot UR3e

El robot UR3e acepta conexiones TCP sin cifrado ni autenticación. Esta práctica no cambia
esa comunicación: la **protege** con dos programas en Python que solo usan la biblioteca
estándar.

- **Pasarela** (`pasarela.py`): servidor TLS 1.3 con autenticación mutua. Recibe del
  cliente los mismos bytes que iría al robot, los reenvía al robot por TCP sin
  interpretarlos y devuelve las respuestas.
- **Cliente seguro** (`cliente_seguro.py`): el cliente de la práctica 1 con el transporte
  cambiado de TCP a TLS y apuntando a la pasarela.

```
Cliente  ──── C1: TLS 1.3, cifrado ────  Pasarela  ──── C2: TCP en claro ────  Robot UR3e
cliente-a.crt                            pasarela.crt, puerto 3000             sin certificado
```

## Índice

1. [Ficheros](#ficheros)
2. [Proceso completo](#proceso-completo)
3. [Fase 1: crear la PKI](#fase-1-crear-la-pki)
4. [Configuración](#configuración)
5. [Cómo ejecutar](#cómo-ejecutar)
6. [Explicación del código](#explicación-del-código)
7. [Diseño de la pasarela: hilos y cierres](#diseño-de-la-pasarela-hilos-y-cierres)
8. [Dónde se cumple cada requisito](#dónde-se-cumple-cada-requisito)
9. [Pruebas de aceptación](#pruebas-de-aceptación)

## Ficheros

```
practica3_tls/
├── menu.py              # ejecutable: menú de texto que lanza todo lo demás
├── pasarela.py          # clases Pasarela y Sesion (servidor TLS + reenvío)
├── cliente_seguro.py    # clase ClienteSeguro (cliente TLS o directo)
├── servidor_eco.py      # clase ServidorEco (sustituye al robot en la Fase 3)
├── configuracion.py     # lectura del fichero JSON de configuración
├── config_ejemplo.json  # configuración de ejemplo
├── crear_pki.sh         # Fase 1: crea la CA y los certificados con OpenSSL
└── README.md            # este documento
```

No se versionan (están en `.gitignore`): `config.json`, `pasarela.log`, las claves
privadas `*.key` y los `*.p12`.

El cliente **importa** el código del robot de la práctica 1
(`practica1_visualizador_ur3e/src/visualizador_ur3e`), así que las dos carpetas tienen
que estar una al lado de la otra, como en el repositorio.

## Proceso completo

| Paso | Qué se hace | Con qué |
|---|---|---|
| 1 | Crear la CA y los certificados de pasarela, cliente-a y cliente-b | `crear_pki.sh` (Fase 1) |
| 2 | Copiar `config_ejemplo.json` a `config.json` y poner las IP y rutas reales | Un editor |
| 3 | Probar la pasarela contra el servidor de eco (Fase 3) | `menu.py` opciones 2 y 1, y `openssl s_client` |
| 4 | Cambiar `ip_destino` y `puerto_destino` al robot (Fase 5) | Solo `config.json`, el código no se toca |
| 5 | Usar el cliente a través de la pasarela y directo, y comparar | `menu.py` opciones 3 y 4 |

## Fase 1: crear la PKI

El script `crear_pki.sh` ejecuta todos los pasos de una vez en `~/pki`. Recibe el número
de estudiante y la IP de la pasarela, y solo pregunta las cuatro contraseñas (CA,
pasarela, cliente-a y cliente-b), sin mostrarlas:

```bash
./crear_pki.sh 7 10.172.21.30
```

Si ya existe una CA en `~/pki` no la sobrescribe. Al terminar muestra la verificación de
la cadena y los datos de cada certificado para la tabla del informe.

Las órdenes que ejecuta son las del enunciado y se explican a continuación, por si se
prefiere hacerlo a mano con OpenSSL 3 desde `~/pki`. La única diferencia es que el script
pasa las contraseñas con `-passout env:` y `-passin env:` en lugar de dejar que OpenSSL
las pregunte en cada orden. Sustituye `N` por tu número de estudiante y `10.172.21.30`
por la IP de tu pasarela.

```bash
# Paso 1: carpetas. ca-privado solo la puede abrir su propietario
mkdir -p ~/pki/ca-privado ~/pki/publico ~/pki/pasarela ~/pki/cliente-a ~/pki/cliente-b
cd ~/pki
chmod 700 ca-privado

# Paso 2: la CA (clave + certificado autofirmado, 2 años). Pide una contraseña para ca.key
openssl req -x509 -newkey rsa:2048 -sha256 -days 730 \
  -keyout ca-privado/ca.key -out publico/ca.crt \
  -subj "/CN=CA Robot Lab - estudiante N" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
```

Paso 3: dos ficheros de extensiones en `~/pki`. Las extensiones las decide la CA.

`pasarela.ext`:

```
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = IP:10.172.21.30
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
```

`cliente.ext` (el mismo para los dos clientes):

```
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
```

```bash
# Paso 4: clave y petición de firma (CSR) de cada equipo. Cada orden pide la contraseña
# de esa clave (la que luego pedirán la pasarela o el cliente). No usar -noenc.
openssl req -new -newkey rsa:2048 -keyout pasarela/pasarela.key -out pasarela/pasarela.csr -subj "/CN=pasarela-ur3e"
openssl req -new -newkey rsa:2048 -keyout cliente-a/cliente-a.key -out cliente-a/cliente-a.csr -subj "/CN=cliente-a"
openssl req -new -newkey rsa:2048 -keyout cliente-b/cliente-b.key -out cliente-b/cliente-b.csr -subj "/CN=cliente-b"

# Paso 5: la CA firma cada petición (1 año). Pide la contraseña de la CA
openssl x509 -req -in pasarela/pasarela.csr \
  -CA publico/ca.crt -CAkey ca-privado/ca.key -CAserial ca-privado/ca.srl -CAcreateserial \
  -days 365 -sha256 -extfile pasarela.ext -out pasarela/pasarela.crt
openssl x509 -req -in cliente-a/cliente-a.csr \
  -CA publico/ca.crt -CAkey ca-privado/ca.key -CAserial ca-privado/ca.srl \
  -days 365 -sha256 -extfile cliente.ext -out cliente-a/cliente-a.crt
openssl x509 -req -in cliente-b/cliente-b.csr \
  -CA publico/ca.crt -CAkey ca-privado/ca.key -CAserial ca-privado/ca.srl \
  -days 365 -sha256 -extfile cliente.ext -out cliente-b/cliente-b.crt

# Paso 6: proteger las claves. La segunda orden debe pedir contraseña
chmod 600 pasarela/pasarela.key cliente-a/cliente-a.key cliente-b/cliente-b.key
openssl pkey -in pasarela/pasarela.key -noout

# Paso 7: verificar la cadena (debe responder OK tres veces)
openssl verify -CAfile publico/ca.crt pasarela/pasarela.crt cliente-a/cliente-a.crt cliente-b/cliente-b.crt

# Paso 9: datos para la tabla de certificados del informe
openssl x509 -in pasarela/pasarela.crt -noout -subject -issuer -serial -dates -fingerprint -sha256
```

Qué recibe cada equipo:

| Fichero | Pasarela | Cliente A | ¿Secreto? |
|---|---|---|---|
| `publico/ca.crt` | Sí | Sí | No |
| `pasarela/pasarela.crt` y `pasarela.key` | Sí | No | La clave, sí |
| `cliente-a/cliente-a.crt` y `cliente-a.key` | No | Sí | La clave, sí |
| `ca-privado/ca.key` | Nunca | Nunca | Sí, el que más |

El paso 8 (prueba de humo con `openssl s_server` y `s_client`) y sus variantes están en
el enunciado y no usan el código de esta carpeta.

## Configuración

```bash
cd practica3_tls
cp config_ejemplo.json config.json
```

Un solo fichero con dos secciones; cada programa lee la suya. Las rutas admiten `~`.

| Sección `pasarela` | Significado |
|---|---|
| `ip_escucha`, `puerto_escucha` | IP de la pasarela en la red del laboratorio y puerto (3000). Solo escucha en esa IP |
| `ca` | Certificado de la CA del laboratorio (ancla de confianza) |
| `certificado`, `clave` | Certificado y clave privada cifrada de la pasarela, en PEM |
| `clientes_autorizados` | Lista de CN que pueden llegar al robot. `cliente-b` no debe estar |
| `ip_destino`, `puerto_destino` | A dónde reenvía: servidor de eco (Fase 3) o robot (Fase 5) |
| `timeout_handshake` | Segundos máximos para completar el handshake |
| `fichero_registro` | Fichero de registro de la pasarela |

| Sección `cliente` | Significado |
|---|---|
| `ip_pasarela`, `puerto_pasarela` | Dónde está la pasarela. Debe ser la IP que figura en la SAN de su certificado |
| `ca` | Certificado de la CA del laboratorio |
| `certificado`, `clave` | Certificado y clave privada cifrada del cliente, en PEM |
| `ip_robot`, `puerto_robot` | Robot real, solo para la conexión directa sin TLS |

**La contraseña de la clave no está en ningún fichero.** La pasarela y el cliente la piden
al arrancar con `getpass`, que no la muestra en pantalla. Así, quien copie el código o la
configuración no obtiene nada que le permita suplantar al equipo.

## Cómo ejecutar

Todo se ejecuta desde la carpeta `practica3_tls/`, con Python 3.10 o posterior. No hay
que instalar nada.

### Con el menú

```bash
./menu.py                       # o: python3 menu.py
./menu.py --config otro.json    # con otro fichero de configuración
```

```
===== Práctica 3 · Pasarela TLS para el UR3e =====
 1. Arrancar la pasarela
 2. Arrancar el servidor de eco (pruebas de la Fase 3)
 3. Cliente a través de la pasarela (TLS)
 4. Cliente directo al robot (sin TLS)
 0. Salir
```

- **1** pide la contraseña de `pasarela.key` y deja la pasarela en marcha. `Ctrl+C` la
  detiene de forma ordenada y vuelve al menú.
- **2** arranca el servidor de eco en `ip_destino:puerto_destino`. `Ctrl+C` lo detiene.
- **3** pide la contraseña de la clave del cliente una vez y abre el submenú del cliente.
- **4** abre el mismo submenú, pero conectando directamente al robot, sin contraseña.

Submenú del cliente: **1** lee la posición articular, **2** mueve el robot a la posición
`TARGET_JOINTS` de la práctica 1 y verifica que ha llegado (pide confirmación con `s`,
porque **el robot se mueve**). Cada operación abre una conexión, muestra los datos TLS,
hace la operación, cierra y muestra el tiempo de respuesta.

La pasarela, el servidor de eco y el cliente son programas distintos: cada uno se lanza
en su propio terminal (o en su propia máquina).

### Sin el menú

```bash
python3 pasarela.py                       # pasarela
python3 pasarela.py --traza               # pasarela, registrando cada bloque reenviado
python3 servidor_eco.py                   # servidor de eco
python3 cliente_seguro.py leer            # leer la posición a través de la pasarela
python3 cliente_seguro.py mover           # mover y verificar a través de la pasarela
python3 cliente_seguro.py --directo leer  # lo mismo, directo al robot y sin TLS
```

Todos aceptan `--config FICHERO` y `--help`.

Con `--traza` (en `pasarela.py` o en `menu.py`) la pasarela registra además una línea por
cada bloque de bytes que reenvía, con el sentido y el tamaño. Sirve para ver desde la
pasarela que los datos pasan; con el robot real son unas diez líneas por segundo y
cliente, por eso está desactivado por defecto.

```
... DEBUG ip=10.172.21.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | cliente -> destino: 9 bytes reenviados
... DEBUG ip=10.172.21.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | destino -> cliente: 9 bytes reenviados
```

### Probar la Fase 3 (pasarela + servidor de eco)

Con `ip_destino` y `puerto_destino` apuntando a tu propio PC (por ejemplo `127.0.0.1` y
`4000`): arranca el servidor de eco en un terminal y la pasarela en otro. Como el
servidor de eco no habla el protocolo del robot, se prueba con el cliente de OpenSSL: lo
que escribas debe volver.

```bash
openssl s_client -connect 10.172.21.30:3000 -tls1_3 \
  -CAfile ~/pki/publico/ca.crt -cert ~/pki/cliente-a/cliente-a.crt -key ~/pki/cliente-a/cliente-a.key \
  -verify_ip 10.172.21.30 -verify_return_error
```

## Explicación del código

### `configuracion.py`

Una sola función, `load_settings(ruta, seccion)`: abre el JSON y devuelve la sección
pedida como diccionario.

### `servidor_eco.py`

Clase `ServidorEco`. `serve()` acepta conexiones y lanza un hilo por cada una; `echo()`
devuelve cada bloque de bytes recibido hasta que el otro extremo cierra. Sirve para
probar toda la parte segura sin depender del robot.

### `pasarela.py`

**`create_context(settings, password)`** crea el contexto TLS del servidor con las cinco
líneas del enunciado:

| Línea | Efecto |
|---|---|
| `SSLContext(PROTOCOL_TLS_SERVER)` | Contexto de servidor vacío: no confía en ninguna CA |
| `minimum_version = TLSv1_3` | Rechaza TLS 1.2 y anteriores |
| `load_cert_chain(crt, key, password)` | Identidad de la pasarela; descifra la clave con la contraseña |
| `load_verify_locations(cafile)` | Confía solo en la CA del laboratorio, no en las del sistema |
| `verify_mode = CERT_REQUIRED` | Exige certificado a todos los clientes |

**Clase `Sesion`**: una conexión de un cliente, de principio a fin. Su método `run()`
resume toda la lógica en una línea: cada paso solo se ejecuta si el anterior fue bien, y
al final siempre se cierra.

```python
if self.handshake() and self.authorize() and self.connect_robot():
    self.forward()
self.close()
```

| Método | Qué hace |
|---|---|
| `handshake()` | Pone el tiempo límite, envuelve el socket con `wrap_socket` (ahí ocurre el handshake) y guarda la versión TLS, la suite y el CN del cliente. Si falla, lo registra |
| `authorize()` | Comprueba que el CN está en `clientes_autorizados`. Si no, registra el motivo |
| `connect_robot()` | Abre la conexión TCP con el destino. Si no puede, lo registra |
| `forward()` | Lanza un hilo que copia destino → cliente y copia cliente → destino en el hilo actual |
| `copy(origen, destino, nombre)` | Bucle `recv` → `sendall`. Termina con 0 bytes, con una excepción o cuando la sesión está marcada como terminada |
| `finish(motivo)` | Marca la sesión como terminada y registra el motivo (solo el primero) |
| `close()` | Cierra el socket del destino y el del cliente; en el lado TLS, `unwrap()` envía `close_notify` |
| `log(nivel, mensaje)` | Escribe una línea de registro con IP, CN, versión TLS y suite |

`copy` no sabe qué es un mensaje del robot: copia los bytes que llegan, sean medio
mensaje o tres. De delimitar los mensajes ya se encargan el cliente y el robot.

Las lecturas tienen un tiempo límite de 1 s (`POLL_TIMEOUT`). Cuando vence sin datos no
es un error: el bucle comprueba si la sesión ha terminado y vuelve a esperar. Así un
hilo nunca se queda bloqueado para siempre y la pasarela puede cerrarse ordenadamente.

**Clase `Pasarela`**: `serve()` escucha en la IP configurada, acepta clientes y crea una
`Sesion` con su hilo para cada uno. Con `Ctrl+C` deja de aceptar, marca todas las
sesiones como terminadas (`close_sessions()`) y espera a sus hilos. La lista de sesiones
abiertas se protege con un `Lock` porque la modifican varios hilos.

Ejemplo de líneas del registro (`pasarela.log`):

```
2026-11-13 14:22:04,129 INFO ip=10.172.21.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | handshake correcto
2026-11-13 14:22:04,331 INFO ip=10.172.21.21 cn=cliente-a tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | cierre: el cliente ha cerrado la conexión
2026-11-13 14:22:04,532 WARNING ip=10.172.21.21 cn=cliente-b tls=TLSv1.3 suite=TLS_AES_256_GCM_SHA384 | rechazado: el CN no está en la lista de autorizados
2026-11-13 14:22:05,292 WARNING ip=10.172.21.21 cn=- tls=- suite=- | handshake rechazado: [SSL: PEER_DID_NOT_RETURN_A_CERTIFICATE] peer did not return a certificate
```

### `cliente_seguro.py`

El código del robot **no se reescribe**: se importa de la práctica 1.

| Importado de la práctica 1 | Para qué |
|---|---|
| `extract_messages`, `parse_joint_positions`, `ROBOT_STATE` (`ur_protocol.py`) | Separar los mensajes del robot y sacar la posición articular |
| `build_program`, `monitor_program` (`escribir.py`) | Construir el programa URScript, seguir su ejecución y verificar la posición |
| `TARGET_JOINTS`, `TIMEOUT`, `STARTUP_TIMEOUT`, `RECV_SIZE` (`escribir.py`) | Las mismas constantes |

Esas funciones reciben un socket y solo usan `recv` y `sendall`, que funcionan igual en
un socket TLS. Por eso basta con cambiar el socket que se les pasa.

**`create_context(settings, password)`**: contexto de cliente. `PROTOCOL_TLS_CLIENT` ya
verifica el certificado de la pasarela, su uso `serverAuth` y su SAN. Solo TLS 1.3, solo
la CA del laboratorio, y el certificado y la clave del cliente.

**Clase `ClienteSeguro`**:

| Método | Qué hace |
|---|---|
| `__init__(settings, password, direct)` | Elige el destino: la pasarela (y crea el contexto TLS) o el robot directo |
| `connect()` | Abre TCP y, si no es directo, hace el handshake con `wrap_socket(tcp, server_hostname=ip)`. `server_hostname` es lo que hace que se compruebe la SAN |
| `show_connection()` | Muestra versión TLS, suite, y CN y caducidad del certificado de la pasarela |
| `read_joints()` | Lee hasta el primer estado del robot y devuelve las posiciones articulares |
| `move_and_verify()` | Envía el programa y sigue su ejecución, igual que `write_and_verify` de la práctica 1 |
| `run(operacion)` | Conecta, ejecuta la operación, cierra y devuelve el resultado y el tiempo medido con `perf_counter` |
| `close()` | Con TLS, `unwrap()` envía `close_notify` antes de cerrar |

Los fallos se convierten en `ErrorCliente` con un mensaje distinto para cada causa:

| Situación | Dónde se detecta | Mensaje |
|---|---|---|
| Pasarela inalcanzable | `connect()`, `OSError` o tiempo agotado | `No se puede alcanzar la pasarela en IP:puerto: …` |
| Conexión rechazada | `connect()`, `ConnectionRefusedError` | `Conexión rechazada: la pasarela no escucha en IP:puerto` |
| Certificado de la pasarela no válido | `connect()`, `SSLCertVerificationError` | `Certificado de la pasarela no válido: <motivo>` |
| Certificado del cliente rechazado | `run()`, `SSLError` con una alerta, **en la primera lectura** | `La pasarela ha rechazado el certificado del cliente: <alerta>` |
| Cerrada tras el handshake | `run()`, lectura de 0 bytes | `Conexión cerrada por la pasarela después del handshake: cliente no autorizado o robot no disponible` |

En TLS 1.3 el cliente da por terminado el handshake antes de que la pasarela valide su
certificado. Por eso el rechazo del certificado del cliente no aparece en `connect()`
sino en la primera lectura, y se captura en `run()`.

Las excepciones se capturan de la más concreta a la más general
(`SSLCertVerificationError` → `SSLError` → `OSError`) porque cada una es un caso
particular de la siguiente.

### `menu.py`

Clase `Menu` con un bucle que muestra las opciones y llama a las mismas funciones que
usan los programas por separado: `run_gateway`, `run_echo_server`, `create_client`,
`show_read` y `show_move`. No contiene lógica de red.

## Diseño de la pasarela: hilos y cierres

```
Hilo principal ── accept() ──┬── Hilo de sesión (cliente 1): handshake, autorización,
                             │      conexión con el destino y copia cliente → destino
                             │        └── Hilo de reenvío: copia destino → cliente
                             ├── Hilo de sesión (cliente 2) ...
                             └── ...
```

| Hilo | Cuántos | Qué hace |
|---|---|---|
| Principal | 1 | Solo acepta conexiones nuevas; nunca espera a un cliente |
| De sesión | 1 por cliente | Handshake, autorización, conexión con el destino y copia cliente → destino |
| De reenvío | 1 por cliente autorizado | Copia destino → cliente |

Como el handshake se hace en el hilo de la sesión y no en el principal, un cliente lento
o que no habla solo retrasa a su propio hilo. No hay límite de clientes simultáneos.

Qué se cierra en cada caso:

| Caso | Qué ocurre |
|---|---|
| El cliente se va | `recv` del lado TLS devuelve 0 bytes (o lanza una excepción) → `finish` → el otro hilo termina → se cierran el socket del destino y el del cliente → se registra |
| El robot se cae | `recv` del lado del destino devuelve 0 bytes o lanza una excepción → `finish` → se cierra el destino y el cliente recibe un cierre TLS ordenado (`close_notify`) → se registra |
| Cliente no autorizado | Handshake correcto, `authorize()` devuelve falso → **no se abre** la conexión con el robot → cierre TLS ordenado → se registra el motivo |
| Handshake fallido | `wrap_socket` lanza una excepción (sin certificado, CA desconocida, uso no permitido, TLS antiguo, tiempo agotado) → se registra y se cierra |
| Destino no disponible | `create_connection` falla → se registra → cierre TLS ordenado del cliente |
| `Ctrl+C` en la pasarela | Se deja de aceptar, se marcan todas las sesiones como terminadas, cada una cierra sus dos sockets (TLS con `close_notify`) y se espera a todos los hilos |

## Dónde se cumple cada requisito

| N.º | Requisito | Dónde |
|---|---|---|
| P1 | Escuchar solo en la IP de la pasarela | `Pasarela.serve`: `create_server((ip_escucha, puerto_escucha))` |
| P2 | Clave cifrada en PEM, contraseña fuera del código | `run_gateway` (`getpass`) y `create_context` (`load_cert_chain`) |
| P3 | Solo TLS 1.3 | `create_context`: `minimum_version` |
| P4 | Exigir certificado | `create_context`: `CERT_REQUIRED` |
| P5 | Validar solo contra la CA del laboratorio | `create_context`: `load_verify_locations`, sin `create_default_context` |
| P6 | Rechazar clientes sin `clientAuth` | Lo hace OpenSSL en el handshake; queda en el registro como `unsuitable certificate purpose` |
| P7 | Lista de CN autorizados | `Sesion.authorize` |
| P8 | Tiempo límite del handshake | `Sesion.handshake`: `settimeout(timeout_handshake)` |
| P9 | Registro en fichero | `setup_logging` y `Sesion.log` |
| P10 | Al menos 4 clientes a la vez | Un hilo por cliente: `Pasarela.start_session` |
| P11 | Destino configurable | `Sesion.connect_robot`: `ip_destino`, `puerto_destino` |
| P12 | Reenviar sin interpretar | `Sesion.copy` |
| P13 | Destino inalcanzable: registrar y cierre TLS ordenado | `Sesion.connect_robot` y `Sesion.close` |
| P14 | Si un extremo cierra, cerrar el otro | `Sesion.finish` y `Sesion.close` |
| P15 | Detectar desconexiones | `Sesion.copy`: 0 bytes o excepción |
| P16 | Parada ordenada | `Pasarela.serve` (`Ctrl+C`) y `Pasarela.close_sessions` |
| C1 | Configuración y contraseña sin mostrar | `config.json` y `create_client` (`getpass`) |
| C2 | Presentar el certificado del cliente | `create_context` del cliente: `load_cert_chain` |
| C3 | Validar el certificado de la pasarela | `PROTOCOL_TLS_CLIENT`, `load_verify_locations` y `server_hostname` |
| C4 | Solo TLS 1.3 | `create_context` del cliente: `minimum_version` |
| C5 | Mostrar versión, suite, sujeto y caducidad | `ClienteSeguro.show_connection` |
| C6 | Reutilizar la comunicación con el robot | Funciones importadas de la práctica 1 |
| C7 | Conexión directa sin TLS | `--directo` y opción 4 del menú |
| C8 | Mensajes distintos por situación | `ClienteSeguro.connect` y `ClienteSeguro.run` |
| C9 | Rechazo del certificado en la primera lectura | `ClienteSeguro.run`: `except ssl.SSLError` |
| C10 | Medir el tiempo de respuesta | `ClienteSeguro.run`: `perf_counter` |

## Pruebas de aceptación

| Prueba | Cómo hacerla | Resultado esperado |
|---|---|---|
| Cliente A, mismas operaciones | Menú 3 y menú 4, operaciones 1 y 2 | Los mismos resultados por los dos caminos |
| Cliente B | `config.json` del cliente con `cliente-b.crt` y `cliente-b.key` | El cliente conecta y luego informa del cierre; en el registro, `rechazado: el CN no está en la lista de autorizados` |
| Cliente sin certificado | `openssl s_client` sin `-cert` ni `-key` | En el registro, `peer did not return a certificate` |
| Certificado emitido con `serverAuth` | Firmar una petición de cliente con `pasarela.ext` y usarla en el cliente | El cliente muestra `La pasarela ha rechazado el certificado del cliente`; en el registro, `unsuitable certificate purpose` |
| Se desconecta el robot | Parar el destino con un cliente conectado | En el registro, `cierre: el destino ha cerrado la conexión`; el cliente informa del cierre |
| Cuatro clientes, uno bloqueado | Un `openssl s_client` que no hace nada y tres clientes normales | Los otros tres siguen funcionando |
| CA de otro estudiante | `ca` del cliente apuntando a otro `ca.crt` | `Certificado de la pasarela no válido: self-signed certificate in certificate chain` |
| Directo y por la pasarela | La misma operación con el menú 3 y el menú 4 | Se comparan los tiempos de respuesta |

Para Wireshark: filtro `tcp.port == 3000` para el tramo cifrado (C1) y el puerto del
robot (por ejemplo `tcp.port == 30001`) para el tramo en claro (C2).
