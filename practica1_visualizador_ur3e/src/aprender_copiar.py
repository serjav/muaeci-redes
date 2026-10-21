"""Learn and Copy: record the joint positions of a UR3e and replay them point by point."""
import argparse
import json
import logging
import math
import socket
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from escribir import DEFAULT_HOST, PORT, RECV_SIZE, TIMEOUT, write_and_verify
from ur_protocol import ROBOT_STATE, extract_messages, parse_joint_positions

# Next to the .exe once packed with PyInstaller (its own files live in a temporary folder),
# otherwise the project's data folder.
DATA_DIR = (
    Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
) / "data"
FILE_VERSION = 1
JOINT_COUNT = 6
JOINT_LIMIT = 2 * math.pi  # UR3e joint range is +-360 degrees

LEARN_HELP = "c = capture point, d = delete last point, l = list points, f = finish and save, q = quit without saving"
COPY_OPTIONS = ("r", "s", "x")
COPY_HELP = "r = retry the failed point, s = start again from point 1, x = cancel"


def format_joints(joints: list[float]) -> str:
    return "[" + ", ".join(f"{joint:.4f}" for joint in joints) + "]"


def list_points(points: list[list[float]]) -> None:
    if not points:
        logging.info("No points captured")
    for index, joints in enumerate(points, start=1):
        logging.info("Point %d: %s rad", index, format_joints(joints))


def read_current_joints(host: str) -> list[float]:
    """Return the robot's current joint positions from its next state message."""
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as client:
        buffer = bytearray()
        while data := client.recv(RECV_SIZE):
            buffer.extend(data)
            for msg_type, body in extract_messages(buffer):
                if msg_type == ROBOT_STATE and (joints := parse_joint_positions(body)) is not None:
                    return joints
    raise ConnectionError("Connection closed by the robot")


def save_sequence(path: Path, points: list[list[float]], host: str) -> None:
    """Write the points to a new JSON file, one point per line, failing if it already exists."""
    metadata = {
        "format_version": FILE_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "host": host,
        "units": "rad",
    }
    header = json.dumps(metadata, indent=2)[:-2]  # without the closing "\n}"
    rows = ",\n".join(f"    {json.dumps(point)}" for point in points)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(f'{header},\n  "points": [\n{rows}\n  ]\n}}\n')


def is_valid_point(point: object) -> bool:
    return (
        isinstance(point, list)
        and len(point) == JOINT_COUNT
        and all(
            isinstance(joint, (int, float)) and not isinstance(joint, bool) and abs(joint) <= JOINT_LIMIT
            for joint in point
        )
    )


def load_sequence(path: Path) -> tuple[list[list[float]], str]:
    """Return the points and the recorded host of a sequence file, raising ValueError if invalid."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("format_version") != FILE_VERSION:
        raise ValueError(f"{path} is not a version {FILE_VERSION} sequence file")
    points = document.get("points")
    if not isinstance(points, list) or not points or not all(map(is_valid_point, points)):
        raise ValueError(f"{path} has no points or an invalid point")
    return points, str(document.get("host", DEFAULT_HOST))


def learn(host: str, path: Path) -> int:
    """Capture joint positions on c + Enter until the operator saves or quits."""
    if path.exists():
        logging.error("%s already exists, choose another file", path)
        return 1
    points: list[list[float]] = []
    logging.info("Learning from robot %s. %s", host, LEARN_HELP)
    while True:
        match input("> ").strip().lower():
            case "c":
                try:
                    joints = read_current_joints(host)
                except (OSError, ValueError) as error:
                    logging.error("Could not read robot %s: %s", host, error)
                    continue
                points.append(joints)
                logging.info("Point %d captured: %s rad", len(points), format_joints(joints))
            case "d":
                if points:
                    points.pop()
                    logging.info("Point %d deleted", len(points) + 1)
                else:
                    logging.warning("No points to delete")
            case "l":
                list_points(points)
            case "f":
                if not points:
                    logging.warning("No points captured, nothing to save")
                    continue
                try:
                    save_sequence(path, points, host)
                except OSError as error:
                    logging.error("Could not save the sequence: %s", error)
                    continue
                logging.info("Saved %d points to %s", len(points), path)
                return 0
            case "q":
                logging.info("Quit without saving")
                return 0
            case command:
                logging.warning("Unknown command %r. %s", command, LEARN_HELP)


def ask(prompt: str, options: tuple[str, ...]) -> str:
    """Ask until the operator types one of the options."""
    while (answer := input(f"{prompt}\n> ").strip().lower()) not in options:
        logging.warning("Unknown option %r", answer)
    return answer


def move_to_point(host: str, joints: list[float]) -> bool:
    try:
        return write_and_verify(host, joints)
    except (OSError, ValueError) as error:
        logging.error("Robot %s connection error: %s", host, error)
        return False


def copy_sequence(
    host: str,
    points: list[list[float]],
    on_failure: Callable[[int, int], str],
    on_point: Callable[[int, int], None] | None = None,
) -> bool:
    """Move the robot through the points, verifying each one. Return False if the operator cancels.

    on_failure(point, total) decides what to do after a failed point: "r" retry, "s" start again
    or "x" cancel. on_point(point, total) is called before moving to each point.
    """
    index = 0
    while index < len(points):
        if on_point:
            on_point(index + 1, len(points))
        logging.info("Point %d/%d: moving to %s rad", index + 1, len(points), format_joints(points[index]))
        if move_to_point(host, points[index]):
            index += 1
            continue
        logging.error("Sequence stopped at point %d/%d, see the reason above", index + 1, len(points))
        match on_failure(index + 1, len(points)):
            case "s":
                index = 0
            case "x":
                logging.info("Sequence cancelled")
                return False
    logging.info("Sequence completed: %d points", len(points))
    return True


def copy(host: str, path: Path) -> int:
    """Replay a saved sequence point by point, verifying each movement."""
    points, recorded_host = load_sequence(path)
    host = host or recorded_host
    logging.info("Sequence %s: %d points recorded on %s", path, len(points), recorded_host)
    list_points(points)
    logging.warning("Robot %s will move from its current position to point 1", host)
    if input("Type y and Enter to start, anything else to cancel\n> ").strip().lower() != "y":
        logging.info("Sequence cancelled")
        return 1
    completed = copy_sequence(host, points, lambda point, total: ask(COPY_HELP, COPY_OPTIONS))
    return 0 if completed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Learn and Copy: record UR3e joint positions and replay them")
    modes = parser.add_subparsers(dest="mode", required=True)
    learn_parser = modes.add_parser("aprender", help="capture joint positions with c + Enter")
    learn_parser.add_argument("--host", default=DEFAULT_HOST, help="robot IP address")
    learn_parser.add_argument(
        "--file", type=Path, help="where to save the sequence (default: data/secuencia_<date>.json)"
    )
    copy_parser = modes.add_parser("copiar", help="replay a saved sequence point by point")
    copy_parser.add_argument("--host", help="robot IP address (default: the robot the sequence was recorded on)")
    copy_parser.add_argument("--file", type=Path, required=True, help="sequence file to replay")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")

    try:
        if args.mode == "aprender":
            path = args.file or DATA_DIR / f"secuencia_{datetime.now():%Y%m%d_%H%M%S}.json"
            return learn(args.host, path)
        return copy(args.host, args.file)
    except (KeyboardInterrupt, EOFError):
        logging.info("Stopped by user")
        return 1
    except (OSError, ValueError) as error:
        logging.error("%s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
