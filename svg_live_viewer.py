#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import re
import sys
import traceback
from typing import Any, Callable
import xml.etree.ElementTree as ET

try:
    from PySide6.QtCore import QTimer, Qt, QRectF, QPointF, QLibraryInfo
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPen, QTransform
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QColorDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("Missing dependency: PySide6\nInstall with: pip install PySide6") from exc


APP_TITLE = "SVG Live Viewer - Cure Interactive"
APP_USER_MODEL_ID = "CureInteractive.SvgLiveViewer"
APP_DIR = Path(__file__).resolve().parent
APP_ICON_ICO_PATH = APP_DIR / "icon.ico"
APP_ICON_PNG_PATH = APP_DIR / "icon-16x16.png"
LOG_PATH = APP_DIR / "svg_live_viewer.log"
APP_CONFIG_PATH = APP_DIR / "config.json"
PROJECT_CONFIG_FILENAME = "svg_live_viewer.json"
DEFAULT_RENDER_WIDTH = 128
DEFAULT_RENDER_HEIGHT = 16
DEFAULT_BG_COLOR = "#1c1c1c"
DEFAULT_TRANSPARENT_TINT_ENABLED = False
DEFAULT_TRANSPARENT_TINT_COLOR = "#00ff00"
DEFAULT_TRANSPARENT_TINT_THRESHOLD = 0
DEFAULT_SHOW_LINE_ANGLES = False
DEFAULT_ANGLE_TEXT_COLOR = "#ffea00"
DEFAULT_ANGLE_TEXT_SIZE = 10
DEFAULT_ANGLE_TEXT_DECIMALS = 1
SVG_PREVIEW_MIN_WIDTH = 1024
RASTER_MIN_ZOOM = 1.0
RASTER_ZOOM_SNAP_NEAR_MIN = 1.05
POLL_MS = 250

CURRENT_PROJECT_DIR: Path | None = None
CURRENT_PROJECT_CONFIG_PATH: Path | None = None
CURRENT_SVG_PATH: Path | None = None


logger = logging.getLogger("svg_live_viewer")
ConfigValue = int | bool | str | float

DEFAULT_APP_CONFIG: dict[str, ConfigValue | dict[str, int] | list[str]] = {
    "window": {"width": 1200, "height": 760},
    "recent_project_dirs_max": 10,
    "recent_project_dirs": [],
}

DEFAULT_PROJECT_CONFIG: dict[str, ConfigValue] = {
    "raster_width": DEFAULT_RENDER_WIDTH,
    "raster_height": DEFAULT_RENDER_HEIGHT,
    "width_locked": True,
    "height_locked": True,
    "bg_color": DEFAULT_BG_COLOR,
    "transparent_tint_enabled": DEFAULT_TRANSPARENT_TINT_ENABLED,
    "transparent_tint_color": DEFAULT_TRANSPARENT_TINT_COLOR,
    "transparent_tint_threshold": DEFAULT_TRANSPARENT_TINT_THRESHOLD,
    "show_line_angles": DEFAULT_SHOW_LINE_ANGLES,
    "angle_text_color": DEFAULT_ANGLE_TEXT_COLOR,
    "angle_text_size": DEFAULT_ANGLE_TEXT_SIZE,
    "angle_text_decimals": DEFAULT_ANGLE_TEXT_DECIMALS,
    "zoom": 12.0,
    "pan_x": 24.0,
    "pan_y": 24.0,
    "active_tab_index": 0,
}

DEFAULT_PROJECT_FILE: dict[str, Any] = {
    "current_svg": "",
    "svg_settings": {},
}


def set_windows_app_user_model_id(app_id: str) -> None:
    try:
        if sys.platform != "win32":
            return
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
    except Exception:
        return


def set_window_icon(window: QMainWindow) -> None:
    icon = QIcon()
    if APP_ICON_ICO_PATH.is_file():
        icon.addFile(str(APP_ICON_ICO_PATH))
    if APP_ICON_PNG_PATH.is_file():
        icon.addFile(str(APP_ICON_PNG_PATH))
    if icon.isNull():
        return
    try:
        window.setWindowIcon(icon)
    except Exception:
        pass
    try:
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
    except Exception:
        pass


def _deep_copy_json_dict(data: dict) -> dict:
    return json.loads(json.dumps(data))


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _norm_dir(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _filter_existing_dirs(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        try:
            if Path(item).is_dir():
                out.append(item)
        except Exception:
            continue
    return out


def project_config_path_for_dir(project_dir: Path) -> Path:
    return project_dir / PROJECT_CONFIG_FILENAME


def get_current_svg_path() -> Path | None:
    return CURRENT_SVG_PATH


def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def log_environment() -> None:
    logger.info("Python executable: %s", sys.executable)
    logger.info("Python version: %s", sys.version.replace("\n", " "))
    logger.info("Script path: %s", APP_DIR / "svg_live_viewer.py")
    logger.info("Log path: %s", LOG_PATH.resolve())
    logger.info("App config path: %s", APP_CONFIG_PATH.resolve())
    logger.info("Qt plugin path: %s", QLibraryInfo.path(QLibraryInfo.PluginsPath))


def load_app_config() -> dict:
    cfg = _deep_copy_json_dict(DEFAULT_APP_CONFIG)
    raw = _read_json(APP_CONFIG_PATH)
    cfg.update(raw)
    if isinstance(raw.get("window"), dict):
        cfg["window"].update(raw["window"])

    recent_max = int(cfg.get("recent_project_dirs_max", 10) or 10)
    if recent_max <= 0:
        recent_max = 10
    raw_recent = cfg.get("recent_project_dirs", [])
    recent_list = [str(x).strip() for x in raw_recent if isinstance(x, str) and str(x).strip()]
    recent_list = [_norm_dir(x) for x in recent_list]
    recent_list = _dedupe_keep_order(recent_list)
    recent_list = _filter_existing_dirs(recent_list)
    cfg["recent_project_dirs_max"] = recent_max
    cfg["recent_project_dirs"] = recent_list[:recent_max]
    _write_json_atomic(APP_CONFIG_PATH, cfg)
    logger.info("Loaded app config: %s", cfg)
    return cfg


def save_app_config(config: dict) -> None:
    _write_json_atomic(APP_CONFIG_PATH, config)
    logger.info("Saved app config: %s", config)


def _normalize_svg_config(raw: dict[str, Any] | None) -> dict[str, ConfigValue]:
    cfg = _deep_copy_json_dict(DEFAULT_PROJECT_CONFIG)
    if isinstance(raw, dict):
        cfg.update(raw)

    width = max(1, int(cfg.get("raster_width", DEFAULT_RENDER_WIDTH)))
    height = max(1, int(cfg.get("raster_height", DEFAULT_RENDER_HEIGHT)))
    width_locked = bool(cfg.get("width_locked", True))
    height_locked = bool(cfg.get("height_locked", True))
    if not width_locked and not height_locked:
        height_locked = True

    bg_color_raw = str(cfg.get("bg_color", DEFAULT_BG_COLOR))
    transparent_tint_raw = str(cfg.get("transparent_tint_color", DEFAULT_TRANSPARENT_TINT_COLOR))
    angle_text_color_raw = str(cfg.get("angle_text_color", DEFAULT_ANGLE_TEXT_COLOR))
    zoom = float(cfg.get("zoom", 12.0))
    if zoom <= 0:
        zoom = 12.0

    return {
        "raster_width": width,
        "raster_height": height,
        "width_locked": width_locked,
        "height_locked": height_locked,
        "bg_color": QColor(bg_color_raw).name() if QColor(bg_color_raw).isValid() else DEFAULT_BG_COLOR,
        "transparent_tint_enabled": bool(cfg.get("transparent_tint_enabled", DEFAULT_TRANSPARENT_TINT_ENABLED)),
        "transparent_tint_color": QColor(transparent_tint_raw).name() if QColor(transparent_tint_raw).isValid() else DEFAULT_TRANSPARENT_TINT_COLOR,
        "transparent_tint_threshold": max(0, min(255, int(cfg.get("transparent_tint_threshold", DEFAULT_TRANSPARENT_TINT_THRESHOLD)))),
        "show_line_angles": bool(cfg.get("show_line_angles", DEFAULT_SHOW_LINE_ANGLES)),
        "angle_text_color": QColor(angle_text_color_raw).name() if QColor(angle_text_color_raw).isValid() else DEFAULT_ANGLE_TEXT_COLOR,
        "angle_text_size": max(6, int(cfg.get("angle_text_size", DEFAULT_ANGLE_TEXT_SIZE))),
        "angle_text_decimals": max(0, min(4, int(cfg.get("angle_text_decimals", DEFAULT_ANGLE_TEXT_DECIMALS)))),
        "zoom": zoom,
        "pan_x": float(cfg.get("pan_x", 24.0)),
        "pan_y": float(cfg.get("pan_y", 24.0)),
        "active_tab_index": max(0, min(1, int(cfg.get("active_tab_index", 0)))),
    }


def load_project_config(project_dir: Path | None) -> dict[str, Any]:
    project_file = _deep_copy_json_dict(DEFAULT_PROJECT_FILE)
    if project_dir is None:
        return project_file

    raw = _read_json(project_config_path_for_dir(project_dir))
    current_svg = str(raw.get("current_svg", "") or "")
    svg_settings_raw = raw.get("svg_settings", {})
    svg_settings: dict[str, dict[str, ConfigValue]] = {}

    if isinstance(svg_settings_raw, dict):
        for key, value in svg_settings_raw.items():
            if not isinstance(key, str) or not key.strip():
                continue
            svg_settings[key.replace("\\", "/")] = _normalize_svg_config(value if isinstance(value, dict) else {})
    else:
        # Backward compatibility: migrate older flat config into the per-SVG structure.
        migrated_cfg = _normalize_svg_config(raw)
        if current_svg:
            svg_settings[current_svg.replace("\\", "/")] = migrated_cfg

    project_file["current_svg"] = current_svg.replace("\\", "/")
    project_file["svg_settings"] = svg_settings
    logger.info("Loaded project config: %s", {"project_dir": str(project_dir), **project_file})
    return project_file


def save_project_config(project_dir: Path | None, config: dict[str, Any]) -> None:
    if project_dir is None:
        return
    _write_json_atomic(project_config_path_for_dir(project_dir), config)
    logger.info("Saved project config: %s", {"project_dir": str(project_dir), **config})


def install_exception_hooks() -> None:
    def handle_exception(exc_type, exc_value, exc_tb) -> None:
        logger.error(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception


class ViewerWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)

        self.zoom = 12.0
        self.min_zoom = RASTER_MIN_ZOOM
        self.max_zoom = 250.0
        self.pan = QPointF(24.0, 24.0)

        self.base_image: QImage | None = None
        self.last_mtime_ns: int | None = None
        self.last_error = ""
        self.src_aspect = 1.0

        self.raster_width = DEFAULT_RENDER_WIDTH
        self.raster_height = DEFAULT_RENDER_HEIGHT
        self.width_locked = True
        self.height_locked = True
        self.raster_bg_color = QColor(DEFAULT_BG_COLOR)
        self.transparent_tint_enabled = DEFAULT_TRANSPARENT_TINT_ENABLED
        self.transparent_tint_color = QColor(DEFAULT_TRANSPARENT_TINT_COLOR)
        self.transparent_tint_threshold = DEFAULT_TRANSPARENT_TINT_THRESHOLD
        self.show_line_angles = DEFAULT_SHOW_LINE_ANGLES
        self.angle_text_color = QColor(DEFAULT_ANGLE_TEXT_COLOR)
        self.angle_text_size = DEFAULT_ANGLE_TEXT_SIZE
        self.angle_text_decimals = DEFAULT_ANGLE_TEXT_DECIMALS
        self.svg_preview_mode = False

        self.dragging = False
        self.drag_start_mouse = QPointF(0.0, 0.0)
        self.drag_start_pan = QPointF(0.0, 0.0)
        self.on_view_changed: Callable[[], None] | None = None

    def set_raster_options(
        self, width: int, height: int, width_locked: bool, height_locked: bool
    ) -> None:
        self.raster_width = max(1, int(width))
        self.raster_height = max(1, int(height))
        self.width_locked = bool(width_locked)
        self.height_locked = bool(height_locked)
        logger.info(
            "Raster options updated: width=%d (%s), height=%d (%s)",
            self.raster_width,
            "manual" if self.width_locked else "auto",
            self.raster_height,
            "manual" if self.height_locked else "auto",
        )
        self._refresh_min_zoom(clamp=True)

    def set_bg_color(self, color_text: str) -> None:
        color = QColor(color_text)
        if not color.isValid():
            logger.error("Invalid background color: %s", color_text)
            return
        self.raster_bg_color = color
        logger.info("Raster background color updated: %s", self.raster_bg_color.name())
        self._update_title()

    def set_transparent_tint(self, enabled: bool, color_text: str, threshold: int) -> None:
        color = QColor(color_text)
        if not color.isValid():
            logger.error("Invalid transparent tint color: %s", color_text)
            return
        self.transparent_tint_enabled = bool(enabled)
        self.transparent_tint_color = color
        self.transparent_tint_threshold = max(0, min(255, int(threshold)))
        logger.info(
            "Transparent tint updated: enabled=%s color=%s threshold=%d",
            self.transparent_tint_enabled,
            self.transparent_tint_color.name(),
            self.transparent_tint_threshold,
        )
        self._update_title()

    def set_show_line_angles(self, enabled: bool) -> None:
        self.show_line_angles = bool(enabled)
        logger.info("Show line angles updated: %s", self.show_line_angles)
        self._update_title()

    def set_angle_text_style(self, color_text: str, size: int, decimals: int) -> None:
        color = QColor(color_text)
        if not color.isValid():
            logger.error("Invalid angle text color: %s", color_text)
            return
        self.angle_text_color = color
        self.angle_text_size = max(6, int(size))
        self.angle_text_decimals = max(0, min(4, int(decimals)))
        logger.info(
            "Angle text style updated: color=%s size=%d decimals=%d",
            self.angle_text_color.name(),
            self.angle_text_size,
            self.angle_text_decimals,
        )
        self._update_title()

    def set_view_mode(self, svg_preview_mode: bool) -> None:
        self.svg_preview_mode = bool(svg_preview_mode)
        self._refresh_min_zoom(clamp=True)
        logger.info("View mode updated: %s", "svg" if self.svg_preview_mode else "raster")
        self._update_title()

    def set_view_transform(self, zoom: float, pan_x: float, pan_y: float) -> None:
        self.zoom = max(self.min_zoom, min(self.max_zoom, float(zoom)))
        self.pan = QPointF(float(pan_x), float(pan_y))
        self._update_title()
        self.update()

    def get_render_size_for_mode(self, svg_preview_mode: bool) -> tuple[int, int]:
        render_w, render_h = self._resolve_output_size()
        if svg_preview_mode:
            scale = max(1.0, SVG_PREVIEW_MIN_WIDTH / max(1, render_w))
            render_w = max(1, round(render_w * scale))
            render_h = max(1, round(render_h * scale))
        return render_w, render_h

    def _get_mode_min_zoom(self, svg_preview_mode: bool) -> float:
        raster_w, raster_h = self.get_render_size_for_mode(False)
        if raster_w <= 0 or raster_h <= 0:
            return RASTER_MIN_ZOOM

        if not svg_preview_mode:
            # Never allow raster view to be smaller than 1:1 raster pixels.
            return RASTER_MIN_ZOOM

        # Allow SVG preview to zoom down until its on-screen size matches
        # raster mode's minimum visible size.
        svg_w, svg_h = self.get_render_size_for_mode(True)
        if svg_w <= 0 or svg_h <= 0:
            return 0.001
        return max((RASTER_MIN_ZOOM * raster_w) / svg_w, (RASTER_MIN_ZOOM * raster_h) / svg_h)

    def _refresh_min_zoom(self, clamp: bool) -> None:
        self.min_zoom = self._get_mode_min_zoom(self.svg_preview_mode)
        if clamp:
            self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom))

    def _resolve_output_size(self) -> tuple[int, int]:
        aspect = self.src_aspect if self.src_aspect > 0 else 1.0
        if self.width_locked and self.height_locked:
            return self.raster_width, self.raster_height
        if self.width_locked and not self.height_locked:
            return self.raster_width, max(1, round(self.raster_width / aspect))
        if self.height_locked and not self.width_locked:
            return max(1, round(self.raster_height * aspect)), self.raster_height
        return self.raster_width, self.raster_height

    @staticmethod
    def _parse_points(points_text: str) -> list[tuple[float, float]]:
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", points_text)
        points: list[tuple[float, float]] = []
        for i in range(0, len(nums) - 1, 2):
            points.append((float(nums[i]), float(nums[i + 1])))
        return points

    @staticmethod
    def _parse_path_segments(path_d: str) -> list[tuple[float, float, float, float]]:
        tokens = re.findall(r"[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path_d)
        segments: list[tuple[float, float, float, float]] = []
        i = 0
        cmd = ""
        cx = cy = 0.0
        sx = sy = 0.0

        def is_number(token: str) -> bool:
            return bool(re.match(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$", token))

        def read_num() -> float:
            nonlocal i
            val = float(tokens[i])
            i += 1
            return val

        while i < len(tokens):
            if re.match(r"^[A-Za-z]$", tokens[i]):
                cmd = tokens[i]
                i += 1
            elif not cmd:
                break

            if cmd in ("M", "m"):
                first = True
                while i + 1 < len(tokens) and is_number(tokens[i]) and is_number(tokens[i + 1]):
                    x = read_num()
                    y = read_num()
                    if cmd == "m":
                        x += cx
                        y += cy
                    if first:
                        cx, cy = x, y
                        sx, sy = x, y
                        first = False
                    else:
                        segments.append((cx, cy, x, y))
                        cx, cy = x, y
                continue

            if cmd in ("L", "l"):
                while i + 1 < len(tokens) and is_number(tokens[i]) and is_number(tokens[i + 1]):
                    x = read_num()
                    y = read_num()
                    if cmd == "l":
                        x += cx
                        y += cy
                    segments.append((cx, cy, x, y))
                    cx, cy = x, y
                continue

            if cmd in ("H", "h"):
                while i < len(tokens) and is_number(tokens[i]):
                    x = read_num()
                    if cmd == "h":
                        x += cx
                    segments.append((cx, cy, x, cy))
                    cx = x
                continue

            if cmd in ("V", "v"):
                while i < len(tokens) and is_number(tokens[i]):
                    y = read_num()
                    if cmd == "v":
                        y += cy
                    segments.append((cx, cy, cx, y))
                    cy = y
                continue

            if cmd in ("Z", "z"):
                segments.append((cx, cy, sx, sy))
                cx, cy = sx, sy
                continue

            param_counts = {"C": 6, "c": 6, "S": 4, "s": 4, "Q": 4, "q": 4, "T": 2, "t": 2, "A": 7, "a": 7}
            count = param_counts.get(cmd, 0)
            if count == 0:
                continue
            while i + count - 1 < len(tokens) and all(is_number(tokens[i + n]) for n in range(count)):
                vals = [read_num() for _ in range(count)]
                if cmd in ("C", "S", "Q", "T", "A"):
                    cx, cy = vals[-2], vals[-1]
                else:
                    cx += vals[-2]
                    cy += vals[-1]

        return segments

    @staticmethod
    def _parse_transform(transform_text: str) -> QTransform:
        if not transform_text.strip():
            return QTransform()

        transform = QTransform()
        for cmd, params_text in re.findall(r"([A-Za-z]+)\(([^)]*)\)", transform_text):
            nums = [
                float(v)
                for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", params_text)
            ]
            name = cmd.strip().lower()
            step = QTransform()

            if name == "matrix" and len(nums) >= 6:
                a, b, c, d, e, f = nums[:6]
                step = QTransform(a, b, 0.0, c, d, 0.0, e, f, 1.0)
            elif name == "translate":
                tx = nums[0] if len(nums) >= 1 else 0.0
                ty = nums[1] if len(nums) >= 2 else 0.0
                step.translate(tx, ty)
            elif name == "scale":
                sx = nums[0] if len(nums) >= 1 else 1.0
                sy = nums[1] if len(nums) >= 2 else sx
                step.scale(sx, sy)
            elif name == "rotate":
                angle = nums[0] if len(nums) >= 1 else 0.0
                if len(nums) >= 3:
                    cx, cy = nums[1], nums[2]
                    step.translate(cx, cy)
                    step.rotate(angle)
                    step.translate(-cx, -cy)
                else:
                    step.rotate(angle)
            elif name == "skewx" and len(nums) >= 1:
                step.shear(math.tan(math.radians(nums[0])), 0.0)
            elif name == "skewy" and len(nums) >= 1:
                step.shear(0.0, math.tan(math.radians(nums[0])))
            else:
                continue

            transform = transform * step

        return transform

    @staticmethod
    def _is_hidden_element(elem: ET.Element) -> bool:
        display = (elem.attrib.get("display") or "").strip().lower()
        visibility = (elem.attrib.get("visibility") or "").strip().lower()
        if display == "none" or visibility == "hidden":
            return True

        style = (elem.attrib.get("style") or "").strip().lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        return False

    def _extract_line_segments(self) -> list[tuple[float, float, float, float]]:
        try:
            svg_path = get_current_svg_path()
            if svg_path is None:
                return []
            root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to parse SVG for angle overlay: %s", exc)
            return []

        segments: list[tuple[float, float, float, float]] = []

        def strip_ns(tag: str) -> str:
            return tag.split("}", 1)[-1]

        def map_segment(
            t: QTransform, x1: float, y1: float, x2: float, y2: float
        ) -> tuple[float, float, float, float]:
            p1 = t.map(QPointF(x1, y1))
            p2 = t.map(QPointF(x2, y2))
            return (p1.x(), p1.y(), p2.x(), p2.y())

        def walk(elem: ET.Element, inherited: QTransform) -> None:
            if self._is_hidden_element(elem):
                return

            local = self._parse_transform(elem.attrib.get("transform", ""))
            combined = inherited * local
            tag = strip_ns(elem.tag)
            if tag == "line":
                x1 = float(elem.attrib.get("x1", "0"))
                y1 = float(elem.attrib.get("y1", "0"))
                x2 = float(elem.attrib.get("x2", "0"))
                y2 = float(elem.attrib.get("y2", "0"))
                segments.append(map_segment(combined, x1, y1, x2, y2))

            elif tag in ("polyline", "polygon"):
                points = self._parse_points(elem.attrib.get("points", ""))
                for idx in range(len(points) - 1):
                    x1, y1 = points[idx]
                    x2, y2 = points[idx + 1]
                    segments.append(map_segment(combined, x1, y1, x2, y2))
                if tag == "polygon" and len(points) > 2:
                    x1, y1 = points[-1]
                    x2, y2 = points[0]
                    segments.append(map_segment(combined, x1, y1, x2, y2))

            elif tag == "path":
                for x1, y1, x2, y2 in self._parse_path_segments(elem.attrib.get("d", "")):
                    segments.append(map_segment(combined, x1, y1, x2, y2))

            for child in list(elem):
                walk(child, combined)

        walk(root, QTransform())
        return segments

    @staticmethod
    def _effective_target_rect(
        requested: QRectF, src_w: float, src_h: float, aspect_mode: Qt.AspectRatioMode
    ) -> QRectF:
        if src_w <= 0 or src_h <= 0:
            return requested
        if aspect_mode == Qt.IgnoreAspectRatio:
            return requested

        sx = requested.width() / src_w
        sy = requested.height() / src_h
        if aspect_mode == Qt.KeepAspectRatio:
            scale = min(sx, sy)
        else:
            scale = max(sx, sy)

        w = src_w * scale
        h = src_h * scale
        x = requested.x() + (requested.width() - w) * 0.5
        y = requested.y() + (requested.height() - h) * 0.5
        return QRectF(x, y, w, h)

    @staticmethod
    def _draw_line_angle_overlay(
        image: QImage,
        segments: list[tuple[float, float, float, float]],
        src_x: float,
        src_y: float,
        src_w: float,
        src_h: float,
        target_rect: QRectF,
        text_color: QColor,
        text_size: int,
        text_decimals: int,
    ) -> None:
        if not segments or src_w == 0 or src_h == 0:
            return

        sx = target_rect.width() / src_w
        sy = target_rect.height() / src_h
        tx = target_rect.x()
        ty = target_rect.y()

        painter = QPainter(image)
        painter.setPen(QPen(text_color))
        font = painter.font()
        font.setPointSize(text_size)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        for x1, y1, x2, y2 in segments:
            px1 = tx + (x1 - src_x) * sx
            py1 = ty + (y1 - src_y) * sy
            px2 = tx + (x2 - src_x) * sx
            py2 = ty + (y2 - src_y) * sy
            angle = math.degrees(math.atan2(py2 - py1, px2 - px1))
            mx = (px1 + px2) * 0.5
            my = (py1 + py2) * 0.5
            text = f"{angle:.{text_decimals}f}"
            bounds = metrics.boundingRect(text)
            draw_x = mx - (bounds.x() + (bounds.width() * 0.5))
            draw_y = my - (bounds.y() + (bounds.height() * 0.5))
            painter.drawText(
                QPointF(draw_x, draw_y),
                text,
            )
        painter.end()

    def load_svg(self) -> None:
        svg_path = get_current_svg_path()
        if svg_path is None:
            self.base_image = None
            self.last_error = "No SVG selected."
            logger.info(self.last_error)
            self.update()
            return

        if not svg_path.exists():
            self.base_image = None
            self.last_error = f"File not found: {svg_path}"
            logger.error(self.last_error)
            self.update()
            return

        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            self.base_image = None
            self.last_error = f"Invalid SVG: {svg_path}"
            logger.error(self.last_error)
            self.update()
            return

        view_box = renderer.viewBoxF()
        if view_box.isEmpty():
            default_size = renderer.defaultSize()
            src_x = 0.0
            src_y = 0.0
            src_w = float(default_size.width()) if default_size.width() > 0 else 1.0
            src_h = float(default_size.height()) if default_size.height() > 0 else 1.0
        else:
            src_x = view_box.x()
            src_y = view_box.y()
            src_w = view_box.width()
            src_h = view_box.height()

        self.src_aspect = src_w / src_h if src_h else 1.0
        render_w, render_h = self.get_render_size_for_mode(self.svg_preview_mode)

        if self.width_locked and self.height_locked:
            # When both dimensions are explicitly locked, fill the full raster.
            draw_w = float(render_w)
            draw_h = float(render_h)
            draw_x = 0.0
            draw_y = 0.0
        else:
            # Auto mode keeps aspect ratio for the unlocked dimension.
            scale = min(render_w / src_w, render_h / src_h)
            draw_w = src_w * scale
            draw_h = src_h * scale
            draw_x = (render_w - draw_w) / 2.0
            draw_y = (render_h - draw_h) / 2.0
        target_rect = QRectF(draw_x, draw_y, draw_w, draw_h)

        image = QImage(render_w, render_h, QImage.Format_ARGB32)
        image.fill(self.raster_bg_color)

        svg_layer = QImage(render_w, render_h, QImage.Format_ARGB32)
        svg_layer.fill(QColor(0, 0, 0, 0))
        painter = QPainter(svg_layer)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        renderer.render(painter, target_rect)
        painter.end()

        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(0, 0, svg_layer)
        painter.end()

        if self.transparent_tint_enabled:
            tint = self.transparent_tint_color.rgba()
            for y in range(render_h):
                for x in range(render_w):
                    if QColor.fromRgba(svg_layer.pixel(x, y)).alpha() <= self.transparent_tint_threshold:
                        image.setPixel(x, y, tint)

        segment_count = 0
        if self.show_line_angles and self.svg_preview_mode:
            segments = self._extract_line_segments()
            segment_count = len(segments)
            effective_target = self._effective_target_rect(
                target_rect, src_w, src_h, renderer.aspectRatioMode()
            )
            self._draw_line_angle_overlay(
                image=image,
                segments=segments,
                src_x=src_x,
                src_y=src_y,
                src_w=src_w,
                src_h=src_h,
                target_rect=effective_target,
                text_color=self.angle_text_color,
                text_size=self.angle_text_size,
                text_decimals=self.angle_text_decimals,
            )

        self.base_image = image
        self.last_error = ""
        logger.info(
            "Rendered SVG: %dx%d (src_aspect=%.4f draw=%.2fx%.2f mode=%s tint=%s angles=%s segments=%d)",
            render_w,
            render_h,
            (src_w / src_h) if src_h else 0.0,
            draw_w,
            draw_h,
            ("svg-preview" if self.svg_preview_mode else ("fill" if (self.width_locked and self.height_locked) else "fit")),
            self.transparent_tint_enabled,
            self.show_line_angles,
            segment_count,
        )
        self.update()

    def reload_if_changed(self, force: bool = False) -> None:
        svg_path = get_current_svg_path()
        if svg_path is None:
            self.last_mtime_ns = None
            if force:
                self.load_svg()
            self._update_title()
            return
        try:
            mtime_ns = svg_path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime_ns = -1

        if force or self.last_mtime_ns is None or mtime_ns != self.last_mtime_ns:
            self.last_mtime_ns = mtime_ns
            logger.info("Detected SVG change (mtime_ns=%s), reloading", mtime_ns)
            self.load_svg()

        self._update_title()

    def _update_title(self) -> None:
        window = self.window()
        window.setWindowTitle(APP_TITLE)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1c1c1c"))

        if self.base_image is None:
            painter.setPen(QColor("#dddddd"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.last_error or "No image")
            return

        target_w = self.base_image.width() * self.zoom
        target_h = self.base_image.height() * self.zoom
        target = QRectF(self.pan.x(), self.pan.y(), target_w, target_h)

        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(target, self.base_image)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = 1.12 if delta > 0 else 1.0 / 1.12
        new_zoom = max(self.min_zoom, min(self.max_zoom, self.zoom * factor))
        if (not self.svg_preview_mode) and new_zoom <= (RASTER_MIN_ZOOM * RASTER_ZOOM_SNAP_NEAR_MIN):
            new_zoom = RASTER_MIN_ZOOM
        if abs(new_zoom - self.zoom) < 1e-9:
            return

        cursor = event.position()
        image_point_x = (cursor.x() - self.pan.x()) / self.zoom
        image_point_y = (cursor.y() - self.pan.y()) / self.zoom

        self.zoom = new_zoom
        self.pan = QPointF(
            cursor.x() - image_point_x * self.zoom,
            cursor.y() - image_point_y * self.zoom,
        )

        self._update_title()
        self.update()
        if self.on_view_changed is not None:
            self.on_view_changed()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_start_mouse = event.position()
            self.drag_start_pan = QPointF(self.pan.x(), self.pan.y())

    def mouseMoveEvent(self, event) -> None:
        if self.dragging:
            delta = event.position() - self.drag_start_mouse
            self.pan = QPointF(
                self.drag_start_pan.x() + delta.x(),
                self.drag_start_pan.y() + delta.y(),
            )
            self.update()
            if self.on_view_changed is not None:
                self.on_view_changed()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.dragging = False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.app_config = load_app_config()
        self.project_dir: Path | None = None
        self.config = _deep_copy_json_dict(DEFAULT_PROJECT_CONFIG)
        self.project_config = _deep_copy_json_dict(DEFAULT_PROJECT_FILE)
        self._updating_controls = False
        self._recent_project_dirs_max = int(self.app_config.get("recent_project_dirs_max", 10) or 10)
        self._recent_project_dirs = list(self.app_config.get("recent_project_dirs", []))

        window_cfg = self.app_config.get("window", {})
        width = max(1000, int(window_cfg.get("width", 1200) or 1200))
        height = max(640, int(window_cfg.get("height", 760) or 760))
        self.resize(width, height)
        self.setWindowTitle(APP_TITLE)
        set_window_icon(self)
        self.viewer = ViewerWidget()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project Directory:"))
        self.project_combo = QComboBox()
        self.project_combo.setEditable(True)
        project_row.addWidget(self.project_combo, 1)
        self.project_browse_button = QPushButton("Browse...")
        project_row.addWidget(self.project_browse_button)
        self.project_load_button = QPushButton("Load Project")
        project_row.addWidget(self.project_load_button)
        self.project_clear_button = QPushButton("Clear History")
        project_row.addWidget(self.project_clear_button)
        layout.addLayout(project_row)

        svg_row = QHBoxLayout()
        svg_row.addWidget(QLabel("SVG File:"))
        self.svg_combo = QComboBox()
        self.svg_combo.setEditable(True)
        svg_row.addWidget(self.svg_combo, 1)
        self.svg_browse_button = QPushButton("Browse SVG...")
        svg_row.addWidget(self.svg_browse_button)
        self.svg_load_button = QPushButton("Load SVG")
        svg_row.addWidget(self.svg_load_button)
        layout.addLayout(svg_row)

        self.project_status = QLabel("Select a project directory to start.")
        layout.addWidget(self.project_status)

        self.tabs = QTabWidget()
        raster_tab = QWidget()
        raster_layout = QHBoxLayout(raster_tab)
        raster_layout.setContentsMargins(6, 6, 6, 6)
        raster_layout.setSpacing(10)

        raster_layout.addWidget(QLabel("Raster:"))
        self.width_checkbox = QCheckBox("Width")
        raster_layout.addWidget(self.width_checkbox)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 4096)
        raster_layout.addWidget(self.width_spin)

        self.height_checkbox = QCheckBox("Height")
        raster_layout.addWidget(self.height_checkbox)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 4096)
        raster_layout.addWidget(self.height_spin)

        raster_layout.addWidget(QLabel("BG:"))
        self.bg_color_edit = QLineEdit()
        self.bg_color_edit.setMaxLength(16)
        self.bg_color_edit.setFixedWidth(90)
        raster_layout.addWidget(self.bg_color_edit)

        self.bg_pick_button = QPushButton("Pick")
        raster_layout.addWidget(self.bg_pick_button)

        self.transparent_tint_checkbox = QCheckBox("Tint Transparent")
        raster_layout.addWidget(self.transparent_tint_checkbox)

        self.transparent_tint_color_edit = QLineEdit()
        self.transparent_tint_color_edit.setMaxLength(16)
        self.transparent_tint_color_edit.setFixedWidth(90)
        raster_layout.addWidget(self.transparent_tint_color_edit)

        self.transparent_tint_pick_button = QPushButton("Pick Tint")
        raster_layout.addWidget(self.transparent_tint_pick_button)
        raster_layout.addWidget(QLabel("Thresh:"))
        self.transparent_tint_threshold_spin = QSpinBox()
        self.transparent_tint_threshold_spin.setRange(0, 255)
        raster_layout.addWidget(self.transparent_tint_threshold_spin)
        raster_layout.addStretch(1)

        svg_tab = QWidget()
        svg_layout = QHBoxLayout(svg_tab)
        svg_layout.setContentsMargins(6, 6, 6, 6)
        svg_layout.setSpacing(10)
        svg_layout.addWidget(QLabel("SVG:"))
        self.show_line_angles_checkbox = QCheckBox("Show Line Angles")
        svg_layout.addWidget(self.show_line_angles_checkbox)
        svg_layout.addWidget(QLabel("Text:"))
        self.angle_text_color_edit = QLineEdit()
        self.angle_text_color_edit.setMaxLength(16)
        self.angle_text_color_edit.setFixedWidth(90)
        svg_layout.addWidget(self.angle_text_color_edit)
        self.angle_text_pick_button = QPushButton("Pick")
        svg_layout.addWidget(self.angle_text_pick_button)
        svg_layout.addWidget(QLabel("Size:"))
        self.angle_text_size_spin = QSpinBox()
        self.angle_text_size_spin.setRange(6, 64)
        svg_layout.addWidget(self.angle_text_size_spin)
        svg_layout.addWidget(QLabel("Decimals:"))
        self.angle_text_decimals_spin = QSpinBox()
        self.angle_text_decimals_spin.setRange(0, 4)
        svg_layout.addWidget(self.angle_text_decimals_spin)
        svg_layout.addStretch(1)

        self.tabs.addTab(raster_tab, "Raster")
        self.tabs.addTab(svg_tab, "Angles")

        layout.addWidget(self.tabs)
        layout.addWidget(self.viewer, 1)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(POLL_MS)
        logger.info("Polling started: every %d ms", POLL_MS)

        self.view_save_timer = QTimer(self)
        self.view_save_timer.setSingleShot(True)
        self.view_save_timer.timeout.connect(self._save_view_settings)
        self.viewer.on_view_changed = self._schedule_view_save

        self.project_browse_button.clicked.connect(self._browse_project_dir)
        self.project_load_button.clicked.connect(self._load_project_from_combo)
        self.project_clear_button.clicked.connect(self._clear_recent_project_history)
        self.project_combo.textActivated.connect(self._on_project_combo_selected)
        self.svg_browse_button.clicked.connect(self._browse_svg_file)
        self.svg_load_button.clicked.connect(self._load_svg_from_combo)
        self.svg_combo.textActivated.connect(self._on_svg_combo_selected)

        self.width_checkbox.toggled.connect(lambda _checked: self._on_lock_toggled("width"))
        self.height_checkbox.toggled.connect(lambda _checked: self._on_lock_toggled("height"))
        self.width_spin.valueChanged.connect(self._on_values_changed)
        self.height_spin.valueChanged.connect(self._on_values_changed)
        self.bg_color_edit.editingFinished.connect(self._on_bg_changed)
        self.bg_pick_button.clicked.connect(self._on_pick_bg_color)
        self.transparent_tint_checkbox.toggled.connect(self._on_transparent_tint_changed)
        self.transparent_tint_color_edit.editingFinished.connect(self._on_transparent_tint_changed)
        self.transparent_tint_pick_button.clicked.connect(self._on_pick_transparent_tint_color)
        self.transparent_tint_threshold_spin.valueChanged.connect(self._on_transparent_tint_changed)
        self.show_line_angles_checkbox.toggled.connect(self._on_svg_options_changed)
        self.angle_text_color_edit.editingFinished.connect(self._on_svg_options_changed)
        self.angle_text_pick_button.clicked.connect(self._on_pick_angle_text_color)
        self.angle_text_size_spin.valueChanged.connect(self._on_svg_options_changed)
        self.angle_text_decimals_spin.valueChanged.connect(self._on_svg_options_changed)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._refresh_project_dropdown()
        self._refresh_svg_dropdown([])
        self._apply_project_config_to_ui(force=False)

        if self._recent_project_dirs:
            self.project_combo.setCurrentText(self._recent_project_dirs[0])
            self._load_project_dir(Path(self._recent_project_dirs[0]))
        else:
            self.viewer.reload_if_changed(force=True)

    def _refresh_project_dropdown(self) -> None:
        current = self.project_combo.currentText().strip()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems(self._recent_project_dirs)
        self.project_combo.blockSignals(False)
        if current:
            self.project_combo.setCurrentText(current)

    def _refresh_svg_dropdown(self, values: list[str]) -> None:
        current = self.svg_combo.currentText().strip()
        self.svg_combo.blockSignals(True)
        self.svg_combo.clear()
        self.svg_combo.addItems(values)
        self.svg_combo.blockSignals(False)
        if current:
            self.svg_combo.setCurrentText(current)

    def _current_svg_rel(self) -> str:
        return str(self.project_config.get("current_svg", "") or "").strip().replace("\\", "/")

    def _default_svg_dimensions(self, svg_rel: str) -> tuple[int, int]:
        if self.project_dir is None or not svg_rel:
            return DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT

        svg_path = (self.project_dir / Path(svg_rel)).resolve()
        if not svg_path.is_file():
            return DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT

        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            return DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT

        view_box = renderer.viewBoxF()
        if not view_box.isEmpty():
            width = max(1, round(view_box.width()))
            height = max(1, round(view_box.height()))
            return width, height

        default_size = renderer.defaultSize()
        width = max(1, int(default_size.width() or DEFAULT_RENDER_WIDTH))
        height = max(1, int(default_size.height() or DEFAULT_RENDER_HEIGHT))
        return width, height

    def _load_svg_state(self, svg_rel: str) -> dict[str, ConfigValue]:
        svg_rel = str(svg_rel or "").strip().replace("\\", "/")
        settings = self.project_config.get("svg_settings", {})
        if not isinstance(settings, dict):
            settings = {}
            self.project_config["svg_settings"] = settings
        had_existing_settings = svg_rel in settings
        raw = settings.get(svg_rel, {}) if svg_rel else {}
        cfg = _normalize_svg_config(raw if isinstance(raw, dict) else {})
        if svg_rel and not had_existing_settings:
            width, height = self._default_svg_dimensions(svg_rel)
            cfg["raster_width"] = width
            cfg["raster_height"] = height
        if svg_rel:
            settings[svg_rel] = cfg
        return cfg

    def _save_current_svg_state(self) -> None:
        svg_rel = self._current_svg_rel()
        if not svg_rel:
            return
        settings = self.project_config.get("svg_settings", {})
        if not isinstance(settings, dict):
            settings = {}
            self.project_config["svg_settings"] = settings
        settings[svg_rel] = _normalize_svg_config(self.config)

    def _persist_app_config(self) -> None:
        self.app_config["window"] = {
            "width": max(self.width(), 1000),
            "height": max(self.height(), 640),
        }
        self.app_config["recent_project_dirs_max"] = int(self._recent_project_dirs_max)
        self.app_config["recent_project_dirs"] = list(self._recent_project_dirs[: self._recent_project_dirs_max])
        save_app_config(self.app_config)

    def _remember_project_dir(self, project_dir: Path) -> None:
        project_text = _norm_dir(str(project_dir))
        items = [project_text] + [p for p in self._recent_project_dirs if p != project_text]
        items = _dedupe_keep_order(items)
        items = _filter_existing_dirs(items)
        self._recent_project_dirs = items[: self._recent_project_dirs_max]
        self._refresh_project_dropdown()
        self._persist_app_config()

    def _clear_recent_project_history(self) -> None:
        ok = QMessageBox.question(
            self,
            APP_TITLE,
            "Clear recent project history?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        self._recent_project_dirs = []
        self._refresh_project_dropdown()
        self._persist_app_config()
        self.project_status.setText("Recent project history cleared.")

    def _list_project_svgs(self, project_dir: Path) -> list[str]:
        out: list[str] = []
        for path in project_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() == ".svg":
                out.append(path.relative_to(project_dir).as_posix())
        out.sort(key=str.casefold)
        return out

    def _set_current_svg_rel(self, svg_rel: str) -> None:
        global CURRENT_SVG_PATH
        svg_rel = str(svg_rel or "").strip().replace("\\", "/")
        self.project_config["current_svg"] = svg_rel
        if self.project_dir is None or not svg_rel:
            CURRENT_SVG_PATH = None
            self.svg_combo.setCurrentText(svg_rel)
            return
        CURRENT_SVG_PATH = (self.project_dir / Path(svg_rel)).resolve()
        self.svg_combo.setCurrentText(svg_rel)

    def _load_project_dir(self, project_dir: Path) -> None:
        global CURRENT_PROJECT_DIR, CURRENT_PROJECT_CONFIG_PATH

        if self.project_dir is not None:
            self._persist_project_config()

        project_dir = project_dir.expanduser().resolve()
        if not project_dir.is_dir():
            QMessageBox.critical(self, APP_TITLE, f"Project directory does not exist:\n{project_dir}")
            return

        self.project_dir = project_dir
        CURRENT_PROJECT_DIR = project_dir
        CURRENT_PROJECT_CONFIG_PATH = project_config_path_for_dir(project_dir)
        self.project_combo.setCurrentText(str(project_dir))
        self._remember_project_dir(project_dir)

        self.project_config = load_project_config(project_dir)
        svg_values = self._list_project_svgs(project_dir)
        self._refresh_svg_dropdown(svg_values)

        desired_svg = str(self.project_config.get("current_svg", "") or "")
        if desired_svg not in svg_values:
            desired_svg = svg_values[0] if svg_values else ""
        self._set_current_svg_rel(desired_svg)
        self.config = self._load_svg_state(desired_svg)

        self._apply_project_config_to_ui(force=True)
        self.project_status.setText(
            f"Loaded project: {project_dir} ({len(svg_values)} SVG{'s' if len(svg_values) != 1 else ''})"
        )

    def _apply_project_config_to_ui(self, force: bool) -> None:
        self._updating_controls = True
        try:
            self.width_checkbox.setChecked(bool(self.config["width_locked"]))
            self.height_checkbox.setChecked(bool(self.config["height_locked"]))
            if not self.width_checkbox.isChecked() and not self.height_checkbox.isChecked():
                self.height_checkbox.setChecked(True)
            self.width_spin.setValue(int(self.config["raster_width"]))
            self.height_spin.setValue(int(self.config["raster_height"]))
            self.bg_color_edit.setText(str(self.config["bg_color"]))
            self.transparent_tint_checkbox.setChecked(bool(self.config["transparent_tint_enabled"]))
            self.transparent_tint_color_edit.setText(str(self.config["transparent_tint_color"]))
            self.transparent_tint_threshold_spin.setValue(int(self.config["transparent_tint_threshold"]))
            self.show_line_angles_checkbox.setChecked(bool(self.config["show_line_angles"]))
            self.angle_text_color_edit.setText(str(self.config["angle_text_color"]))
            self.angle_text_size_spin.setValue(int(self.config["angle_text_size"]))
            self.angle_text_decimals_spin.setValue(int(self.config["angle_text_decimals"]))
            self.tabs.setCurrentIndex(int(self.config.get("active_tab_index", 0)))
        finally:
            self._updating_controls = False

        self.viewer.set_view_transform(
            float(self.config["zoom"]),
            float(self.config["pan_x"]),
            float(self.config["pan_y"]),
        )
        self.viewer.set_view_mode(self.tabs.currentIndex() == 1)
        self._apply_controls_to_viewer(force=force, persist=False)

    def _browse_project_dir(self) -> None:
        initial = self.project_combo.currentText().strip()
        if not initial and self._recent_project_dirs:
            initial = self._recent_project_dirs[0]
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Project Directory",
            initial if Path(initial).is_dir() else str(APP_DIR),
        )
        if chosen:
            self.project_combo.setCurrentText(str(Path(chosen).resolve()))
            self._load_project_from_combo()

    def _load_project_from_combo(self) -> None:
        project_text = self.project_combo.currentText().strip()
        if not project_text:
            QMessageBox.critical(self, APP_TITLE, "Project directory is missing.")
            return
        self._load_project_dir(Path(project_text))

    def _on_project_combo_selected(self, value: str) -> None:
        if value:
            self.project_combo.setCurrentText(value)
            self._load_project_from_combo()

    def _browse_svg_file(self) -> None:
        if self.project_dir is None:
            QMessageBox.critical(self, APP_TITLE, "Load a project directory first.")
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select SVG File",
            str(self.project_dir),
            "SVG Files (*.svg)",
        )
        if not chosen:
            return
        chosen_path = Path(chosen).resolve()
        try:
            rel_path = chosen_path.relative_to(self.project_dir).as_posix()
        except ValueError:
            QMessageBox.critical(
                self,
                APP_TITLE,
                f"SVG must be inside the current project directory:\n{self.project_dir}",
            )
            return
        self.svg_combo.setCurrentText(rel_path)
        self._load_svg_from_combo()

    def _load_svg_from_combo(self) -> None:
        if self.project_dir is None:
            QMessageBox.critical(self, APP_TITLE, "Load a project directory first.")
            return
        self._save_current_svg_state()
        svg_text = self.svg_combo.currentText().strip()
        if not svg_text:
            self._set_current_svg_rel("")
            self.config = _deep_copy_json_dict(DEFAULT_PROJECT_CONFIG)
            self.viewer.reload_if_changed(force=True)
            self._persist_project_config()
            return

        svg_path = (self.project_dir / Path(svg_text)).resolve()
        if not svg_path.is_file():
            QMessageBox.critical(self, APP_TITLE, f"SVG file does not exist:\n{svg_path}")
            return
        try:
            rel_path = svg_path.relative_to(self.project_dir).as_posix()
        except ValueError:
            rel_path = svg_text.replace("\\", "/")

        svg_values = self._list_project_svgs(self.project_dir)
        if rel_path not in svg_values:
            svg_values = _dedupe_keep_order([rel_path] + svg_values)
            self._refresh_svg_dropdown(svg_values)
        self._set_current_svg_rel(rel_path)
        self.config = self._load_svg_state(rel_path)
        self._apply_project_config_to_ui(force=False)
        self.viewer.reload_if_changed(force=True)
        self._persist_project_config()
        self.project_status.setText(f"Loaded SVG: {rel_path}")

    def _on_svg_combo_selected(self, value: str) -> None:
        if value:
            self.svg_combo.setCurrentText(value)
            self._load_svg_from_combo()

    def _persist_project_config(self) -> None:
        if self.project_dir is None:
            return
        self.config["active_tab_index"] = int(self.tabs.currentIndex())
        self._save_current_svg_state()
        save_project_config(self.project_dir, self.project_config)

    def _tick(self) -> None:
        self.viewer.reload_if_changed(force=False)

    def _on_lock_toggled(self, changed: str) -> None:
        if self._updating_controls:
            return

        width_checked = self.width_checkbox.isChecked()
        height_checked = self.height_checkbox.isChecked()
        if not width_checked and not height_checked:
            self._updating_controls = True
            try:
                if changed == "width":
                    self.height_checkbox.setChecked(True)
                else:
                    self.width_checkbox.setChecked(True)
            finally:
                self._updating_controls = False

        self._apply_controls_to_viewer(force=True)

    def _on_values_changed(self, _value: int) -> None:
        if self._updating_controls:
            return
        self._apply_controls_to_viewer(force=True)

    def _apply_controls_to_viewer(self, force: bool, persist: bool = True) -> None:
        bg_color = self.bg_color_edit.text().strip() or DEFAULT_BG_COLOR
        if not QColor(bg_color).isValid():
            logger.error("Rejected invalid BG color from controls: %s", bg_color)
            bg_color = DEFAULT_BG_COLOR
            self._updating_controls = True
            try:
                self.bg_color_edit.setText(bg_color)
            finally:
                self._updating_controls = False

        transparent_tint_color = (
            self.transparent_tint_color_edit.text().strip()
            or DEFAULT_TRANSPARENT_TINT_COLOR
        )
        if not QColor(transparent_tint_color).isValid():
            logger.error(
                "Rejected invalid transparent tint color from controls: %s",
                transparent_tint_color,
            )
            transparent_tint_color = DEFAULT_TRANSPARENT_TINT_COLOR
            self._updating_controls = True
            try:
                self.transparent_tint_color_edit.setText(transparent_tint_color)
            finally:
                self._updating_controls = False

        angle_text_color = self.angle_text_color_edit.text().strip() or DEFAULT_ANGLE_TEXT_COLOR
        if not QColor(angle_text_color).isValid():
            logger.error("Rejected invalid angle text color from controls: %s", angle_text_color)
            angle_text_color = DEFAULT_ANGLE_TEXT_COLOR
            self._updating_controls = True
            try:
                self.angle_text_color_edit.setText(angle_text_color)
            finally:
                self._updating_controls = False

        self.config = {
            **self.config,
            "raster_width": self.width_spin.value(),
            "raster_height": self.height_spin.value(),
            "width_locked": self.width_checkbox.isChecked(),
            "height_locked": self.height_checkbox.isChecked(),
            "bg_color": QColor(bg_color).name(),
            "transparent_tint_enabled": self.transparent_tint_checkbox.isChecked(),
            "transparent_tint_color": QColor(transparent_tint_color).name(),
            "transparent_tint_threshold": self.transparent_tint_threshold_spin.value(),
            "show_line_angles": self.show_line_angles_checkbox.isChecked(),
            "angle_text_color": QColor(angle_text_color).name(),
            "angle_text_size": self.angle_text_size_spin.value(),
            "angle_text_decimals": self.angle_text_decimals_spin.value(),
            "zoom": float(self.viewer.zoom),
            "pan_x": float(self.viewer.pan.x()),
            "pan_y": float(self.viewer.pan.y()),
            "active_tab_index": int(self.tabs.currentIndex()),
        }
        if persist:
            self._persist_project_config()
        self.viewer.set_bg_color(str(self.config["bg_color"]))
        self.viewer.set_transparent_tint(
            bool(self.config["transparent_tint_enabled"]),
            str(self.config["transparent_tint_color"]),
            int(self.config["transparent_tint_threshold"]),
        )
        self.viewer.set_show_line_angles(bool(self.show_line_angles_checkbox.isChecked()))
        self.viewer.set_angle_text_style(
            str(self.config["angle_text_color"]),
            int(self.config["angle_text_size"]),
            int(self.config["angle_text_decimals"]),
        )
        self.viewer.set_raster_options(
            self.width_spin.value(),
            self.height_spin.value(),
            self.width_checkbox.isChecked(),
            self.height_checkbox.isChecked(),
        )
        if force:
            self.viewer.reload_if_changed(force=True)

    def _schedule_view_save(self) -> None:
        self.view_save_timer.start(250)

    def _save_view_settings(self) -> None:
        self.config.update(
            {
                "zoom": float(self.viewer.zoom),
                "pan_x": float(self.viewer.pan.x()),
                "pan_y": float(self.viewer.pan.y()),
                "active_tab_index": int(self.tabs.currentIndex()),
            }
        )
        self._persist_project_config()

    def _on_bg_changed(self) -> None:
        if self._updating_controls:
            return
        self._apply_controls_to_viewer(force=True)

    def _on_pick_bg_color(self) -> None:
        start_color = QColor(self.bg_color_edit.text().strip() or DEFAULT_BG_COLOR)
        color = QColorDialog.getColor(start_color, self, "Pick Background Color")
        if not color.isValid():
            return
        self._updating_controls = True
        try:
            self.bg_color_edit.setText(color.name())
        finally:
            self._updating_controls = False
        self._apply_controls_to_viewer(force=True)

    def _on_transparent_tint_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self._apply_controls_to_viewer(force=True)

    def _on_pick_transparent_tint_color(self) -> None:
        start_color = QColor(
            self.transparent_tint_color_edit.text().strip() or DEFAULT_TRANSPARENT_TINT_COLOR
        )
        color = QColorDialog.getColor(start_color, self, "Pick Transparent Tint Color")
        if not color.isValid():
            return
        self._updating_controls = True
        try:
            self.transparent_tint_color_edit.setText(color.name())
        finally:
            self._updating_controls = False
        self._apply_controls_to_viewer(force=True)

    def _on_svg_options_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self._apply_controls_to_viewer(force=True)

    def _on_pick_angle_text_color(self) -> None:
        start_color = QColor(self.angle_text_color_edit.text().strip() or DEFAULT_ANGLE_TEXT_COLOR)
        color = QColorDialog.getColor(start_color, self, "Pick Angle Text Color")
        if not color.isValid():
            return
        self._updating_controls = True
        try:
            self.angle_text_color_edit.setText(color.name())
        finally:
            self._updating_controls = False
        self._apply_controls_to_viewer(force=True)

    def _on_tab_changed(self, index: int) -> None:
        if self._updating_controls:
            return
        new_svg_mode = index == 1
        old_w, old_h = self.viewer.get_render_size_for_mode(self.viewer.svg_preview_mode)
        new_w, new_h = self.viewer.get_render_size_for_mode(new_svg_mode)
        if old_w > 0 and old_h > 0 and new_w > 0 and new_h > 0:
            # Preserve on-screen physical size across tab modes without enlarging.
            mapped_zoom_w = self.viewer.zoom * (old_w / new_w)
            mapped_zoom_h = self.viewer.zoom * (old_h / new_h)
            mapped_zoom = min(mapped_zoom_w, mapped_zoom_h)
            self.viewer.set_view_transform(
                mapped_zoom,
                self.viewer.pan.x(),
                self.viewer.pan.y(),
            )

        self.viewer.set_view_mode(new_svg_mode)
        self.viewer.reload_if_changed(force=True)
        self.config["active_tab_index"] = int(index)
        self._schedule_view_save()

    def closeEvent(self, event) -> None:
        try:
            self._persist_app_config()
            self._persist_project_config()
        except Exception as exc:
            logger.error("Failed to persist state during close: %s", exc)
        super().closeEvent(event)


def main() -> None:
    set_windows_app_user_model_id(APP_USER_MODEL_ID)
    setup_logging()
    install_exception_hooks()
    log_environment()

    app = QApplication(sys.argv)
    logger.info("QApplication created")
    if app.primaryScreen() is None:
        logger.warning("No primary screen detected. GUI may not be visible.")
    window = MainWindow()
    logger.info("Main window created, size=%sx%s", window.width(), window.height())
    window.show()
    logger.info("Main window show() called")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
