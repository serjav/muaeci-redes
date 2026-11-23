# E1 · Registro de la PKI

Práctica: comunicación segura con el robot UR3e mediante una pasarela TLS.
Estudiante n.º 6 · IP de la pasarela: `10.172.18.6` · OpenSSL 3.5.5

La PKI se creó el 13/11/2026 en `~/pki` con el script `crear_pki.sh`, que ejecuta las
órdenes de la Fase 1 del enunciado. Los certificados públicos están en la carpeta
[`certificados/`](certificados/): `ca.crt`, `pasarela.crt`, `cliente-a.crt` y
`cliente-b.crt`. No se entrega ninguna clave privada.

## 1. Estructura de la PKI

```
CA Robot Lab - estudiante 6        ca.crt (autofirmado, CA:TRUE)
├── pasarela-ur3e                  serverAuth, SAN IP 10.172.18.6
├── cliente-a                      clientAuth, autorizado en la pasarela
└── cliente-b                      clientAuth, NO autorizado
```

No hay CA intermedia: la CA raíz firma directamente los tres certificados de equipo.

## 2. Tabla de certificados emitidos

Datos obtenidos de cada certificado con esta orden (aquí, con el de la pasarela):
`openssl x509 -in pasarela/pasarela.crt -noout -subject -issuer -serial -dates -fingerprint -sha256`.

| | CA | Pasarela | Cliente A | Cliente B |
|---|---|---|---|---|
| Fichero | `ca.crt` | `pasarela.crt` | `cliente-a.crt` | `cliente-b.crt` |
| Titular (Subject) | CN=CA Robot Lab - estudiante 6 | CN=pasarela-ur3e | CN=cliente-a | CN=cliente-b |
| Emisor (Issuer) | CN=CA Robot Lab - estudiante 6 | CN=CA Robot Lab - estudiante 6 | CN=CA Robot Lab - estudiante 6 | CN=CA Robot Lab - estudiante 6 |
| Válido desde | 13/11/2026 15:19:39 GMT | 13/11/2026 15:19:40 GMT | 13/11/2026 15:19:40 GMT | 13/11/2026 15:19:40 GMT |
| Válido hasta | 12/11/2028 15:19:39 GMT | 13/11/2027 15:19:40 GMT | 13/11/2027 15:19:40 GMT | 13/11/2027 15:19:40 GMT |
| Validez | 2 años (730 días) | 1 año (365 días) | 1 año (365 días) | 1 año (365 días) |
| basicConstraints | crítica, CA:TRUE | crítica, CA:FALSE | crítica, CA:FALSE | crítica, CA:FALSE |
| keyUsage | crítica, Certificate Sign, CRL Sign | crítica, Digital Signature | crítica, Digital Signature | crítica, Digital Signature |
| extendedKeyUsage | — | TLS Web Server Authentication (serverAuth) | TLS Web Client Authentication (clientAuth) | TLS Web Client Authentication (clientAuth) |
| SAN | — | IP Address:10.172.18.6 | — | — |
| Clave pública | RSA 2048 bits | RSA 2048 bits | RSA 2048 bits | RSA 2048 bits |
| Algoritmo de firma | sha256WithRSAEncryption | sha256WithRSAEncryption | sha256WithRSAEncryption | sha256WithRSAEncryption |
| Papel en la práctica | Ancla de confianza | Identidad de la pasarela | Cliente autorizado | Cliente válido pero no autorizado |

Números de serie:

| Certificado | Número de serie |
|---|---|
| CA | `499F738DE2A856E43A966C48FAD1144E888B500F` |
| Pasarela | `15E3A29CED187CC9914E65E6240515FF2BE1B961` |
| Cliente A | `15E3A29CED187CC9914E65E6240515FF2BE1B962` |
| Cliente B | `15E3A29CED187CC9914E65E6240515FF2BE1B963` |

El de la pasarela lo generó OpenSSL al azar (`-CAcreateserial`); los de los clientes son
los siguientes del fichero `ca-privado/ca.srl`.

Huellas SHA-256:

| Certificado | Huella SHA-256 |
|---|---|
| CA | `3B:B7:AC:B2:A3:0D:24:26:F6:A3:17:5F:4B:BA:70:41:A1:1F:B5:D8:02:9C:10:BE:17:99:59:AF:E6:F0:81:6A` |
| Pasarela | `CA:DF:C7:65:BB:2A:D1:49:64:11:8D:90:80:96:01:0A:A7:E4:1F:DB:06:0C:D6:47:0D:32:2D:F5:BC:D3:2A:3C` |
| Cliente A | `A4:12:A6:3F:F2:4A:19:24:FB:D7:C8:6D:C5:97:82:3C:11:75:D8:65:6E:8A:CD:33:62:C6:C6:20:97:66:5B:9B` |
| Cliente B | `AC:4C:4C:5B:3A:27:67:20:30:68:5B:B8:E5:E9:34:1A:1A:45:C6:65:A4:05:E0:B9:A5:27:99:4C:5C:F9:76:FC` |

## 3. En qué equipo está cada fichero

| Fichero | PC donde se creó la PKI | Pasarela | Cliente (máquina virtual) | ¿Secreto? |
|---|---|---|---|---|
| `ca-privado/ca.key` | Sí | Nunca | Nunca | Sí, el que más |
| `publico/ca.crt` | Sí | Sí | Sí | No |
| `pasarela/pasarela.crt` | Sí | Sí | No | No |
| `pasarela/pasarela.key` | Sí | Sí | No | Sí |
| `cliente-a/cliente-a.crt` | Sí | No | Sí | No |
| `cliente-a/cliente-a.key` | Sí | No | Sí | Sí |
| `cliente-b/cliente-b.crt` | Sí | No | Sí, solo para la prueba de autorización | No |
| `cliente-b/cliente-b.key` | Sí | No | Sí, solo para la prueba de autorización | Sí |

## 4. Salida de `openssl verify`

```
$ openssl verify -CAfile publico/ca.crt pasarela/pasarela.crt cliente-a/cliente-a.crt cliente-b/cliente-b.crt
pasarela/pasarela.crt: OK
cliente-a/cliente-a.crt: OK
cliente-b/cliente-b.crt: OK
```

Los tres certificados están firmados por la CA y la cadena llega al ancla de confianza.

Comprobación de la petición de firma de la pasarela:

```
$ openssl req -in pasarela/pasarela.csr -noout -verify -subject
Certificate request self-signature verify OK
subject=CN=pasarela-ur3e
```

**Verificación con otra CA** (paso 7). No se disponía del `ca.crt` de otro estudiante,
así que se creó una CA distinta solo para esta prueba (`/tmp/otra.crt`, con
`CN=otra CA`). El resultado es el mismo que con la CA de un compañero: el certificado de
la pasarela no está firmado por ella.

```
$ openssl req -x509 -newkey rsa:2048 -noenc -days 1 -subj "/CN=otra CA" \
    -keyout /tmp/otra.key -out /tmp/otra.crt

$ openssl verify -CAfile /tmp/otra.crt pasarela/pasarela.crt
CN=pasarela-ur3e
error 20 at 0 depth lookup: unable to get local issuer certificate
error pasarela/pasarela.crt: verification failed
```

Es el primer fallo de confianza provocado a propósito: con un ancla de confianza que no
es la CA que firmó el certificado, la cadena no se puede construir.

**La clave corresponde al certificado** (paso 7). Se compara la huella de la clave
pública sacada del certificado con la sacada de la clave privada. Las dos coinciden.

```
$ openssl x509 -in pasarela/pasarela.crt -noout -pubkey | openssl sha256
SHA2-256(stdin)= 0d6831713180df69baf06cdb3e4bc83cc047679939c4d67e68425e07a59fdb94

$ openssl pkey -in pasarela/pasarela.key -pubout | openssl sha256
Enter pass phrase for pasarela/pasarela.key:
SHA2-256(stdin)= 0d6831713180df69baf06cdb3e4bc83cc047679939c4d67e68425e07a59fdb94
```

## 5. Permisos de los ficheros de clave

```
$ ls -ld ca-privado
drwx------ 2 savila savila 4096 Nov 13 15:19 ca-privado

$ ls -l ca-privado/ca.key pasarela/pasarela.key cliente-a/cliente-a.key cliente-b/cliente-b.key
-rw------- 1 savila savila 1886 Nov 13 15:19 ca-privado/ca.key
-rw------- 1 savila savila 1886 Nov 13 15:19 cliente-a/cliente-a.key
-rw------- 1 savila savila 1886 Nov 13 15:19 cliente-b/cliente-b.key
-rw------- 1 savila savila 1886 Nov 13 15:19 pasarela/pasarela.key
```

- La carpeta `ca-privado` tiene permisos `700`: solo su propietario puede entrar.
- Las cuatro claves tienen permisos `600`: solo su propietario puede leerlas.
- Las cuatro claves están cifradas con contraseña: la primera línea de cada fichero es
  `-----BEGIN ENCRYPTED PRIVATE KEY-----`.

**Política de contraseñas.** Cada clave tiene su propia contraseña. No está en el código
ni en el fichero de configuración: la pasarela y el cliente la piden al arrancar con
`getpass`, que no la muestra en pantalla. Así, quien consiga el código, la configuración
o incluso el fichero `.key` no puede usar la clave sin la contraseña, y la contraseña no
queda en el repositorio ni en el historial de órdenes.

## 6. Prueba de humo (paso 8)

La prueba usa `openssl s_server` como pasarela y `openssl s_client` como cliente, sin
código propio, desde `~/pki`.

En el PC de la pasarela:

```bash
openssl s_server -accept 3000 -tls1_3 \
  -cert pasarela/pasarela.crt -key pasarela/pasarela.key \
  -CAfile publico/ca.crt -Verify 1 -verify_return_error
```

En el cliente:

```bash
openssl s_client -connect 10.172.18.6:3000 -tls1_3 \
  -CAfile publico/ca.crt -cert cliente-a/cliente-a.crt -key cliente-a/cliente-a.key \
  -verify_ip 10.172.18.6 -verify_return_error
```

La prueba se hizo con el servidor y el cliente en el mismo PC, por lo que el cliente se
conectó con `-connect 127.0.0.1:3000`. La opción `-verify_ip 10.172.18.6` no cambia: la
comprobación de la SAN se hace contra esa IP, no contra la dirección de `-connect`.

### Resumen

| Prueba | Resultado esperado | Resultado obtenido | ¿Coincide? |
|---|---|---|---|
| Autenticación mutua correcta | `Verify return code: 0 (ok)`, TLSv1.3 y la suite | `Verify return code: 0 (ok)`, TLSv1.3, `TLS_AES_256_GCM_SHA384` | Sí |
| Cliente sin `-cert` ni `-key` | Servidor: `peer did not return a certificate`. Cliente: alerta `certificate required` | Cliente: `tlsv13 alert certificate required` (alerta 116) | Sí |
| Cliente con otra CA (`/tmp/otra.crt`, en lugar del `ca.crt` de otro estudiante) | `self-signed certificate in certificate chain` o `unable to get local issuer certificate` | `Verify return code: 19 (self-signed certificate in certificate chain)` | Sí |
| `-verify_ip` con una IP distinta de la de la SAN | `IP address mismatch` | `Verify return code: 64 (IP address mismatch)` | Sí |
| Cliente con `-tls1_2` en lugar de `-tls1_3` | El cliente recibe la alerta `protocol version` | `tlsv1 alert protocol version` (alerta 70); no se negocia ninguna suite | Sí |

Versión y suite negociadas en la prueba correcta: **TLSv1.3**, **TLS_AES_256_GCM_SHA384**.

### Salida de cada prueba

Salida del cliente (`openssl s_client`) en cada caso.

**1. Autenticación mutua correcta.** El cliente valida a la pasarela y el handshake
termina en TLS 1.3.

```
SSL handshake has read 3470 bytes and written 3301 bytes
Verification: OK
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Protocol: TLSv1.3
Server public key is 2048 bit
This TLS version forbids renegotiation.
Compression: NONE
Expansion: NONE
No ALPN negotiated
Early data was not sent
Verify return code: 0 (ok)
```

**2. Cliente sin `-cert` ni `-key`.** El handshake parece correcto desde el cliente,
porque en TLS 1.3 el servidor valida al cliente al final. El rechazo llega después, como
alerta `certificate required` (número 116), en la última línea.

```
SSL handshake has read 3470 bytes and written 1570 bytes
Verification: OK
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Protocol: TLSv1.3
Server public key is 2048 bit
This TLS version forbids renegotiation.
Compression: NONE
Expansion: NONE
No ALPN negotiated
Early data was not sent
Verify return code: 0 (ok)
---
40E72768817A0000:error:0A00045C:SSL routines:ssl3_read_bytes:tlsv13 alert certificate required:../ssl/record/rec_layer_s3.c:918:SSL alert number 116
```

**3. Cliente con otra CA.** Se usó `-CAfile /tmp/otra.crt`, la CA creada para la
prueba del apartado 4. El cliente no puede llegar desde el certificado de la
pasarela hasta una CA en la que confíe.

```
SSL handshake has read 3110 bytes and written 1467 bytes
Verification error: self-signed certificate in certificate chain
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Protocol: TLSv1.3
This TLS version forbids renegotiation.
Compression: NONE
Expansion: NONE
No ALPN negotiated
Early data was not sent
Verify return code: 19 (self-signed certificate in certificate chain)
```

**4. `-verify_ip` con otra IP.** El certificado es válido, pero la IP comprobada no está
en su SAN.

```
SSL handshake has read 3110 bytes and written 1467 bytes
Verification error: IP address mismatch
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Protocol: TLSv1.3
This TLS version forbids renegotiation.
Compression: NONE
Expansion: NONE
No ALPN negotiated
Early data was not sent
Verify return code: 64 (IP address mismatch)
```

**5. Cliente con `-tls1_2`.** El servidor solo admite TLS 1.3, así que corta el handshake
en cuanto recibe el Client Hello y responde con la alerta `protocol version` (número 70).
El cliente solo lee 7 bytes (la alerta), no recibe ningún certificado y no se negocia
ninguna suite. El `Verify return code: 0 (ok)` del final no significa que la conexión sea
válida: no hubo ningún certificado que verificar.

```
Connecting to 127.0.0.1
CONNECTED(00000003)
40E722D9687C0000:error:0A00042E:SSL routines:ssl3_read_bytes:tlsv1 alert protocol version:../ssl/record/rec_layer_s3.c:918:SSL alert number 70
---
no peer certificate available
---
No client certificate CA names sent
---
SSL handshake has read 7 bytes and written 191 bytes
Verification: OK
---
New, (NONE), Cipher is (NONE)
Protocol: TLSv1.2
Secure Renegotiation IS NOT supported
Compression: NONE
Expansion: NONE
No ALPN negotiated
SSL-Session:
    Protocol  : TLSv1.2
    Cipher    : 0000
    Session-ID: 
    Session-ID-ctx: 
    Master-Key: 
    PSK identity: None
    PSK identity hint: None
    SRP username: None
    Start Time: 1794774061
    Timeout   : 7200 (sec)
    Verify return code: 0 (ok)
    Extended master secret: no
```

## 7. Explicación de cada opción de OpenSSL usada

### Crear la CA

```bash
openssl req -x509 -newkey rsa:2048 -sha256 -days 730 \
  -keyout ca-privado/ca.key -out publico/ca.crt \
  -subj "/CN=CA Robot Lab - estudiante 6" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
```

| Opción | Qué hace |
|---|---|
| `req` | Subcomando que crea peticiones de certificado |
| `-x509` | En lugar de una petición, genera directamente un certificado autofirmado. Es lo que necesita una CA raíz, que no tiene a nadie por encima que la firme |
| `-newkey rsa:2048` | Crea a la vez un par de claves RSA de 2048 bits |
| `-sha256` | El resumen que se firma se calcula con SHA-256. SHA-1 ya no se admite en certificados |
| `-days 730` | El certificado vale 2 años |
| `-keyout` | Dónde se guarda la clave privada. Va a `ca-privado`, que solo abre su propietario |
| `-out` | Dónde se guarda el certificado. Va a `publico` porque se reparte a todos los equipos |
| `-subj` | Nombre del titular. Como es autofirmado, también es el emisor |
| `-addext basicConstraints=critical,CA:TRUE` | Marca el certificado como CA: puede firmar otros certificados |
| `-addext keyUsage=critical,keyCertSign,cRLSign` | La clave solo sirve para firmar certificados y listas de revocación |

`critical` significa que un programa que no entienda la extensión debe rechazar el
certificado en lugar de ignorarla.

### Clave y petición de firma (CSR) de cada equipo

```bash
openssl req -new -newkey rsa:2048 \
  -keyout pasarela/pasarela.key -out pasarela/pasarela.csr \
  -subj "/CN=pasarela-ur3e"
```

| Opción | Qué hace |
|---|---|
| `req -new` | Crea una petición de firma (CSR). Sin `-x509` no se genera un certificado |
| `-newkey rsa:2048` | Crea el par de claves del equipo |
| `-keyout` | Clave privada del equipo. Se queda en su carpeta y no se mueve |
| `-out` | La petición: contiene la clave pública y el nombre, firmados con la clave privada. Esa firma demuestra que quien pide el certificado tiene la clave |
| `-subj "/CN=..."` | Nombre del equipo: `pasarela-ur3e`, `cliente-a` o `cliente-b` |
| (sin `-noenc`) | La clave se guarda cifrada con una contraseña. `-noenc` la dejaría sin cifrar, por eso no se usa |

### La CA firma cada petición

```bash
openssl x509 -req -in pasarela/pasarela.csr \
  -CA publico/ca.crt -CAkey ca-privado/ca.key \
  -CAserial ca-privado/ca.srl -CAcreateserial \
  -days 365 -sha256 -extfile pasarela.ext \
  -out pasarela/pasarela.crt
```

| Opción | Qué hace |
|---|---|
| `x509 -req -in` | Toma una petición de firma y la convierte en certificado |
| `-CA` y `-CAkey` | Certificado y clave privada de la CA que firma. Pide la contraseña de la CA |
| `-CAserial` | Fichero donde la CA lleva la cuenta de los números de serie |
| `-CAcreateserial` | Crea ese fichero la primera vez, con un valor aleatorio. Solo hace falta en la primera firma |
| `-days 365` | El certificado vale 1 año |
| `-sha256` | La CA firma con SHA-256 |
| `-extfile` | Fichero con las extensiones. Las decide la CA, no el equipo que pide el certificado |
| `-out` | Certificado firmado |

### Ficheros de extensiones

| Línea | Qué hace |
|---|---|
| `basicConstraints = critical, CA:FALSE` | Es un certificado de equipo: no puede firmar otros certificados |
| `keyUsage = critical, digitalSignature` | La clave solo sirve para firmar, que es lo que hace cada extremo en el handshake de TLS 1.3 |
| `extendedKeyUsage = serverAuth` | Solo en la pasarela: el certificado vale para identificarse como servidor TLS |
| `extendedKeyUsage = clientAuth` | Solo en los clientes: el certificado vale para identificarse como cliente TLS |
| `subjectAltName = IP:10.172.18.6` | Solo en la pasarela: IP para la que vale el certificado. El cliente comprueba que es la dirección a la que se ha conectado |
| `subjectKeyIdentifier = hash` | Identificador de la clave del propio certificado |
| `authorityKeyIdentifier = keyid, issuer` | Identificador de la clave de la CA que lo firmó. Ayuda a construir la cadena |

Los clientes no llevan SAN: la pasarela no comprueba su dirección, sino su CN.

### Proteger y comprobar

| Orden | Qué hace |
|---|---|
| `chmod 700 ca-privado` | Solo el propietario puede entrar en la carpeta de la CA |
| `chmod 600 pasarela/pasarela.key` | Solo el propietario puede leer la clave. Se aplica a las cuatro claves |
| `openssl pkey -in pasarela/pasarela.key -noout` | Lee la clave sin mostrarla. Si pide contraseña, la clave está cifrada |
| `openssl x509 -in pasarela/pasarela.crt -noout -text` | Muestra el certificado completo en texto |
| `openssl x509 ... -subject -issuer -serial -dates -fingerprint -sha256` | Muestra solo titular, emisor, número de serie, fechas y huella SHA-256. Son los datos de la tabla |
| `openssl req -in pasarela/pasarela.csr -noout -verify -subject` | Comprueba la firma de la petición y muestra su titular |
| `openssl verify -CAfile publico/ca.crt pasarela/pasarela.crt cliente-a/cliente-a.crt cliente-b/cliente-b.crt` | Comprueba que cada certificado está firmado por la CA y que la cadena llega a ella |
| `openssl x509 ... -pubkey \| openssl sha256` y `openssl pkey ... -pubout \| openssl sha256` | Calculan la huella de la clave pública sacada del certificado y de la clave privada. Si coinciden, la clave corresponde al certificado |

### Prueba de humo

| Opción | Qué hace |
|---|---|
| `s_server -accept 3000` | Servidor TLS de pruebas que escucha en el puerto 3000 |
| `s_client -connect IP:3000` | Cliente TLS de pruebas que se conecta a esa dirección |
| `-tls1_3` | Limita la herramienta a TLS 1.3, igual que los programas |
| `-cert` y `-key` | Certificado y clave con los que se identifica ese extremo |
| `-CAfile` | Ancla de confianza con la que se valida al otro extremo |
| `-Verify 1` (servidor) | Exige certificado al cliente. Con `-verify` en minúsculas solo lo pediría |
| `-verify_ip` (cliente) | Comprueba que esa IP está en la SAN del certificado del servidor |
| `-verify_return_error` | Corta la conexión si la validación falla, en lugar de solo avisar |

### Diferencia entre el script y las órdenes del enunciado

`crear_pki.sh` ejecuta estas mismas órdenes, pero pregunta las cuatro contraseñas una
sola vez y se las pasa a OpenSSL con `-passout env:VARIABLE` (al crear una clave) y
`-passin env:VARIABLE` (al usar la clave de la CA). Sin esas opciones, OpenSSL pediría la
contraseña en cada orden. Se usa `env:` y no `pass:` para que la contraseña no aparezca
en la lista de procesos del sistema.
