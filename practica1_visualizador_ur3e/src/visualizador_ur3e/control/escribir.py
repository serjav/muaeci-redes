import argparse
import logging
import socket
import sys
import time
from collections.abc import Sequence

from visualizador_ur3e.comun.ur_protocol import (
    ERROR_CODE_MESSAGE,
    KEY_MESSAGE,
    PROGRAM_STARTED,
    PROGRAM_STOPPED,
    ROBOT_MESSAGE,
    ROBOT_MESSAGE_NAMES,
    ROBOT_STATE,
    RUNTIME_EXCEPTION_MESSAGE,
    TEXT_MESSAGE,
    RobotMessage,
    extract_messages,
    parse_joint_positions,
    parse_robot_message,
    parse_robot_mode,
)

# TODO: always ask for the robot IP before starting any robot instead of relying on this default.
DEFAULT_HOST = "10.172.18.80"
PORT = 30001
RECV_SIZE = 65536  # large enough to drain any backlog in one read
TIMEOUT = 2.0  # seconds without data before the connection is considered lost
STARTUP_TIMEOUT = 2.0  # seconds for the program to start running after it is sent

# TODO: set acceleration and velocity to values within the lab safety limits.
ACCELERATION = 0.5  # rad/s^2
VELOCITY = 0.3  # rad/s
TARGET_JOINTS = [0.0, -1.5, 0.0, -1.5, 0.0, 0.0]  # rad
JOINT_TOLERANCE = 0.01  # rad
PROGRAM_NAME = "secuencia"  # the robot reports this name when the program starts and stops

ROBOT_MESSAGE_LEVELS = {  # error code messages are reported by monitor_program instead
    TEXT_MESSAGE: logging.INFO,
    RUNTIME_EXCEPTION_MESSAGE: logging.ERROR,
}


def build_program(target: Sequence[float], test_failure: bool = False) -> str:
    """Return a URScript program that moves the robot to the target joints."""
    joints = [float(joint) for joint in target]
    lines = [f"def {PROGRAM_NAME}():"]
    if test_failure:
        # Unknown function on purpose: the robot rejects the program and reports why.
        lines.append(f"  movejjj({joints}, a={ACCELERATION}, v={VELOCITY})")
    lines += [f"  movej({joints}, a={ACCELERATION}, v={VELOCITY})", "end", f"{PROGRAM_NAME}()"]
    return "\n".join(lines) + "\n"


def log_robot_message(body: bytes) -> RobotMessage | None:
    """Log a Robot Message at a level that matches its type and return it decoded."""
    message = parse_robot_message(body)
    if message is None:
        logging.warning("Malformed robot message (%d bytes)", len(body))
        return None
    level = ROBOT_MESSAGE_LEVELS.get(message.message_type, logging.DEBUG)
    name = ROBOT_MESSAGE_NAMES.get(message.message_type, f"type {message.message_type}")
    content = " ".join(part for part in (message.title, message.text) if part)
    logging.log(
        level, "Robot %s message from source %d: %s %s", name, message.source, content, message.details
    )
    return message


def is_program_event(message: RobotMessage | None, title: str) -> bool:
    """Return True if message is the given start/stop event of the program sent."""
    return (
        message is not None
        and message.message_type == KEY_MESSAGE
        and message.title == title
        and message.text == PROGRAM_NAME
    )


def verify_joint_positions(target: Sequence[float], actual: list[float] | None) -> bool:
    """Log each joint's error and return True if all are within JOINT_TOLERANCE."""
    if actual is None:
        logging.error("No joint positions received to verify")
        return False
    if len(actual) != len(target):
        logging.error("Expected %d joints but received %d", len(target), len(actual))
        return False

    errors = [abs(position - goal) for goal, position in zip(target, actual)]
    for index, (goal, position, error) in enumerate(zip(target, actual, errors), start=1):
        logging.debug(
            "Joint %d: target=%.6f rad, actual=%.6f rad, error=%.6f rad", index, goal, position, error
        )
    worst = max(range(len(errors)), key=errors.__getitem__)
    if errors[worst] < JOINT_TOLERANCE:
        logging.info(
            "Confirmed: all joints are within %.3f rad of the target (largest error %.6f rad, joint %d)",
            JOINT_TOLERANCE, errors[worst], worst + 1,
        )
        return True
    logging.error(
        "Joint positions differ from the target by %.3f rad or more. Errors: [%s] rad",
        JOINT_TOLERANCE, ", ".join(f"{error:.4f}" for error in errors),
    )
    return False


def monitor_program(client: socket.socket, target: Sequence[float], startup_timeout: float) -> bool:
    """Follow the program until it ends, then verify the final joints. Return True on success.

    Start and end come from the robot's PROGRAM_XXX_STARTED/STOPPED events, which are sent for
    every program. The 10 Hz state snapshots can miss a program shorter than 100 ms.
    """
    deadline = time.monotonic() + startup_timeout
    started = finished = False
    buffer = bytearray()
    while started or time.monotonic() < deadline:
        data = client.recv(RECV_SIZE)
        if not data:
            raise ConnectionError("Connection closed by the robot")
        buffer.extend(data)
        for msg_type, body in extract_messages(buffer):
            if msg_type == ROBOT_MESSAGE:
                message = log_robot_message(body)
                if message is not None and message.message_type == ERROR_CODE_MESSAGE:
                    # Not always a fault, so it is reported without stopping the program.
                    logging.warning(
                        "Robot error code while running %s: %s %s", PROGRAM_NAME, message.text, message.details
                    )
                if not started and is_program_event(message, PROGRAM_STARTED):
                    started = True
                    logging.info("Program %s started", PROGRAM_NAME)
                elif started and is_program_event(message, PROGRAM_STOPPED):
                    finished = True
                    logging.info("Program %s finished, verifying joint positions", PROGRAM_NAME)
                continue
            if msg_type != ROBOT_STATE:
                continue
            mode = parse_robot_mode(body)
            if mode is None:
                logging.debug("Robot state without mode data")
                continue
            if mode.emergency_stopped or mode.protective_stopped:
                stop_kind = "emergency" if mode.emergency_stopped else "protective"
                logging.error("Robot is in %s stop, program aborted", stop_kind)
                return False
            # The stop event can arrive before the final positions, so use the next state.
            if finished:
                return verify_joint_positions(target, parse_joint_positions(body))
    logging.error("Program did not start within %.1f s", startup_timeout)
    return False


def write_and_verify(
    host: str,
    target: Sequence[float],
    startup_timeout: float = STARTUP_TIMEOUT,
    test_failure: bool = False,
) -> bool:
    """Send a program that moves the robot to target and check that it got there."""
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
        logging.info("Robot %s connected", host)
        client.sendall(build_program(target, test_failure).encode("utf-8"))
        logging.info("Program sent")
        return monitor_program(client, target, startup_timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Move a UR3e to a target pose and verify it")
    parser.add_argument("--host", default=DEFAULT_HOST, help="robot IP address")
    parser.add_argument(
        "--startup-timeout", type=float, default=STARTUP_TIMEOUT,
        help="seconds for the program to start running",
    )
    parser.add_argument(
        "--test-failure", action="store_true", help="send an invalid command to test error reporting"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")

    try:
        success = write_and_verify(args.host, TARGET_JOINTS, args.startup_timeout, args.test_failure)
    except KeyboardInterrupt:
        logging.info("Stopped by user")
        return 1
    except (OSError, ValueError) as error:
        logging.error("Robot %s connection error: %s", args.host, error)
        return 1
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
