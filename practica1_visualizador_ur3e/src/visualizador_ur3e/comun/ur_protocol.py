"""Decoding of the UR primary interface and Dashboard Server messages, shared by every tool."""
import struct
from collections.abc import Iterator
from typing import NamedTuple, TextIO

# Dashboard Server: plain text, one command and one answer per line
DASHBOARD_PORT = 29999
REMOTE_CONTROL_QUERY = "is in remote control"  # answers true or false (e-Series, PolyScope 5.6 or later)

HEADER = struct.Struct(">iB")  # length (int32) + type (uint8), used by messages and sub-packages
MAX_MSG_LEN = 2**20  # 1 MiB; primary messages vary in size, anything larger is corrupt

ROBOT_STATE = 16
ROBOT_MESSAGE = 20

# Robot State sub-packages
ROBOT_MODE_DATA = 0
JOINT_DATA = 1
MASTERBOARD_DATA = 3
ROBOT_MODE = struct.Struct(">Q7?")  # timestamp + 7 status flags
JOINT_RECORD = struct.Struct(">dddffffB")  # one joint in the Joint Data sub-package
# Master Board Data: I/O, analog values and power, up to euromap67InterfaceInstalled
MASTERBOARD = struct.Struct(">iiBBddbbddffffBBb")
EUROMAP = struct.Struct(">IIff")  # only present when the Euromap67 interface is installed
# UR internal uint32, operationalModeSelectorInput, threePositionEnablingDeviceInput, UR internal byte
MASTERBOARD_TAIL = struct.Struct(">IBBB")

# Robot Message types
TEXT_MESSAGE = 0
VERSION_MESSAGE = 3
ERROR_CODE_MESSAGE = 6
KEY_MESSAGE = 7  # e.g. PROGRAM_XXX_STARTED with the program name as text
RUNTIME_EXCEPTION_MESSAGE = 10  # e.g. an unknown function in a URScript program
ROBOT_MESSAGE_NAMES = {
    TEXT_MESSAGE: "text",
    VERSION_MESSAGE: "version",
    ERROR_CODE_MESSAGE: "error code",
    KEY_MESSAGE: "key",
    RUNTIME_EXCEPTION_MESSAGE: "runtime exception",
}
ROBOT_MESSAGE_HEADER = struct.Struct(">QbB")  # timestamp, source, robotMessageType
ROBOT_MESSAGE_FIELDS = {  # numeric fields before the title and text, per message type
    TEXT_MESSAGE: (struct.Struct(">"), ()),
    ERROR_CODE_MESSAGE: (struct.Struct(">iiiII"), ("code", "argument", "report_level", "data_type", "data")),
    KEY_MESSAGE: (struct.Struct(">iiB"), ("code", "argument", "title_size")),
    RUNTIME_EXCEPTION_MESSAGE: (struct.Struct(">ii"), ("line", "column")),
}
PROGRAM_STARTED = "PROGRAM_XXX_STARTED"
PROGRAM_STOPPED = "PROGRAM_XXX_STOPPED"


class RobotMode(NamedTuple):
    timestamp: int
    real_robot_connected: bool
    real_robot_enabled: bool
    power_on: bool
    emergency_stopped: bool
    protective_stopped: bool
    program_running: bool
    program_paused: bool


class MasterBoard(NamedTuple):
    digital_input_bits: int
    digital_output_bits: int
    analog_input_range0: int
    analog_input_range1: int
    analog_input0: float
    analog_input1: float
    analog_output_domain0: int
    analog_output_domain1: int
    analog_output0: float
    analog_output1: float
    masterboard_temperature: float
    robot_voltage_48v: float
    robot_current: float
    master_io_current: float
    safety_mode: int
    in_reduced_mode: int
    euromap67_installed: int
    operational_mode_selector_input: int
    three_position_enabling_device_input: int


class RobotMessage(NamedTuple):
    timestamp: int
    message_type: int
    source: int
    title: str  # only key messages have a title
    text: str
    details: dict[str, int]


def extract_messages(buffer: bytearray) -> Iterator[tuple[int, bytes]]:
    """Remove each complete message from buffer and yield its (type, body)."""
    while len(buffer) >= HEADER.size:
        msg_len, msg_type = HEADER.unpack_from(buffer)
        if not HEADER.size <= msg_len <= MAX_MSG_LEN:
            raise ValueError(f"Invalid message length: {msg_len}")
        if len(buffer) < msg_len:
            return
        body = bytes(buffer[HEADER.size:msg_len])
        del buffer[:msg_len]
        yield msg_type, body


def iter_subpackages(robot_state: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield (type, body) of each sub-package in a Robot State body, stopping at a malformed one."""
    offset = 0
    while offset + HEADER.size <= len(robot_state):
        sub_len, sub_type = HEADER.unpack_from(robot_state, offset)
        end = offset + sub_len
        if sub_len < HEADER.size or end > len(robot_state):
            return
        yield sub_type, robot_state[offset + HEADER.size:end]
        offset = end


def parse_joint_positions(robot_state: bytes) -> list[float] | None:
    """Return q_actual of each joint from a Robot State body, or None if absent."""
    for sub_type, body in iter_subpackages(robot_state):
        if sub_type == JOINT_DATA and len(body) % JOINT_RECORD.size == 0:
            return [joint[0] for joint in JOINT_RECORD.iter_unpack(body)]
    return None


def parse_robot_mode(robot_state: bytes) -> RobotMode | None:
    """Return the Robot Mode Data of a Robot State body, or None if absent."""
    for sub_type, body in iter_subpackages(robot_state):
        if sub_type == ROBOT_MODE_DATA and len(body) >= ROBOT_MODE.size:
            return RobotMode._make(ROBOT_MODE.unpack_from(body))
    return None


def parse_masterboard(robot_state: bytes) -> MasterBoard | None:
    """Return the Master Board Data of a Robot State body, or None if absent."""
    for sub_type, body in iter_subpackages(robot_state):
        if sub_type != MASTERBOARD_DATA or len(body) < MASTERBOARD.size:
            continue
        fields = MASTERBOARD.unpack_from(body)
        offset = MASTERBOARD.size + (EUROMAP.size if fields[-1] else 0)  # last field: Euromap67 installed
        if len(body) < offset + MASTERBOARD_TAIL.size:
            return None
        _, selector, enabling_device, _ = MASTERBOARD_TAIL.unpack_from(body, offset)
        return MasterBoard(*fields, selector, enabling_device)
    return None


def ask_dashboard(stream: TextIO, command: str) -> str:
    """Send one Dashboard Server command and return its answer without the line break."""
    stream.write(command + "\n")
    stream.flush()
    answer = stream.readline()
    if not answer:
        raise ConnectionError("Connection closed by the Dashboard Server")
    return answer.strip()


def parse_remote_control(answer: str) -> bool | None:
    """Return the answer to REMOTE_CONTROL_QUERY as a bool, or None if the robot cannot report it."""
    return {"true": True, "false": False}.get(answer.lower())


def parse_robot_message(body: bytes) -> RobotMessage | None:
    """Decode a Robot Message body, or return None if it is too short for its type."""
    if len(body) < ROBOT_MESSAGE_HEADER.size:
        return None
    timestamp, source, message_type = ROBOT_MESSAGE_HEADER.unpack_from(body)
    if message_type not in ROBOT_MESSAGE_FIELDS:
        return RobotMessage(timestamp, message_type, source, "", "", {})
    fields, names = ROBOT_MESSAGE_FIELDS[message_type]
    offset = ROBOT_MESSAGE_HEADER.size
    if len(body) < offset + fields.size:
        return None
    details = dict(zip(names, fields.unpack_from(body, offset)))
    offset += fields.size
    title_size = details.pop("title_size", 0)
    if len(body) < offset + title_size:
        return None
    title = body[offset:offset + title_size].decode("utf-8", errors="replace")
    text = body[offset + title_size:].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return RobotMessage(timestamp, message_type, source, title, text, details)
