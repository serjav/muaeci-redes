import logging

from modbus_tcp import (ModbusTCP, ExceptionModbus, ErrorConexion,
                        read_discrete_inputs, read_holding_register)

logging.basicConfig(level=logging.INFO)

HOST = "127.0.0.1"
PORT = 5020
DEAD_PORT = 5999     # nothing should be listening here


def attempt(label, func):
    """Run func and report which exception (if any) it raised."""
    try:
        result = func()
        print(f"[{label}] OK, no exception: {result}")
    except ExceptionModbus as e:
        print(f"[{label}] ExceptionModbus -> function=0x{e.function:02X} "
              f"code={e.code} ({e.description})")
    except ErrorConexion as e:
        print(f"[{label}] ErrorConexion -> {e}")


def main():
    # 1) and 2): the server replies, but with a Modbus exception.
    #    The connection stays usable afterwards, so we reuse the same client.
    client = ModbusTCP(HOST, PORT)
    client.connect()
    try:
        attempt("address 10000", lambda: read_holding_register(client, init_addr=10000, qty=1))
        attempt("disabled function (discrete inputs)", lambda: read_discrete_inputs(client, init_addr=0, qty=5))
    finally:
        client.close()

    # 3) nobody answers: connect() must raise ErrorConexion
    attempt("port without reply", lambda: ModbusTCP(HOST, DEAD_PORT).connect())


if __name__ == "__main__":
    main()
