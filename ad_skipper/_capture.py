"""Shared screen-capture, coordinate-mapping and cursor-preserving click helpers.

Used by both ``collect_ad_frames.py`` (Phase 1 harvest) and
``youtube_ad_skipper.py`` (Phase 5 runtime) so that the capture path is
*identical* between training-data collection and inference. Keeping them in
one module guarantees the domain-match requirement (#2/#12 in the plan).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

try:
    import mss
except Exception as exc:  # pragma: no cover - dependency guard
    raise RuntimeError("mss is required for screen capture: pip install mss") from exc

try:
    import cv2
except Exception as exc:  # pragma: no cover - dependency guard
    raise RuntimeError("opencv-python is required: pip install opencv-python") from exc


@dataclass(frozen=True)
class BBox:
    """Axis-aligned box in image pixel coordinates (top-left origin)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def to_yolo(self, img_w: int, img_h: int) -> Tuple[float, float, float, float]:
        """Return normalized (cx, cy, w, h) clamped to [0, 1]."""
        if img_w <= 0 or img_h <= 0:
            raise ValueError("image dimensions must be positive")
        cx, cy = self.center
        nx = min(max(cx / img_w, 0.0), 1.0)
        ny = min(max(cy / img_h, 0.0), 1.0)
        nw = min(max(self.w / img_w, 0.0), 1.0)
        nh = min(max(self.h / img_h, 0.0), 1.0)
        return nx, ny, nw, nh


class ScreenCapture:
    """Thin wrapper around a persistent ``mss`` instance.

    A single ``mss.MSS`` handle is reused for the lifetime of the object to
    avoid the per-grab setup cost. Not thread-safe; create one per thread.
    """

    def __init__(self, monitor_index: int = 1) -> None:
        self._sct = mss.mss()
        monitors = self._sct.monitors
        if monitor_index < 0 or monitor_index >= len(monitors):
            raise ValueError(
                f"monitor_index {monitor_index} out of range "
                f"(0..{len(monitors) - 1})"
            )
        self._monitor_index = monitor_index
        self._monitor = monitors[monitor_index]

    @property
    def monitor(self) -> dict:
        return self._monitor

    def grab(self) -> np.ndarray:
        """Capture the selected monitor as a BGR ``np.ndarray``."""
        shot = self._sct.grab(self._monitor)
        return cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)

    def monitor_offset(self) -> Tuple[int, int]:
        """Top-left screen coordinate of the captured monitor."""
        return int(self._monitor["left"]), int(self._monitor["top"])

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def viewport_rect_to_image_bbox(
    rect: dict,
    window_rect: dict,
    toolbar_height: float,
    device_pixel_ratio: float,
    monitor_left: int,
    monitor_top: int,
) -> BBox:
    """Map a Selenium ``element.rect`` (CSS px, viewport-relative) to a box in
    the *captured image* pixel space.

    The captured image originates at ``(monitor_left, monitor_top)`` in screen
    space, so the monitor offset is subtracted after scaling to device pixels.
    """
    screen_x = (window_rect["x"] + rect["x"]) * device_pixel_ratio
    screen_y = (window_rect["y"] + toolbar_height + rect["y"]) * device_pixel_ratio
    w = rect["width"] * device_pixel_ratio
    h = rect["height"] * device_pixel_ratio
    return BBox(x=screen_x - monitor_left, y=screen_y - monitor_top, w=w, h=h)


def image_point_to_screen(
    cx: float,
    cy: float,
    monitor_left: int,
    monitor_top: int,
) -> Tuple[int, int]:
    """Convert a point in captured-image pixels back to absolute screen px."""
    return int(round(cx + monitor_left)), int(round(cy + monitor_top))


def draw_bbox(image: np.ndarray, bbox: BBox, label: str = "skip") -> np.ndarray:
    """Return a copy of ``image`` with ``bbox`` drawn, for --draw QA."""
    out = image.copy()
    x1, y1 = int(bbox.x), int(bbox.y)
    x2, y2 = int(bbox.x + bbox.w), int(bbox.y + bbox.h)
    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.putText(
        out, label, (x1, max(0, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA,
    )
    return out


def cursor_preserving_click(x: int, y: int) -> None:
    """Click at absolute screen ``(x, y)`` then restore the user's cursor.

    Honors the non-interference constraint at runtime: the physical mouse is
    returned to its original position after the click so the user is not
    disrupted. Prefers ``pydirectinput`` (SendInput) and falls back to
    ``pyautogui``.
    """
    orig: Optional[Tuple[int, int]] = None
    try:
        import pydirectinput  # type: ignore

        try:
            orig = pydirectinput.position()
        except Exception:
            orig = None
        pydirectinput.moveTo(x, y)
        pydirectinput.click()
        if orig is not None:
            pydirectinput.moveTo(orig[0], orig[1])
        return
    except Exception:
        pass

    import pyautogui  # type: ignore

    pyautogui.FAILSAFE = False
    try:
        orig = pyautogui.position()
    except Exception:
        orig = None
    pyautogui.click(x, y)
    if orig is not None:
        pyautogui.moveTo(orig[0], orig[1])
