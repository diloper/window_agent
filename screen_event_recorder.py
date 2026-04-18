import cv2
import mss
import json
import signal
import threading
import numpy as np
from datetime import datetime
from pynput import mouse, keyboard
from pathlib import Path


class ScreenEventRecorder:
    """同時錄製螢幕、鍵盤事件、滑鼠座標"""

    def __init__(self, output_dir="recordings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.events = []
        self.recording = False
        self.modifier_state = {
            'ctrl': False,
            'shift': False,
            'alt': False
        }

    def _update_modifier_state(self, key, pressed):
        """更新 Ctrl/Shift/Alt 狀態。"""
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self.modifier_state['ctrl'] = pressed
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self.modifier_state['shift'] = pressed
        elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
            self.modifier_state['alt'] = pressed

    def _extract_raw_key(self, key):
        """回傳原始鍵值字串，保留字元與特殊鍵資訊。"""
        try:
            if key.char is not None:
                return key.char
        except AttributeError:
            pass
        return str(key).split('.')[-1]

    def _normalize_key(self, raw_key):
        """將鍵值正規化，Ctrl 組合鍵統一為 Ctrl+X。"""
        if self.modifier_state['ctrl']:
            if len(raw_key) == 1 and 1 <= ord(raw_key) <= 26:
                return f"Ctrl+{chr(ord(raw_key) + 64)}"
            if len(raw_key) == 1 and raw_key.isprintable():
                return f"Ctrl+{raw_key.upper()}"
        return raw_key

    def record_screen(self, fps=15, duration_seconds=None):
        """錄製螢幕到 MP4"""
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 主螢幕
            frame_size = (monitor['width'], monitor['height'])

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            output_file = self.output_dir / f"screen_{self.timestamp}.mp4"
            out = cv2.VideoWriter(str(output_file), fourcc, fps, frame_size)

            print(f"錄製中... 輸出: {output_file}")
            frame_count = 0

            while self.recording:
                if duration_seconds and frame_count >= fps * duration_seconds:
                    break

                screenshot = sct.grab(monitor)
                frame = cv2.cvtColor(
                    np.array(screenshot),
                    cv2.COLOR_BGRA2BGR
                )
                out.write(frame)
                frame_count += 1

            out.release()
            print(f"螢幕錄影完成: {output_file}")

    def on_key_press(self, key):
        """記錄鍵盤事件"""
        self._update_modifier_state(key, pressed=True)
        raw_key = self._extract_raw_key(key)
        normalized_key = self._normalize_key(raw_key)

        event = {
            'type': 'key_press',
            'key': normalized_key,
            'raw_key': raw_key,
            'normalized_key': normalized_key,
            'modifiers': [k for k, v in self.modifier_state.items() if v],
            'timestamp': datetime.now().isoformat()
        }
        self.events.append(event)
        print(f"按鍵: {normalized_key}")

    def on_key_release(self, key):
        """記錄鍵盤釋放"""
        raw_key = self._extract_raw_key(key)
        normalized_key = self._normalize_key(raw_key)
        event = {
            'type': 'key_release',
            'key': normalized_key,
            'raw_key': raw_key,
            'normalized_key': normalized_key,
            'modifiers': [k for k, v in self.modifier_state.items() if v],
            'timestamp': datetime.now().isoformat()
        }
        self.events.append(event)
        self._update_modifier_state(key, pressed=False)

    def on_mouse_move(self, x, y):
        """記錄滑鼠移動座標"""
        event = {
            'type': 'mouse_move',
            'x': x,
            'y': y,
            'timestamp': datetime.now().isoformat()
        }
        self.events.append(event)

    def on_mouse_click(self, x, y, button, pressed):
        """記錄滑鼠點擊與座標"""
        event = {
            'type': 'mouse_press' if pressed else 'mouse_release',
            'button': str(button).split('.')[-1],
            'x': x,
            'y': y,
            'timestamp': datetime.now().isoformat()
        }
        self.events.append(event)
        if pressed:
            print(f"滑鼠點擊: {button} at ({x}, {y})")

    def start_recording(self, duration_seconds=30):
        """開始同時錄製螢幕與事件"""
        self.recording = True
        self.events = []
        self.modifier_state = {'ctrl': False, 'shift': False, 'alt': False}

        # 啟動螢幕錄製執行緒
        screen_thread = threading.Thread(
            target=self.record_screen,
            args=(15, duration_seconds)
        )
        screen_thread.daemon = True
        screen_thread.start()

        # 錄製期間暫時忽略 Ctrl+C 導致的 SIGINT，避免中斷錄製流程。
        previous_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            # 啟動事件監聽器
            with keyboard.Listener(
                on_press=self.on_key_press,
                on_release=self.on_key_release
            ) as key_listener:
                with mouse.Listener(
                    on_move=None,
                    on_click=self.on_mouse_click
                ) as mouse_listener:
                    screen_thread.join(timeout=duration_seconds + 2)
                    self.recording = False
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)

        # 保存事件日誌
        events_file = self.output_dir / f"events_{self.timestamp}.json"
        with open(events_file, 'w', encoding='utf-8') as f:
            json.dump(self.events, f, indent=2, ensure_ascii=False)
        print(f"事件記錄已保存: {events_file}")

    def stop_recording(self):
        """停止錄製"""
        self.recording = False


if __name__ == "__main__":
    # 範例：錄製 30 秒
    recorder = ScreenEventRecorder()
    recorder.start_recording(duration_seconds=30)
