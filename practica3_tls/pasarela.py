"""TLS gateway: TLS server towards the clients and plain TCP client towards the robot.

It forwards the bytes in both directions without reading what they mean.
"""
import argparse
import getpass
import logging
import socket
import ssl
import threading
from pathlib import Path

from configuracion import DEFAULT_CONFIG, load_settings

RECV_SIZE = 4096
CONNECT_TIMEOUT = 5.0  # seconds to open the TCP connection with the destination
POLL_TIMEOUT = 1.0  # seconds a read waits before checking if the session has finished


def create_context(settings, password):
    """Return the TLS context of the gateway (server side)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3  # only TLS 1.3
    # Identity of the gateway: its certificate and its encrypted private key
    context.load_cert_chain(
        Path(settings["certificado"]).expanduser(),
        Path(settings["clave"]).expanduser(),
        password=password,
    )
    # Trust only the lab CA (the system CAs are never loaded)
    context.load_verify_locations(cafile=Path(settings["ca"]).expanduser())
    context.verify_mode = ssl.CERT_REQUIRED  # every client must present a certificate
    return context


class Sesion:
    """One client connection: handshake, authorization and forwarding to the destination."""

    def __init__(self, connection, address, context, settings):
        self.connection = connection  # TCP socket just accepted, still without TLS
        self.ip = address[0]
        self.context = context
        self.settings = settings
        self.tls = None  # TLS socket with the client
        self.robot = None  # TCP socket with the destination (echo server or robot)
        self.thread = None  # thread that runs this session, set by the gateway
        # Data for the log lines, filled in after the handshake
        self.cn = "-"
        self.tls_version = "-"
        self.suite = "-"
        self.finished = threading.Event()  # set when the session must end
        self.lock = threading.Lock()  # two threads can try to finish at the same time

    def log(self, level, message):
        """Write one line of the log with the data of this connection."""
        logging.log(
            level, "ip=%s cn=%s tls=%s suite=%s | %s",
            self.ip, self.cn, self.tls_version, self.suite, message,
        )

    def run(self):
        """Whole life of the connection. Each step only runs if the previous one went well."""
        if self.handshake() and self.authorize() and self.connect_robot():
            self.forward()
        self.close()

    def handshake(self):
        """Do the TLS handshake with a time limit. Return True if the client is authenticated."""
        self.connection.settimeout(self.settings["timeout_handshake"])
        try:
            self.tls = self.context.wrap_socket(self.connection, server_side=True)
        except (ssl.SSLError, OSError) as error:
            # No certificate, unknown CA, wrong use, old TLS version, silent client...
            self.log(logging.WARNING, f"handshake rechazado: {error}")
            return False
        self.tls.settimeout(POLL_TIMEOUT)
        self.tls_version = self.tls.version()
        self.suite = self.tls.cipher()[0]
        certificate = self.tls.getpeercert()  # client certificate, already validated
        subject = dict(field[0] for field in certificate["subject"])
        self.cn = subject["commonName"]
        self.log(logging.INFO, "handshake correcto")
        return True

    def authorize(self):
        """Return True if the CN of the client is in the list of authorized clients."""
        if self.cn in self.settings["clientes_autorizados"]:
            return True
        self.log(logging.WARNING, "rechazado: el CN no está en la lista de autorizados")
        return False

    def connect_robot(self):
        """Open the TCP connection with the destination. Return True if it is open."""
        destination = (self.settings["ip_destino"], self.settings["puerto_destino"])
        try:
            self.robot = socket.create_connection(destination, timeout=CONNECT_TIMEOUT)
        except OSError as error:
            self.log(logging.ERROR, f"no se puede conectar con el destino {destination[0]}:{destination[1]}: {error}")
            return False
        self.robot.settimeout(POLL_TIMEOUT)
        self.log(logging.INFO, f"conectado con el destino {destination[0]}:{destination[1]}")
        return True

    def forward(self):
        """Copy bytes in both directions until one side ends. One thread per direction."""
        to_client = threading.Thread(target=self.copy, args=(self.robot, self.tls, "destino", "cliente"))
        to_client.start()
        self.copy(self.tls, self.robot, "cliente", "destino")
        to_client.join()

    def copy(self, source, destination, source_name, destination_name):
        """Read from source and write to destination until the session finishes."""
        while not self.finished.is_set():
            try:
                data = source.recv(RECV_SIZE)
            except TimeoutError:
                continue  # nothing arrived yet: check finished and wait again
            except OSError as error:
                self.finish(f"desconexión del {source_name}: {error}")
                return
            if not data:  # 0 bytes: the other end closed
                self.finish(f"el {source_name} ha cerrado la conexión")
                return
            try:
                destination.sendall(data)
            except OSError as error:
                self.finish(f"no se pueden reenviar los datos del {source_name}: {error}")
                return
            # Only shown with --traza: one line per block of bytes forwarded
            self.log(logging.DEBUG, f"{source_name} -> {destination_name}: {len(data)} bytes reenviados")

    def finish(self, reason):
        """Mark the session as finished and log why. Only the first reason is logged."""
        with self.lock:
            if not self.finished.is_set():
                self.finished.set()
                self.log(logging.INFO, f"cierre: {reason}")

    def close(self):
        """Close both sockets. The TLS side is closed in order, with close_notify."""
        if self.robot is not None:
            self.robot.close()
        if self.tls is None:
            self.connection.close()  # the handshake failed, there is no TLS to close
            return
        try:
            self.tls.unwrap().close()  # sends close_notify and closes
        except (ssl.SSLError, OSError):
            self.tls.close()  # the client was already gone: close anyway


class Pasarela:
    """Accepts the clients and runs one Sesion per client, each in its own thread."""

    def __init__(self, settings, password):
        self.settings = settings
        self.context = create_context(settings, password)
        self.sessions = []  # sessions that are still open
        self.lock = threading.Lock()  # protects the list of sessions

    def serve(self):
        """Accept clients until Ctrl+C, then close everything in order."""
        # Listen only on the gateway IP, not on every address of the PC
        address = (self.settings["ip_escucha"], self.settings["puerto_escucha"])
        with socket.create_server(address) as server:
            logging.info("Pasarela escuchando en %s:%d (Ctrl+C para parar)", *address)
            try:
                while True:
                    connection, client_address = server.accept()
                    self.start_session(connection, client_address)
            except KeyboardInterrupt:
                logging.info("Parada solicitada: no se aceptan más conexiones")
        self.close_sessions()
        logging.info("Pasarela detenida")

    def start_session(self, connection, address):
        session = Sesion(connection, address, self.context, self.settings)
        session.thread = threading.Thread(target=self.run_session, args=(session,))
        with self.lock:
            self.sessions.append(session)
        session.thread.start()

    def run_session(self, session):
        """Thread of one client: run the session and forget it when it ends."""
        session.run()
        with self.lock:
            self.sessions.remove(session)

    def close_sessions(self):
        """Finish the open sessions and wait for their threads to end."""
        with self.lock:
            sessions = list(self.sessions)
        for session in sessions:
            session.finish("la pasarela se detiene")
        for session in sessions:
            session.thread.join()


def setup_logging(log_file, trace=False):
    """Send the log to the log file and also to the screen. With trace, also every block forwarded."""
    logging.basicConfig(
        level=logging.DEBUG if trace else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )


def run_gateway(config_path, trace=False):
    """Load the configuration, ask for the key password and start the gateway."""
    try:
        settings = load_settings(config_path, "pasarela")
        password = getpass.getpass("Contraseña de la clave privada de la pasarela: ")
        gateway = Pasarela(settings, password)
        setup_logging(settings["fichero_registro"], trace)
        gateway.serve()
    except ssl.SSLError as error:
        print(f"No se puede cargar el certificado o la clave (¿contraseña incorrecta?): {error}")
    except (OSError, ValueError, KeyError) as error:
        print(f"No se puede arrancar la pasarela: {error!r}")


def main():
    parser = argparse.ArgumentParser(description="Pasarela TLS para el robot UR3e")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="fichero de configuración")
    parser.add_argument("--traza", action="store_true",
                        help="registra también cada bloque de bytes reenviado (sentido y tamaño)")
    args = parser.parse_args()
    run_gateway(args.config, args.traza)


if __name__ == "__main__":
    main()
