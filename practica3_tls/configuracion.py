"""Reading of the JSON configuration file shared by the gateway and the client."""
import json
from pathlib import Path

DEFAULT_CONFIG = "config.json"
TLS_FILES = ("ca", "certificado", "clave")  # settings that are paths of files


class ErrorConfiguracion(Exception):
    """The configuration cannot be used; the message says exactly what is wrong."""


def load_settings(path, section):
    """Return one section ("pasarela" or "cliente") of the configuration file as a dict."""
    path = Path(path)
    if not path.is_file():
        raise ErrorConfiguracion(
            f"no se encuentra el fichero de configuración: {path.resolve()}\n"
            "  Créalo con: cp config_ejemplo.json config.json (o indica otro con --config)"
        )
    try:
        with open(path, encoding="utf-8") as file:
            config = json.load(file)
    except ValueError as error:
        raise ErrorConfiguracion(
            f"{path.resolve()} no es un JSON válido: {error}\n"
            "  En las rutas de Windows usa / en lugar de \\"
        ) from error
    if section not in config:
        raise ErrorConfiguracion(f'falta la sección "{section}" en {path.resolve()}')
    return config[section]


def file_path(settings, name):
    """Return the path of one file of the settings, after checking that the file exists."""
    if name not in settings:
        raise ErrorConfiguracion(f'falta el dato "{name}" en la configuración')
    path = Path(settings[name]).expanduser()
    if not path.is_file():
        raise ErrorConfiguracion(
            f'no se encuentra el fichero de "{name}": {path.resolve()}\n'
            f'  Valor en la configuración: "{settings[name]}"'
        )
    return path


def check_tls_files(settings):
    """Check that the CA, the certificate and the key exist, before asking for the password."""
    for name in TLS_FILES:
        file_path(settings, name)
