"""Secure client: the robot client of practica 1 with the transport changed from TCP to TLS.

The code that builds and reads the robot messages is imported from practica 1 as it is.
"""
import argparse
import getpass
import logging
import socket
import ssl
import sys
import time
from pathlib import Path

from configuracion import DEFAULT_CONFIG, ErrorConfiguracion, check_tls_files, file_path, load_settings

# Make the practica 1 package importable: it lives in the folder next to this one
PRACTICA1_SRC = Path(__file__).resolve().parent.parent / "practica1_visualizador_ur3e" / "src"
sys.path.insert(0, str(PRACTICA1_SRC))

from visualizador_ur3e.comun.ur_protocol import ROBOT_STATE, extract_messages, parse_joint_positions
from visualizador_ur3e.control.escribir import (
    RECV_SIZE,
    STARTUP_TIMEOUT,
    TARGET_JOINTS,
    TIMEOUT,
    build_program,
    monitor_program,
)


class ErrorCliente(Exception):
    """Something failed; the message explains the cause to the user."""


def create_context(settings, password):
    """Return the TLS context of the client."""
    # PROTOCOL_TLS_CLIENT already verifies the gateway certificate, its use and its SAN
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3  # only TLS 1.3
    # Trust only the lab CA (the system CAs are never loaded)
    context.load_verify_locations(cafile=file_path(settings, "ca"))
    # Identity of the client: its certificate and its encrypted private key
    context.load_cert_chain(
        file_path(settings, "certificado"),
        file_path(settings, "clave"),
        password=password,
    )
    return context


class ClienteSeguro:
    """Robot client that connects through the gateway (TLS) or directly to the robot (TCP)."""

    def __init__(self, settings, password=None, direct=False):
        self.direct = direct
        self.sock = None
        if direct:
            self.address = (settings["ip_robot"], settings["puerto_robot"])
            self.peer = "el robot"
        else:
            self.address = (settings["ip_pasarela"], settings["puerto_pasarela"])
            self.peer = "la pasarela"
            self.context = create_context(settings, password)

    def connect(self):
        """Open the connection. Through the gateway, also do the TLS handshake."""
        ip, port = self.address
        try:
            tcp = socket.create_connection(self.address, timeout=TIMEOUT)
        except ConnectionRefusedError as error:
            raise ErrorCliente(f"Conexión rechazada: {self.peer} no escucha en {ip}:{port}") from error
        except OSError as error:
            raise ErrorCliente(f"No se puede alcanzar {self.peer} en {ip}:{port}: {error}") from error
        if self.direct:
            self.sock = tcp
            print(f"Conectado directamente al robot {ip}:{port} (TCP en claro)")
            return
        try:
            # server_hostname is what makes the IP be checked against the SAN
            self.sock = self.context.wrap_socket(tcp, server_hostname=ip)
        except ssl.SSLCertVerificationError as error:
            raise ErrorCliente(f"Certificado de la pasarela no válido: {error.verify_message}") from error
        except ssl.SSLError as error:
            raise ErrorCliente(f"Error TLS durante el handshake: {error.reason}") from error
        except OSError as error:
            raise ErrorCliente(f"Error de red durante el handshake: {error}") from error
        self.show_connection()

    def show_connection(self):
        """Print the negotiated TLS version and suite and the gateway certificate."""
        certificate = self.sock.getpeercert()  # gateway certificate, already validated
        subject = dict(field[0] for field in certificate["subject"])
        print(f"Conectado a la pasarela {self.address[0]}:{self.address[1]}")
        print(f"  Versión TLS: {self.sock.version()}")
        print(f"  Suite:       {self.sock.cipher()[0]}")
        print(f"  Certificado: CN={subject['commonName']}, caduca el {certificate['notAfter']}")

    def close(self):
        """Close the connection. With TLS, send close_notify first."""
        if self.sock is None:
            return
        try:
            if not self.direct:
                self.sock = self.sock.unwrap()  # sends close_notify
        except (ssl.SSLError, OSError):
            pass  # the gateway was already gone: close anyway
        self.sock.close()
        self.sock = None

    def read_joints(self):
        """Return the joint positions of the first robot state received."""
        buffer = bytearray()
        while True:
            data = self.sock.recv(RECV_SIZE)
            if not data:
                raise ConnectionError("Connection closed")
            buffer.extend(data)
            for msg_type, body in extract_messages(buffer):
                if msg_type == ROBOT_STATE:
                    joints = parse_joint_positions(body)
                    if joints is not None:
                        return joints

    def move_and_verify(self):
        """Move the robot to TARGET_JOINTS and return True if it got there (as escribir.py)."""
        self.sock.sendall(build_program(TARGET_JOINTS).encode("utf-8"))
        return monitor_program(self.sock, TARGET_JOINTS, STARTUP_TIMEOUT)

    def run(self, operation):
        """Connect, run one operation and close. Return (result, seconds it took)."""
        start = time.perf_counter()
        self.connect()
        try:
            result = operation()
            seconds = time.perf_counter() - start
        except ssl.SSLError as error:
            # With TLS 1.3 a client certificate rejected by the gateway shows up here,
            # in the first read, and not in connect()
            if "ALERT" in str(error.reason):
                raise ErrorCliente(f"La pasarela ha rechazado el certificado del cliente: {error.reason}") from error
            raise ErrorCliente(f"Error TLS: {error}") from error
        except TimeoutError as error:
            raise ErrorCliente(f"Sin respuesta: {self.peer} no ha enviado datos en {TIMEOUT} s") from error
        except ConnectionError as error:
            if self.direct:
                raise ErrorCliente("Conexión cerrada por el robot") from error
            raise ErrorCliente(
                "Conexión cerrada por la pasarela después del handshake: "
                "cliente no autorizado o robot no disponible"
            ) from error
        except (OSError, ValueError) as error:
            raise ErrorCliente(f"Error en la comunicación con {self.peer}: {error}") from error
        finally:
            self.close()
        return result, seconds


def create_client(config_path, direct):
    """Load the configuration and build the client. Ask for the key password if TLS is used."""
    try:
        settings = load_settings(config_path, "cliente")
        password = None
        if not direct:
            check_tls_files(settings)  # a missing file is reported before asking for the password
            password = getpass.getpass("Contraseña de la clave privada del cliente: ")
        return ClienteSeguro(settings, password, direct)
    except ssl.SSLError as error:
        raise ErrorCliente(f"No se puede cargar el certificado o la clave (¿contraseña incorrecta?): {error}") from error
    except ErrorConfiguracion as error:
        raise ErrorCliente(f"Configuración: {error}") from error
    except KeyError as error:
        raise ErrorCliente(f'Configuración: falta el dato {error} en la sección "cliente" de {config_path}') from error


def show_read(client):
    """Read the joint positions once and print them with the response time."""
    joints, seconds = client.run(client.read_joints)
    print("Posición articular (rad): " + ", ".join(f"{joint:.4f}" for joint in joints))
    print(f"Tiempo de respuesta: {seconds * 1000:.1f} ms")


def show_move(client):
    """Move the robot, verify the final position and print the response time."""
    reached, seconds = client.run(client.move_and_verify)
    print("Posición verificada" if reached else "El robot NO ha alcanzado la posición")
    print(f"Tiempo de respuesta: {seconds * 1000:.1f} ms")


def main():
    parser = argparse.ArgumentParser(description="Cliente seguro del robot UR3e")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="fichero de configuración")
    parser.add_argument("--directo", action="store_true",
                        help="conectar directamente al robot, sin TLS ni pasarela")
    parser.add_argument("operacion", choices=["leer", "mover"],
                        help="leer la posición articular o mover el robot y verificar")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    try:
        client = create_client(args.config, args.directo)
        if args.operacion == "leer":
            show_read(client)
        else:
            show_move(client)
    except ErrorCliente as error:
        print(f"ERROR: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nDetenido por el usuario")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
