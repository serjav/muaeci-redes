#!/usr/bin/env python3
"""Text menu to run every program of the practice from one place.

Usage:
    ./menu.py                      uses config.json in the current folder
    ./menu.py --config other.json  uses another configuration file
    ./menu.py --traza              the gateway also logs every block forwarded
    ./menu.py --help               explains every option of the menu
"""
import argparse
import logging

from cliente_seguro import TARGET_JOINTS, ErrorCliente, create_client, show_move, show_read
from configuracion import DEFAULT_CONFIG
from pasarela import run_gateway
from servidor_eco import run_echo_server

MAIN_MENU = """
===== Práctica 3 · Pasarela TLS para el UR3e =====
 1. Arrancar la pasarela
 2. Arrancar el servidor de eco (pruebas de la Fase 3)
 3. Cliente a través de la pasarela (TLS)
 4. Cliente directo al robot (sin TLS)
 0. Salir"""

CLIENT_MENU = """
----- Cliente ({mode}) -----
 1. Leer la posición articular
 2. Mover el robot y verificar la posición
 0. Volver"""

HELP_DESCRIPTION = """\
Menú de texto de la práctica 3: pasarela TLS para el robot UR3e.

Se elige una opción escribiendo su número y pulsando Enter:
  1  Arrancar la pasarela. Pide la contraseña de pasarela.key (no se muestra).
     Ctrl+C la detiene de forma ordenada y vuelve al menú.
  2  Arrancar el servidor de eco, que sustituye al robot en las pruebas.
     Escucha en ip_destino:puerto_destino. Ctrl+C lo detiene.
  3  Cliente a través de la pasarela, con TLS. Pide la contraseña de la
     clave del cliente y abre el submenú del cliente.
  4  Cliente directo al robot, sin TLS ni contraseña, para comparar.
  0  Salir.

Submenú del cliente (opciones 3 y 4):
  1  Leer la posición articular del robot.
  2  Mover el robot y verificar la posición. Pide confirmación con "s" (sí);
     cualquier otra respuesta cancela. EL ROBOT SE MUEVE.
  0  Volver al menú principal.
"""

HELP_STEPS = """\
antes de usarlo:
  1. Crear los certificados:        ./crear_pki.sh <numero_estudiante> <ip_pasarela>
  2. Crear la configuración:        cp config_ejemplo.json config.json
  3. Editar config.json con las IP, los puertos y las rutas de los certificados.

ejemplos:
  ./menu.py                         usa config.json de la carpeta actual
  ./menu.py --config cliente.json   usa otro fichero de configuración
  ./menu.py --traza                 la pasarela muestra cada bloque que reenvía

La pasarela, el servidor de eco y el cliente son programas distintos: abre un
terminal (o una máquina) para cada uno y ejecuta el menú en cada terminal.
Se ejecuta desde la carpeta practica3_tls/. Más detalles en README.md.
"""


class Menu:
    def __init__(self, config_path, trace=False):
        self.config_path = config_path
        self.trace = trace  # the gateway also logs every block of bytes forwarded

    def run(self):
        """Show the main menu until the user leaves."""
        while True:
            print(MAIN_MENU)
            option = input("Opción: ").strip()
            if option == "1":
                run_gateway(self.config_path, self.trace)
            elif option == "2":
                run_echo_server(self.config_path)
            elif option == "3":
                self.client_menu(direct=False)
            elif option == "4":
                self.client_menu(direct=True)
            elif option == "0":
                return
            else:
                print("Opción no válida")

    def client_menu(self, direct):
        """Build the client (asks for the key password once) and show its operations."""
        logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
        try:
            client = create_client(self.config_path, direct)
        except ErrorCliente as error:
            print(f"ERROR: {error}")
            return
        mode = "directo, sin TLS" if direct else "a través de la pasarela"
        while True:
            print(CLIENT_MENU.format(mode=mode))
            option = input("Opción: ").strip()
            if option == "0":
                return
            try:
                if option == "1":
                    show_read(client)
                elif option == "2":
                    self.confirm_and_move(client)
                else:
                    print("Opción no válida")
            except ErrorCliente as error:
                print(f"ERROR: {error}")

    def confirm_and_move(self, client):
        """Ask before moving: the real robot moves."""
        print(f"El robot se va a MOVER a {TARGET_JOINTS} rad.")
        if input("¿Continuar? (s/n): ").strip().lower() == "s":
            show_move(client)
        else:
            print("Movimiento cancelado")


def main():
    parser = argparse.ArgumentParser(
        prog="menu.py", description=HELP_DESCRIPTION, epilog=HELP_STEPS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, metavar="FICHERO",
                        help=f"fichero de configuración (por defecto {DEFAULT_CONFIG})")
    parser.add_argument("--traza", action="store_true",
                        help="la pasarela registra también cada bloque de bytes reenviado")
    args = parser.parse_args()
    try:
        Menu(args.config, args.traza).run()
    except (KeyboardInterrupt, EOFError):
        print("\nSaliendo")


if __name__ == "__main__":
    main()
