import argparse
import socket
import struct
import time

from UR3e_rg2.dynamic_ur3e import UR3eRG2

DEFAULT_HOST = "192.168.1.157"
PORT = 30003
RECV_SIZE = 65536  # large enough to drain any backlog in one read
TIMEOUT = 2.0  # seconds without data before the connection is considered lost
RECONNECT_DELAY = 1.0  # seconds to wait before reconnecting

MSG_LEN = struct.Struct(">i")
Q_ACTUAL = struct.Struct(">6d")
Q_ACTUAL_OFFSET = 252  # after length, time, q_target, qd_target, qdd_target, I_target, M_target
MIN_MSG_LEN = Q_ACTUAL_OFFSET + Q_ACTUAL.size


def stream_joints(host: str, robot: UR3eRG2) -> None:
    """Move the robot with the joint positions received until the connection ends."""
    buffer = bytearray()
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
        print(f"Connected to {host}:{PORT}")
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


def main():
    parser = argparse.ArgumentParser(description="UR3e real-time port client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="robot IP address")
    args = parser.parse_args()

    robot = UR3eRG2()
    try:
        while True:
            try:
                stream_joints(args.host, robot)
                print("Connection closed by the robot")
            except OSError as error:
                print(f"Connection error: {error}")
            print(f"Reconnecting in {RECONNECT_DELAY} s...")
            time.sleep(RECONNECT_DELAY)
    except KeyboardInterrupt:
        print("Stopped by user")


if __name__ == "__main__":
    main()
