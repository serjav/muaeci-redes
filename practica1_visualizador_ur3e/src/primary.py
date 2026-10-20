import socket
import struct

from UR3e_rg2.dynamic_ur3e import UR3eRG2

HOST = "192.168.1.157"
PORT = 30001
RECV_SIZE = 65536  # large enough to drain any backlog in one read

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


def main():
    robot = UR3eRG2()
    buffer = bytearray()
    with socket.create_connection((HOST, PORT)) as client:
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


if __name__ == "__main__":
    main()
