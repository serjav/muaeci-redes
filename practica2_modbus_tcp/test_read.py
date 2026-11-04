import logging

from modbus_tcp import (ModbusTCP, read_coils, read_discrete_inputs,
                        read_holding_register, read_input_registers, write_coil,
                        read_write_multiple_registries, write_multiple_coils,
                        write_multiple_registries, write_registry)

logging.basicConfig(level=logging.INFO)

HOST = "127.0.0.1"
PORT = 5020


def main():
    client = ModbusTCP(HOST, PORT)
    client.connect()
    try:
        values = read_holding_register(client, init_addr=107, qty=4, transaction_id=1)
        print("Holding registers 107-110 (tid 1):", values)

        values = read_input_registers(client, init_addr=22, qty=8, transaction_id=2)
        print("Input registers 22-29 (tid 2):", values)

        # No transaction_id given: the client generates it (1, then 2, ...)
        values = read_holding_register(client, init_addr=107, qty=4)
        print("Holding registers 107-110 (auto tid):", values)

        # 10 coils -> the server answers with 2 bytes (last 6 bits are padding)
        values = read_coils(client, init_addr=0, qty=10)
        print("Coils 0-9:", values)

        # 5 discrete inputs -> the server answers with 1 byte (last 3 bits are padding)
        values = read_discrete_inputs(client, init_addr=0, qty=5)
        print("Discrete inputs 0-4:", values)

        # Write a negative value, then read it back. The read functions decode
        # registers as unsigned, so -5 should come back as 65531 (0xFFFB).
        echoed = write_registry(client, init_addr=107, value=-5)
        print("Wrote to register 107, echo:", echoed)
        values = read_holding_register(client, init_addr=107, qty=1)
        print("Read back register 107:", values)

        # Turn coil 3 ON (sent as FF 00), then read it back
        echoed = write_coil(client, init_addr=3, value=True)
        print("Wrote coil 3 ON, echo:", echoed)
        values = read_coils(client, init_addr=3, qty=1)
        print("Read back coil 3:", values)

        # Write 4 registers starting at 200 (one is negative), then read them back
        qty = write_multiple_registries(client, init_addr=200, values=[10, 20, -30, 40])
        print("Wrote registers 200-203, echoed qty:", qty)
        values = read_holding_register(client, init_addr=200, qty=4)
        print("Read back registers 200-203:", values)

        # Write 10 coils starting at 20 (spans 2 bytes: 0x0D then 0x03), read them back
        coils = [True, False, True, True, False, False, False, False, True, True]
        qty = write_multiple_coils(client, init_addr=20, values=coils)
        print("Wrote coils 20-29, echoed qty:", qty)
        values = read_coils(client, init_addr=20, qty=10)
        print("Read back coils 20-29:", values)
        print("Match:", values == coils)

        # Write 3 registers at 300 and read the same 3 in ONE request. The server
        # writes first, then reads, so we get the new values back (-333 -> 65203).
        values = read_write_multiple_registries(client, read_addr=300, read_qty=3,
                                                write_addr=300, write_values=[111, 222, -333])
        print("Read/write registers 300-302:", values)
    finally:
        client.close()   # always close, even if the read raised an error


if __name__ == "__main__":
    main()
