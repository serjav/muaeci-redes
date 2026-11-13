"""Echo server for Phase 3: it sends back whatever it receives, in place of the robot."""
import argparse
import socket
import threading

from configuracion import DEFAULT_CONFIG, load_settings

RECV_SIZE = 4096


class ServidorEco:
    def __init__(self, ip, port):
        self.address = (ip, port)

    def serve(self):
        """Accept connections until Ctrl+C. Each one is answered in its own thread."""
        with socket.create_server(self.address) as server:
            print(f"Servidor de eco escuchando en {self.address[0]}:{self.address[1]} (Ctrl+C para parar)")
            try:
                while True:
                    connection, address = server.accept()
                    # daemon: these threads end with the program, there is nothing to close in order
                    threading.Thread(target=self.echo, args=(connection, address), daemon=True).start()
            except KeyboardInterrupt:
                print("\nServidor de eco detenido")

    def echo(self, connection, address):
        """Send back every block of bytes until the other end closes."""
        print(f"Conexión de {address[0]}:{address[1]}")
        with connection:
            try:
                while data := connection.recv(RECV_SIZE):
                    connection.sendall(data)
            except OSError as error:
                print(f"Conexión de {address[0]}:{address[1]} perdida: {error}")
        print(f"Conexión de {address[0]}:{address[1]} cerrada")


def run_echo_server(config_path):
    """Start the echo server on the destination that the gateway has configured."""
    try:
        settings = load_settings(config_path, "pasarela")
        server = ServidorEco(settings["ip_destino"], settings["puerto_destino"])
        server.serve()
    except (OSError, ValueError, KeyError) as error:
        print(f"No se puede arrancar el servidor de eco: {error!r}")


def main():
    parser = argparse.ArgumentParser(description="Servidor de eco para probar la pasarela")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="fichero de configuración")
    args = parser.parse_args()
    run_echo_server(args.config)


if __name__ == "__main__":
    main()
