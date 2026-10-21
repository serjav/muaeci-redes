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
PORT = 30003
RECV_SIZE = 65536  # large enough to drain any backlog in one read
TIMEOUT = 2.0  # seconds without data before the connection is considered lost
RECONNECT_DELAY = 1.0  # seconds to wait before reconnecting

MSG_LEN = struct.Struct(">i")
Q_ACTUAL = struct.Struct(">6d")
Q_ACTUAL_OFFSET = 252  # after length, time, q_target, qd_target, qdd_target, I_target, M_target
MIN_MSG_LEN = Q_ACTUAL_OFFSET + Q_ACTUAL.size
MAX_MSG_LEN = 4096  # real-time messages are ~1.1 KB, anything larger is corrupt
SPAWN_SPACING = 0.8  # meters between additional robots in the simulator

Mover = Callable[[list[float]], None]  # moves one simulated robot to the given joints


def stream_joints(client: socket.socket, move: Mover, stop: threading.Event) -> None:
    """Move the robot with the joint positions received until the connection ends."""
    buffer = bytearray()
    while not stop.is_set() and (data := client.recv(RECV_SIZE)):
        buffer.extend(data)
        joints = None
        while len(buffer) >= MSG_LEN.size:
            (msg_len,) = MSG_LEN.unpack_from(buffer)
            if not MIN_MSG_LEN <= msg_len <= MAX_MSG_LEN:
                raise ValueError(f"Invalid message length: {msg_len}")
            if len(buffer) < msg_len:
                break
            joints = Q_ACTUAL.unpack_from(buffer, Q_ACTUAL_OFFSET)
            del buffer[:msg_len]
        # Only the newest message is applied so a slow move_robot never lags behind.
        if joints is not None:
            move(list(joints))


def run_robot(host: str, move: Mover, stop: threading.Event) -> None:
    """Keep one robot connected, reconnecting after errors, until stop is set."""
    has_connected = False  # the robot was reached at least once
    is_down = False  # the current outage was already reported
    while not stop.is_set():
        reached = False
        try:
            with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
                reached = True
                logging.info("Robot %s %s", host, "reconnected" if has_connected else "connected")
                has_connected, is_down = True, False
                stream_joints(client, move, stop)
                reason = "connection closed by the robot"
        except OSError as error:
            reason = error
        except ValueError as error:
            logging.error("%s. Stopping robot %s", error, host)
            return
        if stop.is_set():
            return
        if reached:
            logging.warning("Robot %s disconnected: %s", host, reason)
        elif not is_down:
            logging.warning("Robot %s unreachable: %s", host, reason)
        else:
            logging.debug("Robot %s still unreachable: %s", host, reason)
        is_down = True
        stop.wait(RECONNECT_DELAY)


def make_mover(simulator: UR3eRG2, robot_id: int, lock: threading.Lock) -> Mover:
    """Return a function that moves one robot of the shared simulator, one thread at a time."""
    def move(joints: list[float]) -> None:
        with lock:
            simulator.move_robot(robot_id, joints)
    return move


def main():
    parser = argparse.ArgumentParser(description="UR3e real-time port client")
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
