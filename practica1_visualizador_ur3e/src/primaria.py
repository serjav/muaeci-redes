import argparse
import socket
import struct
import time

from UR3e_rg2.dynamic_ur3e import UR3eRG2

DEFAULT_HOST = "192.168.1.157"
PORT = 30001
RECV_SIZE = 65536  # large enough to drain any backlog in one read
TIMEOUT = 2.0  # seconds without data before the connection is considered lost
RECONNECT_DELAY = 1.0  # seconds to wait before reconnecting

HEADER = struct.Struct(">iB")  # length (int32) + type (uint8)
JOINT_RECORD = struct.Struct(">dddffffB")  # one joint in the Joint Data sub-package
ROBOT_STATE = 16
JOINT_DATA = 1


def parse_joint_positions(robot_state: bytes) -> list[float] | None:
    """Return q_actual of each joint from a Robot State body, or None if absent."""
    offset = 0
    while offset + HEADER.size <= len(robot_state):
        sub_len, sub_type = HEADER.unpack_from(robot_state, offset)
        end = offset + sub_len
        if sub_len < HEADER.size or end > len(robot_state):
            return None
        if sub_type == JOINT_DATA:
            records = robot_state[offset + HEADER.size:end]
            return [joint[0] for joint in JOINT_RECORD.iter_unpack(records)]
        offset = end
    return None


def stream_joints(host: str, robot: UR3eRG2) -> None:
    """Move the robot with the joint positions received until the connection ends."""
    buffer = bytearray()
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
        print(f"Connected to {host}:{PORT}")
        while data := client.recv(RECV_SIZE):
            buffer.extend(data)
            joints = None
            while len(buffer) >= HEADER.size:
                msg_len, msg_type = HEADER.unpack_from(buffer)
                if msg_len < HEADER.size:
                    raise ValueError(f"Invalid message length: {msg_len}")
                if len(buffer) < msg_len:
                    break
                body = bytes(buffer[HEADER.size:msg_len])
                del buffer[:msg_len]
                if msg_type == ROBOT_STATE:
                    joints = parse_joint_positions(body) or joints
            # Only the newest message is applied so a slow move_robot never lags behind.
            if joints is not None:
                print(f"Joint positions: {joints}")
                robot.move_robot(0, joints)


def main():
    parser = argparse.ArgumentParser(description="UR3e primary port client")
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
