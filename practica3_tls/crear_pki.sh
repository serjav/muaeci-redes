#!/usr/bin/env bash
# Phase 1: creates the CA and the certificates of pasarela, cliente-a and cliente-b
# in ~/pki, with the same OpenSSL commands as the assignment.
#
# Usage:   ./crear_pki.sh <numero_estudiante> <ip_pasarela>
# Example: ./crear_pki.sh 7 10.172.21.30
# Help:    ./crear_pki.sh --help
#
# It only asks for the four passwords (CA, pasarela, cliente-a, cliente-b).

set -e  # stop at the first command that fails

usage() {
    cat <<HELP
Uso: ./crear_pki.sh <numero_estudiante> <ip_pasarela>
     ./crear_pki.sh --help

Crea en ~/pki la PKI de la práctica 3 (Fase 1) con OpenSSL: una CA propia y
los certificados de la pasarela, de cliente-a y de cliente-b.

Argumentos:
  numero_estudiante  Tu número de estudiante. Va en el nombre de la CA:
                     "CA Robot Lab - estudiante N".
  ip_pasarela        IP de la pasarela en la red del laboratorio. Va en la SAN
                     del certificado de la pasarela: el cliente solo acepta la
                     pasarela si se conecta a esta misma IP.

Ejemplo:
  ./crear_pki.sh 7 10.172.21.30

Lo único que pregunta son cuatro contraseñas, dos veces cada una y sin
mostrarlas (mínimo 4 caracteres):
  1. clave de la CA         solo se usa aquí, para firmar los certificados
  2. clave de la pasarela   la pide la pasarela al arrancar
  3. clave de cliente-a     la pide el cliente al conectar
  4. clave de cliente-b     la pide el cliente al conectar como cliente-b

Ficheros que crea en ~/pki:
  ca-privado/ca.key                 clave de la CA. SECRETA, no se copia nunca
  publico/ca.crt                    certificado de la CA, para todos los equipos
  pasarela/pasarela.crt y .key      para el PC de la pasarela
  cliente-a/cliente-a.crt y .key    para la máquina del cliente (autorizado)
  cliente-b/cliente-b.crt y .key    para probar un cliente no autorizado
  pasarela.ext, cliente.ext         extensiones que impone la CA

Al terminar muestra la verificación de la cadena (debe decir OK tres veces) y
el titular, emisor, número de serie, validez y huella de cada certificado.

Después:
  1. Copia a la máquina del cliente publico/ca.crt, cliente-a/cliente-a.crt
     y cliente-a/cliente-a.key.
  2. Pon las rutas de esos ficheros y la IP de la pasarela en config.json.

Si ya existe una CA en ~/pki, el script se detiene y no sobrescribe nada.
Necesita OpenSSL 3 (compruébalo con: openssl version).
HELP
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
    exit 0
fi
if [ $# -ne 2 ]; then
    usage
    exit 1
fi
STUDENT="$1"
GATEWAY_IP="$2"
PKI="$HOME/pki"

# Never overwrite an existing CA: every certificate it signed would stop being valid
if [ -e "$PKI/ca-privado/ca.key" ]; then
    echo "Ya existe una CA en $PKI. Bórrala o muévela antes de crear otra."
    exit 1
fi

# Ask for a password twice, without showing it, and store it in the variable named $1
ask_password() {
    local first second
    while true; do
        read -r -s -p "Contraseña para $2: " first; echo
        read -r -s -p "Repite la contraseña: " second; echo
        if [ "$first" = "$second" ] && [ ${#first} -ge 4 ]; then
            break
        fi
        echo "No coinciden o tiene menos de 4 caracteres. Inténtalo de nuevo."
    done
    export "$1=$first"  # exported so that openssl can read it with env:NAME
}

ask_password CA_PASS "la clave de la CA"
ask_password PASARELA_PASS "la clave de la pasarela"
ask_password CLIENTE_A_PASS "la clave de cliente-a"
ask_password CLIENTE_B_PASS "la clave de cliente-b"

# Step 1: folders. Only the owner can open ca-privado
mkdir -p "$PKI/ca-privado" "$PKI/publico" "$PKI/pasarela" "$PKI/cliente-a" "$PKI/cliente-b"
cd "$PKI"
chmod 700 ca-privado

# Step 2: the CA (key + self-signed certificate, 2 years)
openssl req -x509 -newkey rsa:2048 -sha256 -days 730 \
    -keyout ca-privado/ca.key -out publico/ca.crt \
    -subj "/CN=CA Robot Lab - estudiante $STUDENT" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -passout env:CA_PASS

# Step 3: extension files (the CA decides the extensions)
cat > pasarela.ext <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = IP:$GATEWAY_IP
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
EOF

cat > cliente.ext <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
EOF

# Step 4: encrypted key and signing request (CSR) of each machine
openssl req -new -newkey rsa:2048 \
    -keyout pasarela/pasarela.key -out pasarela/pasarela.csr \
    -subj "/CN=pasarela-ur3e" -passout env:PASARELA_PASS

openssl req -new -newkey rsa:2048 \
    -keyout cliente-a/cliente-a.key -out cliente-a/cliente-a.csr \
    -subj "/CN=cliente-a" -passout env:CLIENTE_A_PASS

openssl req -new -newkey rsa:2048 \
    -keyout cliente-b/cliente-b.key -out cliente-b/cliente-b.csr \
    -subj "/CN=cliente-b" -passout env:CLIENTE_B_PASS

# Step 5: the CA signs each request (1 year)
openssl x509 -req -in pasarela/pasarela.csr \
    -CA publico/ca.crt -CAkey ca-privado/ca.key \
    -CAserial ca-privado/ca.srl -CAcreateserial \
    -days 365 -sha256 -extfile pasarela.ext \
    -out pasarela/pasarela.crt -passin env:CA_PASS

openssl x509 -req -in cliente-a/cliente-a.csr \
    -CA publico/ca.crt -CAkey ca-privado/ca.key -CAserial ca-privado/ca.srl \
    -days 365 -sha256 -extfile cliente.ext \
    -out cliente-a/cliente-a.crt -passin env:CA_PASS

openssl x509 -req -in cliente-b/cliente-b.csr \
    -CA publico/ca.crt -CAkey ca-privado/ca.key -CAserial ca-privado/ca.srl \
    -days 365 -sha256 -extfile cliente.ext \
    -out cliente-b/cliente-b.crt -passin env:CA_PASS

# Step 6: only the owner can read the keys
chmod 600 ca-privado/ca.key pasarela/pasarela.key cliente-a/cliente-a.key cliente-b/cliente-b.key

# Step 7: the chain of each certificate must reach the CA (OK three times)
echo
echo "== Verificación de la cadena =="
openssl verify -CAfile publico/ca.crt \
    pasarela/pasarela.crt cliente-a/cliente-a.crt cliente-b/cliente-b.crt

# Step 9: data for the table of certificates of the report
for name in pasarela cliente-a cliente-b; do
    echo
    echo "== $name =="
    openssl x509 -in "$name/$name.crt" -noout -subject -issuer -serial -dates -fingerprint -sha256
done

echo
echo "PKI creada en $PKI"
echo "Copia a la máquina del cliente: publico/ca.crt, cliente-a/cliente-a.crt y cliente-a/cliente-a.key"
