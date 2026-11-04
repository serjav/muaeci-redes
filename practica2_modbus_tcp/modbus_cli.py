import argparse
import logging
import math
import sys

from modbus_tcp import (ModbusTCP, ExceptionModbus, ErrorConexion, ErrorTimeout,
                        ErrorProtocolo, ReadWriteMultipleRegistries,
                        WriteMultipleCoils, WriteMultipleRegistries,
                        read_coils, read_discrete_inputs, read_holding_register,
                        read_input_registers, read_write_multiple_registries,
                        write_coil, write_multiple_coils,
                        write_multiple_registries, write_registry)

# Exit codes (from the output table)
EXIT_OK = 0
EXIT_ARGUMENTO = 2
EXIT_EXCEPCION = 3
EXIT_TIMEOUT = 4
EXIT_CONEXION = 5
EXIT_PROTOCOLO = 6

# command name -> library function
READ_BITS = {"leer-coils": read_coils, "leer-entradas": read_discrete_inputs}
READ_REGS = {"leer-holding": read_holding_register, "leer-input": read_input_registers}

MAX_READ_BITS = 2000
MAX_READ_REGS = 125


class ArgParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse calls this for every bad argument; use the required format and code
        print(f"ARGUMENTO INVALIDO: {message}")
        sys.exit(EXIT_ARGUMENTO)


def ranged(lo, hi):
    """Build an argparse 'type' that accepts an integer between lo and hi (inclusive)."""
    def check(text):
        try:
            n = int(text, 0)         # base 0: accepts 10, 0x0A, 0b1010
        except ValueError:
            raise argparse.ArgumentTypeError(f"'{text}' no es un entero")
        if not lo <= n <= hi:
            raise argparse.ArgumentTypeError(f"{n} fuera de rango ({lo} a {hi})")
        return n
    return check


def positive_float(text):
    try:
        n = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' no es un numero")
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError(f"{text} debe ser un numero mayor que 0")
    return n


ADDRESS = ranged(0, 0xFFFF)
SIGNED16 = ranged(-32768, 32767)
BIT = ranged(0, 1)


def build_parser():
    parser = ArgParser(prog="modbus_cli.py", description="Cliente Modbus TCP")
    # Global options, in the order requested
    parser.add_argument("--ip", default="127.0.0.1", metavar="IP",
                        help="direccion del servidor (por defecto 127.0.0.1)")
    parser.add_argument("--puerto", type=ranged(1, 65535), default=502, metavar="P",
                        help="puerto TCP (por defecto 502)")
    parser.add_argument("--unidad", type=ranged(0, 255), default=0xFF, metavar="U",
                        help="unit id (por defecto 255)")
    parser.add_argument("--timeout", type=positive_float, default=3.0, metavar="S",
                        help="timeout en segundos (por defecto 3)")
    parser.add_argument("--traza", action="store_true",
                        help="muestra las tramas enviadas y recibidas (por stderr)")

    sub = parser.add_subparsers(dest="comando", required=True, metavar="COMANDO")

    for name in READ_BITS:
        p = sub.add_parser(name, help="leer bits")
        p.add_argument("direccion", type=ADDRESS)
        p.add_argument("cantidad", type=ranged(1, MAX_READ_BITS))

    for name in READ_REGS:
        p = sub.add_parser(name, help="leer registros")
        p.add_argument("direccion", type=ADDRESS)
        p.add_argument("cantidad", type=ranged(1, MAX_READ_REGS))

    p = sub.add_parser("escribir-coil", help="escribir un coil (0 o 1)")
    p.add_argument("direccion", type=ADDRESS)
    p.add_argument("valor", type=BIT)

    p = sub.add_parser("escribir-registro", help="escribir un registro (con signo)")
    p.add_argument("direccion", type=ADDRESS)
    p.add_argument("valor", type=SIGNED16)

    p = sub.add_parser("escribir-coils", help="escribir varios coils (0 o 1)")
    p.add_argument("direccion", type=ADDRESS)
    p.add_argument("valores", type=BIT, nargs="+")

    p = sub.add_parser("escribir-registros", help="escribir varios registros (con signo)")
    p.add_argument("direccion", type=ADDRESS)
    p.add_argument("valores", type=SIGNED16, nargs="+")

    p = sub.add_parser("leer-escribir", help="escribir y leer registros en una peticion")
    p.add_argument("dir_lectura", type=ADDRESS)
    p.add_argument("cantidad", type=ranged(1, MAX_READ_REGS))
    p.add_argument("dir_escritura", type=ADDRESS)
    p.add_argument("valores", type=SIGNED16, nargs="+")

    return parser


def check_span(parser, start, count, what):
    # The last address touched must still fit in 16 bits
    if start + count - 1 > 0xFFFF:
        parser.error(f"{what}: direccion {start} + cantidad {count} supera 65535")


def check_count(parser, count, maximum, what):
    if count > maximum:
        parser.error(f"{what}: {count} valores, el maximo es {maximum}")


def validate(parser, args):
    """Checks that need more than one argument. Runs BEFORE connecting."""
    cmd = args.comando
    if cmd in READ_BITS or cmd in READ_REGS:
        check_span(parser, args.direccion, args.cantidad, "lectura")
    elif cmd == "escribir-coils":
        check_count(parser, len(args.valores), WriteMultipleCoils.MAX_QTY, "escritura")
        check_span(parser, args.direccion, len(args.valores), "escritura")
    elif cmd == "escribir-registros":
        check_count(parser, len(args.valores), WriteMultipleRegistries.MAX_QTY, "escritura")
        check_span(parser, args.direccion, len(args.valores), "escritura")
    elif cmd == "leer-escribir":
        check_count(parser, len(args.valores),
                    ReadWriteMultipleRegistries.MAX_WRITE_QTY, "escritura")
        check_span(parser, args.dir_lectura, args.cantidad, "lectura")
        check_span(parser, args.dir_escritura, len(args.valores), "escritura")


def print_bits(start, bits):
    for i, bit in enumerate(bits):
        print(f"{start + i} {int(bit)}")


def print_registers(start, registers):
    for i, value in enumerate(registers):
        signed = value - 0x10000 if value >= 0x8000 else value   # two's complement
        print(f"{start + i} {value} {signed} 0x{value:04X}")


def run(args):
    client = ModbusTCP(args.ip, args.puerto, args.timeout, unit_id=args.unidad)
    client.connect()
    try:
        cmd = args.comando
        if cmd in READ_BITS:
            print_bits(args.direccion, READ_BITS[cmd](client, args.direccion, args.cantidad))
        elif cmd in READ_REGS:
            print_registers(args.direccion, READ_REGS[cmd](client, args.direccion, args.cantidad))
        elif cmd == "escribir-coil":
            write_coil(client, args.direccion, args.valor)
            print("OK")
        elif cmd == "escribir-registro":
            write_registry(client, args.direccion, args.valor)
            print("OK")
        elif cmd == "escribir-coils":
            write_multiple_coils(client, args.direccion, args.valores)
            print("OK")
        elif cmd == "escribir-registros":
            write_multiple_registries(client, args.direccion, args.valores)
            print("OK")
        elif cmd == "leer-escribir":
            registers = read_write_multiple_registries(
                client, args.dir_lectura, args.cantidad, args.dir_escritura, args.valores)
            print_registers(args.dir_lectura, registers)
    finally:
        client.close()      # always close, even after an error


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    validate(parser, args)

    if args.traza:
        # stderr keeps stdout clean, so the output table is not polluted
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(message)s")

    try:
        run(args)
    except ValueError as e:          # raised by the library's own range checks
        print(f"ARGUMENTO INVALIDO: {e}")
        return EXIT_ARGUMENTO
    except ExceptionModbus as e:
        print(f"EXCEPCION 0x{e.code:02X} {e.description.upper().replace(' ', '_')}")
        return EXIT_EXCEPCION
    except ErrorTimeout:             # must come before ErrorConexion (it is a subclass)
        print("TIMEOUT")
        return EXIT_TIMEOUT
    except ErrorConexion as e:
        print(f"ERROR DE CONEXION: {e}")
        return EXIT_CONEXION
    except ErrorProtocolo as e:
        print(f"ERROR DE PROTOCOLO: {e}")
        return EXIT_PROTOCOLO
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
