# E3 · Código fuente

Práctica: comunicación segura con el robot UR3e mediante una pasarela TLS.
Estudiante n.º 6.

El enunciado pide: pasarela y cliente en Python, un fichero de configuración de ejemplo y
un README que explique cómo ejecutarlos, sin claves privadas, sin `.p12` y sin
contraseñas.

## 1. Qué se entrega

Carpeta `practica3_tls/`:

| Fichero | Qué es | Pedido en E3 |
|---|---|---|
| `pasarela.py` | Pasarela: servidor TLS 1.3 con autenticación mutua, lista de autorizados, reenvío y registro | Pasarela |
| `cliente_seguro.py` | Cliente seguro: el cliente de la práctica 1 con el transporte cambiado a TLS; también conecta directo sin TLS | Cliente |
| `config_ejemplo.json` | Configuración de ejemplo, con las secciones `pasarela` y `cliente` | Configuración de ejemplo |
| `README.md` | Cómo crear la PKI, configurar y ejecutar; explicación del código y de dónde se cumple cada requisito | README |
| `configuracion.py` | Lectura del fichero de configuración, con mensajes de error claros | Lo usan la pasarela y el cliente |
| `servidor_eco.py` | Servidor de eco de la Fase 3, que sustituye al robot en las pruebas | Pruebas |
| `menu.py` | Menú de texto que lanza la pasarela, el servidor de eco y el cliente | Ejecutable |
| `crear_pki.sh` | Ejecuta las órdenes de OpenSSL de la Fase 1 | Fase 1 |
| `entrega/` | E1, E2, este documento y los certificados públicos | E1 y E2 |

Carpeta `practica1_visualizador_ur3e/src/`: el cliente seguro **importa** de aquí el
código del robot, sin modificarlo, así que tiene que ir en la entrega junto a
`practica3_tls/`.

| Fichero de la práctica 1 | Qué se usa |
|---|---|
| `visualizador_ur3e/comun/ur_protocol.py` | `extract_messages`, `parse_joint_positions`, `ROBOT_STATE` |
| `visualizador_ur3e/control/escribir.py` | `build_program`, `monitor_program` y sus constantes |
| `visualizador_ur3e/clientes/primaria_segura.py` | Conexión segura del panel web de la práctica 1 (casilla «Conexión segura (TLS)») |

## 2. Qué no se entrega

| Fichero | Motivo |
|---|---|
| `*.key` | Claves privadas |
| `*.p12` | Contienen la clave privada |
| `config.json` | Configuración local, con las IP y rutas reales |
| `pasarela.log` | Registro local |
| `__pycache__/` | Ficheros generados por Python |

Ninguno está en el repositorio: los excluye `.gitignore`. Las contraseñas no están en
ningún fichero, porque los programas las piden al arrancar con `getpass`.

## 3. Cómo se ejecuta

Resumen; los detalles están en `README.md`. Desde `practica3_tls/`, con Python 3.10 o
posterior y sin instalar nada:

```bash
./crear_pki.sh 6 10.172.18.6          # una vez: crea la CA y los certificados en ~/pki
cp config_ejemplo.json config.json    # y se editan las IP, los puertos y las rutas
./menu.py                             # menú: pasarela, servidor de eco y cliente
./menu.py --help                      # explica cada opción
```

Sin el menú:

```bash
python3 pasarela.py                       # pasarela (con --traza muestra cada bloque reenviado)
python3 cliente_seguro.py leer            # leer la posición a través de la pasarela
python3 cliente_seguro.py mover           # mover el robot y verificar la posición
python3 cliente_seguro.py --directo leer  # lo mismo, directo al robot y sin TLS
```

## 4. Cómo crear el fichero comprimido

Desde la raíz del repositorio. `git archive` solo incluye los ficheros que están en el
repositorio, así que no puede colarse ninguna clave ni configuración local. Antes hay que
hacer `git add` y `git commit` de la carpeta `entrega/`.

```bash
git archive --format=zip -o <tu_nombre>_practica3.zip HEAD \
  practica3_tls practica1_visualizador_ur3e/src
```

Comprobación de que no hay claves dentro (no debe mostrar nada):

```bash
unzip -l <tu_nombre>_practica3.zip | grep -E "\.key|\.p12|config\.json|\.log"
```

La captura de Wireshark de la demostración se añade a la entrega después:

```bash
zip <tu_nombre>_practica3.zip captura_demostracion.pcapng
```
