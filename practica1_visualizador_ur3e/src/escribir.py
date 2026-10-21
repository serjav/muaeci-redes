import socket
import struct
import time

ROBOT_IP = "10.172.18.80"
ROBOT_PORT = 30001

ROBOT_STATE_TYPE = 16
ROBOT_MESSAGE_TYPE = 20
ROBOT_MESSAGE_TYPE_ERROR_CODE = 6

ROBOT_STATE_HEADER = struct.Struct(">iB")
JOINT_RECORD = struct.Struct(">dddffffB")
JOINT_DATA = 1
JOINT_TOLERANCE = 0.01


def receive_exact(connection, size):
    data = bytearray()

    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("El robot cerró la conexión.")
        data.extend(chunk)

    return bytes(data)


def receive_packet(connection):
    header = receive_exact(connection, 4)
    packet_length = struct.unpack(">I", header)[0]

    if packet_length < 5:
        raise ValueError(f"Tamaño de paquete no válido: {packet_length}")

    packet = receive_exact(connection, packet_length - 4)
    return packet[0], packet[1:]


def parse_robot_mode_data(payload):
    # Layout: uint32 packageSize, uint8 packageType, uint64 timestamp, 7 bools, ...
    if len(payload) < 20:
        return None

    package_size = struct.unpack_from(">I", payload, 0)[0]
    package_type = payload[4]

    if package_type != 0 or package_size < 20 or package_size > len(payload):
        return None

    timestamp = struct.unpack_from(">Q", payload, 5)[0]
    signal_names = (
        "isRealRobotConnected",
        "isRealRobotEnabled",
        "isRobotPowerOn",
        "isEmergencyStopped",
        "isProtectiveStopped",
        "isProgramRunning",
        "isProgramPaused",
    )
    signals = dict(zip(signal_names, (bool(value) for value in payload[13:20])))

    return timestamp, signals


def handle_robot_message_20(payload):
    # receive_packet() has already removed messageSize and the outer type (20).
    # The remaining payload starts with timestamp.
    print("\n" + "=" * 60)
    print("ROBOT MESSAGE (20) — startup failure details")

    if len(payload) < 18:
        print(f"Mensaje tipo 20 incompleto ({len(payload)} bytes).")
        return

    timestamp = struct.unpack_from(">Q", payload, 0)[0]
    source = payload[8:9].decode("ascii", errors="replace")
    robot_message_type = payload[9]
    robot_message_code, robot_message_argument = struct.unpack_from(">ii", payload, 10)

    print(f"timestamp: {timestamp}")
    print(f"source: {source}")
    print(f"robotMessageType: {robot_message_type}")
    print(f"robotMessageCode: {robot_message_code}")
    print(f"robotMessageArgument: {robot_message_argument}")

    if robot_message_type == ROBOT_MESSAGE_TYPE_ERROR_CODE:
        if len(payload) < 30:
            print(f"Mensaje de error incompleto ({len(payload)} bytes).")
            return

        robot_message_report_level = struct.unpack_from(">i", payload, 18)[0]
        robot_message_data_type = struct.unpack_from(">I", payload, 22)[0]
        robot_message_data = struct.unpack_from(">I", payload, 26)[0]
        text_bytes = payload[30:].split(b"\0", 1)[0]
        robot_comm_text_message = text_bytes.decode("utf-8", errors="replace")

        print(f"robotMessageReportLevel: {robot_message_report_level}")
        print(f"robotMessageDataType: {robot_message_data_type}")
        print(f"robotMessageData: {robot_message_data}")
        print(f"robotCommTextMessage: {robot_comm_text_message}")


def report_startup_failure(robot_messages, startup_timeout):
    print(
        "\nADVERTENCIA: isProgramRunning no cambió a 1 "
        f"en {startup_timeout:.1f} segundos."
    )

    if robot_messages:
        for payload in robot_messages:
            handle_robot_message_20(payload)
    else:
        print("No se recibieron mensajes tipo 20 para analizar.")


def monitor_robot_stream(connection, requested_joints, startup_timeout=2.0):
    print("Leyendo mensajes del robot. Pulsa Ctrl+C para salir.")

    deadline = time.monotonic() + startup_timeout
    program_running_seen = False
    latest_joint_positions = None
    startup_robot_messages = []

    while True:
        if program_running_seen:
            connection.settimeout(None)
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                report_startup_failure(startup_robot_messages, startup_timeout)
                return
            connection.settimeout(remaining)

        try:
            message_type, payload = receive_packet(connection)
        except socket.timeout:
            report_startup_failure(startup_robot_messages, startup_timeout)
            return

        if message_type == ROBOT_STATE_TYPE:
            mode_data, joint_positions = parse_robot_state(payload)

            if joint_positions is not None:
                latest_joint_positions = joint_positions

            if mode_data is not None:
                _, signals = mode_data

                if signals["isProgramRunning"]:
                    program_running_seen = True
                elif program_running_seen:
                    print("\nMovimiento completado; verificando posiciones:")
                    verify_joint_positions(requested_joints, latest_joint_positions)
                    return
            else:
                print("\n" + "=" * 60)
                print(f"ROBOT_STATE: {payload.hex()}")

        elif message_type == ROBOT_MESSAGE_TYPE and not program_running_seen:
            # Defer message-20 decoding unless startup fails.
            startup_robot_messages.append(payload)


def parse_robot_state(payload):
    """Extract RobotModeData and q_actual joint angles from a Robot State body."""
    offset = 0
    mode_data = None
    joint_positions = None

    while offset + ROBOT_STATE_HEADER.size <= len(payload):
        package_size, package_type = ROBOT_STATE_HEADER.unpack_from(payload, offset)
        package_end = offset + package_size

        if package_size < ROBOT_STATE_HEADER.size or package_end > len(payload):
            break

        if package_type == 0 and package_size >= 20:
            timestamp = struct.unpack_from(">Q", payload, offset + 5)[0]
            signal_names = (
                "isRealRobotConnected",
                "isRealRobotEnabled",
                "isRobotPowerOn",
                "isEmergencyStopped",
                "isProtectiveStopped",
                "isProgramRunning",
                "isProgramPaused",
            )
            signal_bytes = payload[offset + 13:offset + 20]
            signals = dict(zip(signal_names, (bool(value) for value in signal_bytes)))
            mode_data = timestamp, signals

        elif package_type == JOINT_DATA:
            records = payload[offset + ROBOT_STATE_HEADER.size:package_end]
            if len(records) % JOINT_RECORD.size == 0:
                # joint[0] is q_actual, in radians, as in primaria.py.
                joint_positions = [
                    joint[0] for joint in JOINT_RECORD.iter_unpack(records)
                ]

        offset = package_end

    return mode_data, joint_positions


def verify_joint_positions(requested, received):
    if received is None:
        print("ERROR: No se recibieron posiciones articulares para verificar.")
        return

    if len(requested) != len(received):
        print(
            f"ERROR: Se esperaban {len(requested)} articulaciones, "
            f"pero se recibieron {len(received)}. "
        )
        return

    variances = [abs(actual - target) for target, actual in zip(requested, received)]

    for index, (target, actual, variance) in enumerate(
        zip(requested, received, variances), start=1
    ):
        print(
            f"Joint {index}: requested={target:.6f} rad, "
            f"received={actual:.6f} rad, variance={variance:.6f} rad"
        )

    if all(variance < JOINT_TOLERANCE for variance in variances):
        print("CONFIRMED: All joint positions are within 0.01 rad of the target.")
    else:
        print("ERROR: Joint positions differ from the target by 0.01 rad or more.")


def main():
    connection = None

    try:
        connection = socket.create_connection((ROBOT_IP, ROBOT_PORT))
        print("Conexión establecida con el servidor del robot.")

        requested_joints = [0.0, -1.5, 0.0, -1.5, 0.0, 0.0]

        with connection:
            message_test = (
                "def secuencia():\n"
                "movejjj([0.0, -1, 0.0, -1, 0.0, 0.0], a=0.5, v=0.3)\n"
                "movej([0.0, -1.5, 0.0, -1.5, 0.0, 0.0], a=0.5, v=0.3)\n"
                "end\n"
                "secuencia()\n"
            )
            # abort_message = "abort"
            message_encoded = message_test.encode("utf-8")
            connection.sendall(message_encoded)
            print("Mensaje de prueba enviado al robot.")
            monitor_robot_stream(connection, requested_joints)
    except KeyboardInterrupt:
        print("\nLectura detenida por el usuario.")
    except OSError as error:
        print(f"Error de conexión con el servidor del robot: {error}")
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
