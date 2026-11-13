"""Reading of the JSON configuration file shared by the gateway and the client."""
import json

DEFAULT_CONFIG = "config.json"


def load_settings(path, section):
    """Return one section ("pasarela" or "cliente") of the configuration file as a dict."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)[section]
