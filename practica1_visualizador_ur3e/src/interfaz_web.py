"""Local web UI for the UR3e clients: monitoring, 3D visualizer and Learn and Copy."""
import argparse
import itertools
import json
import logging
import re
import sys
import threading
import webbrowser
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pybullet
from UR3e_rg2.dynamic_ur3e import UR3eRG2

import primaria
import tiempo_real
from aprender_copiar import DATA_DIR, copy_sequence, format_joints, load_sequence, read_current_joints, save_sequence

LOCAL_HOST = "127.0.0.1"  # the UI can move real robots, so it is never exposed to the network
DEFAULT_PORT = 8000
# Static files live next to this script, or inside the bundle once packed with PyInstaller.
WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "interfaz"
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/estilos.css": ("estilos.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}

INTERFACES = {"primaria": primaria.run_robot, "tiempo_real": tiempo_real.run_robot}
SPAWN_SPACING = primaria.SPAWN_SPACING
PARKED_POSITION = [0, 0, -5]  # below the floor, out of sight
# Camera set each time the window opens, looking at the robots slightly from above.
CAMERA_DISTANCE = 0.9  # m, for a single robot; grows with the width of the row of robots
CAMERA_YAW = 45  # degrees, three-quarter view of a single robot
CAMERA_YAW_ROW = 10  # degrees, nearly facing a row of robots so they all look the same size
CAMERA_PITCH = -25  # degrees
CAMERA_HEIGHT = 0.2  # m, height of the point the camera looks at
IDENTITY = [0, 0, 0, 1]  # quaternion without rotation
HOST_PATTERN = re.compile(r"[A-Za-z0-9.\-]{1,253}")
FILE_PATTERN = re.compile(r"[\w\-. ]{1,100}\.json")
LOG_SIZE = 500
TEACH_THREAD = "ensenar"  # log records from threads with this prefix go to the teach page


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class LogBuffer(logging.Handler):
    """Keep the latest log records so the page can poll them."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: deque[dict] = deque(maxlen=LOG_SIZE)
        self.next_id = 0
        self.last_teach_error = ""

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        channel = "teach" if record.threadName.startswith(TEACH_THREAD) else "monitor"
        self.records.append({
            "id": self.next_id,
            "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "channel": channel,
            "message": message,
        })
        self.next_id += 1
        if channel == "teach" and record.levelno >= logging.ERROR and not message.startswith("Sequence stopped"):
            self.last_teach_error = message

    def since(self, first_id: int) -> tuple[list[dict], int]:
        with self.lock:
            return [entry for entry in self.records if entry["id"] >= first_id], self.next_id


class Visualizer:
    """The UR3eRG2 window, with one simulated robot per monitored host."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.simulator: UR3eRG2 | None = None
        self.bodies: dict[str, tuple[int, int]] = {}  # host -> (slot, simulator body id)

    @property
    def is_open(self) -> bool:
        return self.simulator is not None

    def body_of(self, host: str) -> int | None:
        slot_body = self.bodies.get(host)
        return slot_body[1] if slot_body else None

    def open(self, hosts: list[str]) -> None:
        with self.lock:
            if self.simulator is None:
                try:
                    self.simulator = UR3eRG2()
                except pybullet.error as error:
                    raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, f"No se pudo abrir el visualizador: {error}")
                self.bodies = {}
                logging.info("Visualizer opened")
                opened = True
            else:
                opened = False
            for host in hosts:
                if host not in self.bodies:
                    self._attach(host)
            if not any(slot == 0 for slot, _ in self.bodies.values()):
                pybullet.resetBasePositionAndOrientation(0, PARKED_POSITION, IDENTITY)
            if opened:
                self._frame_camera()

    def _frame_camera(self) -> None:
        """Point the camera at the row of robots, which starts at x = 0."""
        width = max((slot for slot, _ in self.bodies.values()), default=0) * SPAWN_SPACING
        pybullet.resetDebugVisualizerCamera(
            cameraDistance=CAMERA_DISTANCE + width * 0.5,
            cameraYaw=CAMERA_YAW_ROW if width else CAMERA_YAW,
            cameraPitch=CAMERA_PITCH,
            cameraTargetPosition=[width / 2, 0, CAMERA_HEIGHT],
        )

    def attach(self, host: str) -> None:
        with self.lock:
            if self.simulator is not None and host not in self.bodies:
                self._attach(host)

    def _attach(self, host: str) -> None:
        used = {slot for slot, _ in self.bodies.values()}
        slot = next(index for index in itertools.count() if index not in used)
        pose = [slot * SPAWN_SPACING, 0, 0, 0, 0, 0]
        try:
            if slot == 0:  # body 0 is created by UR3eRG2() itself
                pybullet.resetBasePositionAndOrientation(0, pose[:3], IDENTITY)
                body = 0
            else:
                body = self.simulator.spawn_robot(pose)
        except pybullet.error:
            self._closed()
            return
        self.bodies[host] = (slot, body)
        logging.info("Robot %s shown as simulator body %d", host, body)

    def detach(self, host: str) -> None:
        with self.lock:
            if self.simulator is None or host not in self.bodies:
                return
            _, body = self.bodies.pop(host)
            try:
                if body == 0:  # UR3eRG2 reads body 0 on every move, so it is parked instead of removed
                    pybullet.resetBasePositionAndOrientation(0, PARKED_POSITION, IDENTITY)
                else:
                    pybullet.removeBody(body)
            except pybullet.error:
                self._closed()

    def move(self, host: str, joints: list[float]) -> None:
        with self.lock:
            if self.simulator is None or host not in self.bodies:
                return
            try:
                self.simulator.move_robot(self.bodies[host][1], list(joints))  # move_robot extends its list
            except pybullet.error:
                self._closed()

    def _closed(self) -> None:
        logging.warning("Visualizer window closed")
        self.simulator = None
        self.bodies = {}
        try:
            pybullet.disconnect()
        except pybullet.error:
            pass


class Monitor:
    """Monitored hosts, each streaming joints in its own thread."""

    def __init__(self, visualizer: Visualizer) -> None:
        self.lock = threading.Lock()
        self.visualizer = visualizer
        self.hosts: dict[str, dict] = {}

    def add(self, host: str, interface: str) -> None:
        if interface not in INTERFACES:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Interfaz desconocida: {interface}")
        entry = {"interface": interface, "status": "connecting", "joints": None, "stop": threading.Event()}
        with self.lock:
            if host in self.hosts:
                raise ApiError(HTTPStatus.CONFLICT, f"El robot {host} ya está en la lista")
            self.hosts[host] = entry

        def move(joints: list[float]) -> None:
            if not entry["stop"].is_set():  # a removed host may still deliver one last message
                entry["joints"] = list(joints)
                self.visualizer.move(host, joints)

        def on_status(status: str) -> None:
            entry["status"] = status

        logging.info("Robot %s added (%s interface)", host, interface)
        self.visualizer.attach(host)
        threading.Thread(
            target=INTERFACES[interface], args=(host, move, entry["stop"], on_status), name=host, daemon=True
        ).start()

    def remove(self, host: str) -> None:
        with self.lock:
            entry = self.hosts.pop(host, None)
        if entry is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"El robot {host} no está en la lista")
        entry["stop"].set()
        self.visualizer.detach(host)
        logging.info("Robot %s removed", host)

    def stop_all(self) -> None:
        with self.lock:
            for entry in self.hosts.values():
                entry["stop"].set()

    def host_names(self) -> list[str]:
        with self.lock:
            return list(self.hosts)

    def snapshot(self) -> list[dict]:
        with self.lock:
            items = list(self.hosts.items())
        return [
            {
                "host": host,
                "interface": entry["interface"],
                "status": entry["status"],
                "joints": entry["joints"],
                "body": self.visualizer.body_of(host),
            }
            for host, entry in items
        ]


class Teacher:
    """Captured points and the sequence being replayed."""

    def __init__(self, log_buffer: LogBuffer) -> None:
        self.lock = threading.Lock()
        self.log_buffer = log_buffer
        self.points: list[list[float]] = []
        self.saved_as: str | None = None  # file holding the current points, if unchanged since
        self.running = False
        self.progress = {"point": 0, "total": 0, "state": "idle"}
        self.decision: dict | None = None  # pending failure waiting for the operator
        self.decision_ids = itertools.count(1)  # lets the page tell two failures at the same point apart
        self.answer = ""
        self.answered = threading.Event()

    def _check_idle(self) -> None:
        if self.running:
            raise ApiError(HTTPStatus.CONFLICT, "Hay una secuencia en ejecución")

    def capture(self, host: str) -> None:
        self._check_idle()
        try:
            joints = read_current_joints(host)
        except (OSError, ValueError) as error:
            logging.error("Could not read robot %s: %s", host, error)
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"No se pudo leer el robot {host}: {error}")
        with self.lock:
            self.points.append(joints)
            self.saved_as = None
            logging.info("Point %d captured: %s rad", len(self.points), format_joints(joints))

    def delete(self, index: int) -> None:
        with self.lock:
            self._check_idle()
            if not 0 <= index < len(self.points):
                raise ApiError(HTTPStatus.NOT_FOUND, "Ese punto no existe")
            self.points.pop(index)
            self.saved_as = None
            logging.info("Point %d deleted", index + 1)

    @staticmethod
    def _path(name: str) -> Path:
        if not name.endswith(".json"):
            name += ".json"
        if not FILE_PATTERN.fullmatch(name):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Nombre de archivo no válido")
        return DATA_DIR / name

    def files(self) -> list[dict]:
        paths = sorted(DATA_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        return [
            {"name": path.name, "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")}
            for path in paths
        ]

    def save(self, name: str, host: str) -> str:
        path = self._path(name)
        with self.lock:
            if not self.points:
                raise ApiError(HTTPStatus.CONFLICT, "No hay puntos que guardar")
            try:
                save_sequence(path, self.points, host)
            except FileExistsError:
                raise ApiError(HTTPStatus.CONFLICT, f"{path.name} ya existe, elige otro nombre")
            self.saved_as = path.name
            logging.info("Saved %d points to %s", len(self.points), path)
        return path.name

    def load(self, name: str) -> str:
        path = self._path(name)
        try:
            points, host = load_sequence(path)
        except FileNotFoundError:
            raise ApiError(HTTPStatus.NOT_FOUND, f"{path.name} no existe")
        except (OSError, ValueError) as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(error))
        with self.lock:
            self._check_idle()
            self.points = points
            self.saved_as = path.name
            logging.info("Sequence %s loaded: %d points recorded on %s", path.name, len(points), host)
        return host

    def execute(self, host: str) -> None:
        with self.lock:
            self._check_idle()
            if not self.points:
                raise ApiError(HTTPStatus.CONFLICT, "No hay puntos que ejecutar")
            self.running = True
            self.progress = {"point": 0, "total": len(self.points), "state": "moving"}
            points = list(self.points)
        threading.Thread(target=self._run, args=(host, points), name=f"{TEACH_THREAD}-ejecucion", daemon=True).start()

    def _run(self, host: str, points: list[list[float]]) -> None:
        logging.info("Sequence started on %s: %d points", host, len(points))
        try:
            completed = copy_sequence(host, points, self._wait_for_decision, self._on_point)
            self.progress["state"] = "completed" if completed else "cancelled"
        except Exception:
            logging.exception("Sequence failed")
            self.progress["state"] = "error"
        finally:
            self.running = False

    def _on_point(self, point: int, total: int) -> None:
        self.progress = {"point": point, "total": total, "state": "moving"}

    def _wait_for_decision(self, point: int, total: int) -> str:
        self.progress = {"point": point, "total": total, "state": "stopped"}
        self.answered.clear()
        self.decision = {
            "id": next(self.decision_ids),
            "point": point,
            "total": total,
            "reason": self.log_buffer.last_teach_error,
        }
        self.answered.wait()
        self.decision = None
        return self.answer

    def decide(self, option: str) -> None:
        if self.decision is None:
            raise ApiError(HTTPStatus.CONFLICT, "No hay ninguna decisión pendiente")
        if option not in ("r", "s", "x"):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Opción desconocida: {option}")
        self.answer = option
        self.answered.set()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "points": list(self.points),
                "saved_as": self.saved_as,
                "running": self.running,
                "progress": dict(self.progress),
                "decision": self.decision,
            }


def text_field(data: dict, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, f"Falta el campo {name}")
    return value.strip()


def host_field(data: dict) -> str:
    host = text_field(data, "host")
    if not HOST_PATTERN.fullmatch(host):
        raise ApiError(HTTPStatus.BAD_REQUEST, f"Dirección de robot no válida: {host}")
    return host


class App:
    def __init__(self, log_buffer: LogBuffer) -> None:
        self.log_buffer = log_buffer
        self.visualizer = Visualizer()
        self.monitor = Monitor(self.visualizer)
        self.teacher = Teacher(log_buffer)

    def state(self, query: dict) -> dict:
        logs, next_log = self.log_buffer.since(int(query.get("desde", 0)))
        return {
            "visualizer": self.visualizer.is_open,
            "hosts": self.monitor.snapshot(),
            "teach": self.teacher.snapshot(),
            "logs": logs,
            "next_log": next_log,
        }

    def open_visualizer(self, data: dict) -> None:
        self.visualizer.open(self.monitor.host_names())

    def add_host(self, data: dict) -> None:
        self.monitor.add(host_field(data), text_field(data, "interface"))

    def remove_host(self, data: dict) -> None:
        self.monitor.remove(host_field(data))

    def capture(self, data: dict) -> None:
        self.teacher.capture(host_field(data))

    def delete_point(self, data: dict) -> None:
        index = data.get("index")
        if not isinstance(index, int):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Falta el campo index")
        self.teacher.delete(index)

    def sequences(self, query: dict) -> dict:
        return {"files": self.teacher.files()}

    def save(self, data: dict) -> dict:
        return {"name": self.teacher.save(text_field(data, "name"), host_field(data))}

    def load(self, data: dict) -> dict:
        return {"host": self.teacher.load(text_field(data, "name"))}

    def execute(self, data: dict) -> None:
        self.teacher.execute(host_field(data))

    def decide(self, data: dict) -> None:
        self.teacher.decide(text_field(data, "option"))


ROUTES = {
    ("GET", "/api/estado"): App.state,
    ("POST", "/api/visualizador/abrir"): App.open_visualizer,
    ("POST", "/api/hosts/anadir"): App.add_host,
    ("POST", "/api/hosts/eliminar"): App.remove_host,
    ("POST", "/api/ensenar/capturar"): App.capture,
    ("POST", "/api/ensenar/borrar"): App.delete_point,
    ("GET", "/api/ensenar/secuencias"): App.sequences,
    ("POST", "/api/ensenar/guardar"): App.save,
    ("POST", "/api/ensenar/cargar"): App.load,
    ("POST", "/api/ensenar/ejecutar"): App.execute,
    ("POST", "/api/ensenar/decision"): App.decide,
}


class Handler(BaseHTTPRequestHandler):
    server: "UIServer"

    def log_message(self, format: str, *args) -> None:
        pass  # the terminal is kept for the robot logs

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if not self._from_this_page():
            return
        if url.path in STATIC_FILES:
            self._send_file(*STATIC_FILES[url.path])
        else:
            self._api("GET", url.path, dict(parse_qsl(url.query)))

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not self._from_this_page():
            return
        # Requiring JSON makes the browser block requests sent by other web pages.
        if self.headers.get_content_type() != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Se esperaba JSON"})
            return
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except (ValueError, json.JSONDecodeError):
            data = None
        if not isinstance(data, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON no válido"})
            return
        self._api("POST", url.path, data)

    def _from_this_page(self) -> bool:
        """Reject requests addressed to another host name, which could come from DNS rebinding."""
        allowed = {f"{LOCAL_HOST}:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") in allowed:
            return True
        self._send_json(HTTPStatus.FORBIDDEN, {"error": "Acceso solo desde este equipo"})
        return False

    def _api(self, method: str, path: str, data: dict) -> None:
        route = ROUTES.get((method, path))
        if route is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
            return
        if path.startswith("/api/ensenar"):
            threading.current_thread().name = TEACH_THREAD
        try:
            self._send_json(HTTPStatus.OK, route(self.server.app, data) or {})
        except ApiError as error:
            self._send_json(error.status, {"error": str(error)})
        except Exception:
            logging.exception("Unexpected error in %s", path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Error interno, revisa el registro"})

    def _send_file(self, name: str, content_type: str) -> None:
        self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), f"{content_type}; charset=utf-8")

    def _send_json(self, status: HTTPStatus, data: dict) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class UIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, app: App) -> None:
        super().__init__((LOCAL_HOST, port), Handler)
        self.app = app


def main() -> int:
    parser = argparse.ArgumentParser(description="Local web UI for the UR3e clients")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="local port for the web UI")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")
    log_buffer = LogBuffer()
    logging.getLogger().addHandler(log_buffer)

    app = App(log_buffer)
    try:
        server = UIServer(args.port, app)
    except OSError as error:
        logging.error("Could not start the web UI on port %d: %s", args.port, error)
        return 1
    url = f"http://{LOCAL_HOST}:{args.port}"
    logging.info("Web UI running at %s", url)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    finally:
        app.monitor.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
