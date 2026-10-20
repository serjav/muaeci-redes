import argparse
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable

from UR3e_rg2.dynamic_ur3e import UR3eRG2

# TODO: always ask for the robot IP before starting any robot instead of relying on this default.
DEFAULT_HOST = "10.172.18.80"
PORT = 30001
RECV_SIZE = 65536  # large enough to drain any backlog in one read
TIMEOUT = 2.0  # seconds without data before the connection is considered lost
RECONNECT_DELAY = 1.0  # seconds to wait before reconnecting

HEADER = struct.Struct(">iB")  # length (int32) + type (uint8)
JOINT_RECORD = struct.Struct(">dddffffB")  # one joint in the Joint Data sub-package
ROBOT_STATE = 16
JOINT_DATA = 1
MAX_MSG_LEN = 2**20  # 1 MiB; primary messages vary in size, anything larger is corrupt
SPAWN_SPACING = 0.8  # meters between additional robots in the simulator

Mover = Callable[[list[float]], None]  # moves one simulated robot to the given joints


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


def stream_joints(host: str, move: Mover, stop: threading.Event) -> None:
    """Move the robot with the joint positions received until the connection ends."""
    buffer = bytearray()
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
        logging.info("Connected to %s:%d", host, PORT)
        while not stop.is_set() and (data := client.recv(RECV_SIZE)):
            buffer.extend(data)
            joints = None
            while len(buffer) >= HEADER.size:
                msg_len, msg_type = HEADER.unpack_from(buffer)
                if not HEADER.size <= msg_len <= MAX_MSG_LEN:
                    raise ValueError(f"Invalid message length: {msg_len}")
                if len(buffer) < msg_len:
                    break
                body = bytes(buffer[HEADER.size:msg_len])
                del buffer[:msg_len]
                if msg_type == ROBOT_STATE:
                    joints = parse_joint_positions(body) or joints
            # Only the newest message is applied so a slow move_robot never lags behind.
            if joints is not None:
                logging.debug("Joint positions: %s", joints)
                move(joints)
        if not stop.is_set():
            logging.warning("Connection closed by the robot")


def run_robot(host: str, move: Mover, stop: threading.Event) -> None:
    """Keep one robot connected, reconnecting after errors, until stop is set."""
    while not stop.is_set():
        try:
            stream_joints(host, move, stop)
        except OSError as error:
            logging.warning("Connection error: %s", error)
        except ValueError as error:
            logging.error("%s. Stopping this robot", error)
            return
        if not stop.wait(RECONNECT_DELAY):
            logging.info("Reconnecting...")


def make_mover(simulator: UR3eRG2, robot_id: int, lock: threading.Lock) -> Mover:
    """Return a function that moves one robot of the shared simulator, one thread at a time."""
    def move(joints: list[float]) -> None:
        with lock:
            simulator.move_robot(robot_id, joints)
    return move


def main():
    parser = argparse.ArgumentParser(description="UR3e primary port client")
    parser.add_argument(
        "--hosts", nargs="+", default=[DEFAULT_HOST], metavar="HOST", help="robot IP addresses"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")

    stop = threading.Event()
    simulator = UR3eRG2()
    simulator_lock = threading.Lock()
    hosts = dict.fromkeys(args.hosts)  # drop duplicate IPs, keep order
    threads = []
    for index, host in enumerate(hosts):
        if index == 0:
            robot_id = 0
        else:
            robot_id = simulator.spawn_robot(
                [index * SPAWN_SPACING, 0, 0, 0, 0, 0]
            )
        logging.info("Robot %s controls simulator body %d", host, robot_id)
        threads.append(
            threading.Thread(
                target=run_robot,
                args=(host, make_mover(simulator, robot_id, simulator_lock), stop),
                name=host,
            )
        )
    for thread in threads:
        thread.start()
    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        logging.info("Stopped by user")
        stop.set()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
