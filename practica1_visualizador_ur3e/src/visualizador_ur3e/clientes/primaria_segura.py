"""Secure version of the primary port client: the same messages, through the TLS gateway.

The robot code is not repeated here. This script only opens the connection (TLS with the
gateway of practica 3 instead of TCP with the robot) and gives it to primaria.run_robot.
"""
import json
import logging
import socket
import ssl
from contextlib import contextmanager
from pathlib import Path

from visualizador_ur3e.clientes import primaria

# Configuration file of practica 3, used when no other file is given
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "practica3_tls" / "config.json"
TLS_FILES = ("ca", "certificado", "clave")  # settings that are paths of files


class ErrorSeguro(Exception):
    """The secure connection cannot be prepared; the message explains the cause."""


def load_settings(path):
    """Return the "cliente" section of the practica 3 configuration file, with its files checked."""
    path = Path(path)
    if not path.is_file():
        raise ErrorSeguro(f"No se encuentra el fichero de configuración TLS: {path}")
    try:
        with open(path, encoding="utf-8") as file:
            settings = json.load(file)["cliente"]
    except (ValueError, KeyError) as error:
        raise ErrorSeguro(f'{path} no es un JSON válido con la sección "cliente": {error}') from error
    for name in TLS_FILES + ("puerto_pasarela",):
        if name not in settings:
            raise ErrorSeguro(f'Falta el dato "{name}" en la sección "cliente" de {path}')
    for name in TLS_FILES:
        settings[name] = Path(settings[name]).expanduser()
        if not settings[name].is_file():
            raise ErrorSeguro(f'No se encuentra el fichero de "{name}": {settings[name]}')
    return settings


class ConectorSeguro:
    """Opens TLS connections with the gateway. primaria.run_robot uses it in place of TCP."""

    def __init__(self, settings, password):
        self.port = settings["puerto_pasarela"]
        # PROTOCOL_TLS_CLIENT already verifies the gateway certificate, its use and its SAN
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_3  # only TLS 1.3
        self.context.load_verify_locations(cafile=settings["ca"])  # trust only the lab CA
        try:
            self.context.load_cert_chain(settings["certificado"], settings["clave"], password=password)
        except ssl.SSLError as error:
            raise ErrorSeguro("No se puede cargar la clave del cliente: ¿contraseña incorrecta?") from error

    @contextmanager
    def connect(self, host):
        """Open a TLS connection with the gateway at host and close it in order at the end."""
        tcp = socket.create_connection((host, self.port), timeout=primaria.TIMEOUT)
        # server_hostname is what makes the IP be checked against the SAN of the certificate
        tls = self.context.wrap_socket(tcp, server_hostname=host)
        certificate = tls.getpeercert()  # gateway certificate, already validated
        subject = dict(field[0] for field in certificate["subject"])
        logging.info(
            "Gateway %s secure connection: %s, %s, certificate CN=%s valid until %s",
            host, tls.version(), tls.cipher()[0], subject["commonName"], certificate["notAfter"],
        )
        try:
            yield tls
        finally:
            try:
                tls.unwrap()  # sends close_notify
            except OSError:
                pass  # the gateway was already gone: close anyway
            tls.close()
