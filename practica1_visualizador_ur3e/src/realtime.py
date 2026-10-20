import socket
import struct

from UR3e_rg2.dynamic_ur3e import UR3eRG2

HOST = "192.168.1.157"
PORT = 30003
RECV_SIZE = 65536  # large enough to drain any backlog in one read

MSG_LEN = struct.Struct(">i")
Q_ACTUAL = struct.Struct(">6d")
Q_ACTUAL_OFFSET = 252  # after length, time, q_target, qd_target, qdd_target, I_target, M_target
MIN_MSG_LEN = Q_ACTUAL_OFFSET + Q_ACTUAL.size


def main():
    robot = UR3eRG2()
    buffer = bytearray()
    with socket.create_connection((HOST, PORT)) as client:
        while data := client.recv(RECV_SIZE):
            buffer.extend(data)
            joints = None
            while len(buffer) >= MSG_LEN.size:
                (msg_len,) = MSG_LEN.unpack_from(buffer)
                if msg_len < MIN_MSG_LEN:
                    raise ValueError(f"Invalid message length: {msg_len}")
                if len(buffer) < msg_len:
                    break
                joints = Q_ACTUAL.unpack_from(buffer, Q_ACTUAL_OFFSET)
                del buffer[:msg_len]
            # Only the newest message is applied so a slow move_robot never lags behind.
            if joints is not None:
                robot.move_robot(0, list(joints))


if __name__ == "__main__":
    main()
