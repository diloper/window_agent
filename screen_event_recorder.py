import cv2
import mss
import json
import queue
import signal
import threading
import time
import numpy as np
from datetime import datetime
from pynput import mouse, keyboard
from pathlib import Path
import argparse


class ScreenEventRecorder:
    """同時錄製螢幕、鍵盤事件、滑鼠座標"""

    def __init__(self, output_dir="recordings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.timestamp = ""
        self.recording = False
        self.record_start_monotonic = None
        self.events_file_path = None
        self.frames_file_path = None
        self._events_fp = None
        self._frames_fp = None
        self._events_write_count = 0
        self._frames_write_count = 0
        self._event_queue = None
        self._event_queue_sentinel = object()
        self._event_queue_max_depth = 0
        self._event_drop_count = 0
        self._event_enqueued_count = 0
        self._event_written_count = 0
        self._event_writer_thread = None
        self._frame_queue = None
        self._frame_queue_max_depth = 0
        self._frame_drop_count = 0
        self._frame_capture_count = 0
        self._frame_written_count = 0
        self._frame_queue_sentinel = object()
        self._sync_marker_end_emitted = False
        self.modifier_state = {
            'ctrl': False,
            'shift': False,
            'alt': False
        }

    def _apply_sync_marker(self, frame, rel_ts, sync_marker_seconds):
        """在影格左上角繪製視覺同步標記（紅色實心矩形）。

        同步標記的用途
        --------------
        同步標記同時出現在兩個地方：
          1. **影片畫面**：前 sync_marker_ms 毫秒的每一幀左上角都有紅色方塊。
          2. **事件日誌**：錄影起始寫入 sync_marker_start（timestamp=0.0），
             結束後寫入 sync_marker_end（timestamp=elapsed）。

        透過比對「影片中紅色方塊首次消失的時間點」與
        「events JSON 中 sync_marker_end.timestamp」，
        可校驗影片時間軸與事件時間軸的對齊誤差。
        若兩者差距 > 1 個影格週期（≈67ms @15fps），表示存在 I/O 延遲或掉幀。

        視覺規格
        --------
        - 顏色：BGR (0, 0, 255) = 純紅，邊框 BGR (255, 255, 255) = 白色 2px
        - 位置：固定於左上角 (12, 12)，遠離典型 UI 元素，不干擾標註區域
        - 尺寸：寬=畫面寬 × 8%（最小 40px），高=畫面高 × 6%（最小 30px）
          → 在 1920×1080 解析度約為 153×64px，目視明顯可辨

        Args:
            frame: BGR numpy array，來自 cv2.cvtColor(mss_screenshot, BGRA2BGR)。
            rel_ts: 當前影格的相對時間戳（秒，monotonic clock）。
            sync_marker_seconds: 標記顯示的持續秒數（= sync_marker_ms / 1000）。
                                  ≤ 0 表示停用標記，直接返回原始影格。

        Returns:
            繪製標記後的影格（in-place 修改並返回）；
            若不在標記期間則直接返回未修改的原始影格。
        """
        # sync_marker_seconds <= 0 表示使用者以 --sync-marker-ms 0 停用標記
        # rel_ts > sync_marker_seconds 表示標記期間已過，不再繪製
        if sync_marker_seconds <= 0 or rel_ts > sync_marker_seconds:
            return frame

        h, w = frame.shape[:2]
        # 標記寬高按比例縮放，確保在不同解析度下都清晰可見
        marker_w = max(40, int(w * 0.08))  # 最小 40px，避免低解析度下過小
        marker_h = max(30, int(h * 0.06))  # 最小 30px
        x1, y1 = 12, 12  # 距畫面邊緣 12px，避免被視窗邊框裁切
        x2, y2 = min(w - 1, x1 + marker_w), min(h - 1, y1 + marker_h)

        # 第一層：純紅實心填充（thickness=-1），高對比，利於機器視覺偵測
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), thickness=-1)
        # 第二層：白色邊框，在深色桌面背景下仍保持可見度
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), thickness=2)
        return frame

    def _relative_timestamp(self):
        if self.record_start_monotonic is None:
            return 0.0
        return round(time.perf_counter() - self.record_start_monotonic, 6)

    def _write_event(self, payload):
        if self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait(payload)
            self._event_enqueued_count += 1
            self._event_queue_max_depth = max(self._event_queue_max_depth, self._event_queue.qsize())
        except queue.Full:
            self._event_drop_count += 1

    def _enqueue_event_sentinel(self):
        if self._event_queue is None:
            return
        for _ in range(20):
            try:
                self._event_queue.put_nowait(self._event_queue_sentinel)
                return
            except queue.Full:
                time.sleep(0.01)

    def _event_writer_loop(self):
        if self._events_fp is None:
            return
        while True:
            if self._event_queue is None:
                return

            try:
                item = self._event_queue.get(timeout=0.2)
            except queue.Empty:
                if not self.recording and self._event_queue.empty():
                    return
                continue

            if item is self._event_queue_sentinel:
                return

            line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            self._events_fp.write(line + "\n")
            self._events_write_count += 1
            self._event_written_count += 1
            if self._events_write_count % 20 == 0:
                self._events_fp.flush()

    def _write_frame_timestamp(self, frame_index, timestamp):
        if self._frames_fp is None:
            return
        payload = {
            'frame_index': frame_index,
            'timestamp': timestamp,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._frames_fp.write(line + "\n")
        self._frames_write_count += 1
        if self._frames_write_count % 60 == 0:
            self._frames_fp.flush()

    def _enqueue_frame_sentinel(self):
        if self._frame_queue is None:
            return
        for _ in range(20):
            try:
                self._frame_queue.put_nowait(self._frame_queue_sentinel)
                return
            except queue.Full:
                time.sleep(0.01)

    def _capture_screen_frames(self, fps, duration_seconds, monitor, sync_marker_seconds):
        frame_interval = 1.0 / max(1, fps)
        target_frame_count = int(fps * duration_seconds) if duration_seconds else None

        with mss.mss() as sct:
            while self.recording:
                if target_frame_count is not None and self._frame_capture_count >= target_frame_count:
                    break

                loop_start = time.perf_counter()
                screenshot = sct.grab(monitor)
                frame = cv2.cvtColor(
                    np.array(screenshot),
                    cv2.COLOR_BGRA2BGR
                )
                rel_ts = self._relative_timestamp()
                frame = self._apply_sync_marker(frame, rel_ts, sync_marker_seconds)
                packet = (self._frame_capture_count, rel_ts, frame)

                if self._frame_queue is not None:
                    try:
                        self._frame_queue.put_nowait(packet)
                        self._frame_queue_max_depth = max(self._frame_queue_max_depth, self._frame_queue.qsize())
                    except queue.Full:
                        self._frame_drop_count += 1

                self._frame_capture_count += 1

                elapsed = time.perf_counter() - loop_start
                sleep_s = frame_interval - elapsed
                if sleep_s > 0:
                    time.sleep(sleep_s)

        self.recording = False
        if sync_marker_seconds > 0 and not self._sync_marker_end_emitted:
            self._write_event(
                {
                    'type': 'sync_marker_end',
                    'timestamp': min(sync_marker_seconds, self._relative_timestamp()),
                }
            )
            self._sync_marker_end_emitted = True
        self._enqueue_frame_sentinel()

    def _write_screen_frames(self, output_file, fps, frame_size):
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_file), fourcc, fps, frame_size)
        print(f"錄製中... 輸出: {output_file}")

        try:
            while True:
                if self._frame_queue is None:
                    break

                try:
                    item = self._frame_queue.get(timeout=0.2)
                except queue.Empty:
                    if not self.recording and self._frame_queue.empty():
                        break
                    continue

                if item is self._frame_queue_sentinel:
                    break

                frame_index, rel_ts, frame = item
                out.write(frame)
                self._write_frame_timestamp(frame_index, rel_ts)
                self._frame_written_count += 1
        finally:
            out.release()
            print(f"螢幕錄影完成: {output_file}")

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

    def record_screen(self, fps=15, duration_seconds=None, sync_marker_ms=300):
        """以 producer-consumer 方式錄製螢幕到 MP4。

        Args:
            fps: 目標錄製幀率（預設 15fps）。
            duration_seconds: 錄製秒數；None 表示持續到 recording=False。
            sync_marker_ms: 視覺同步標記的持續毫秒數（預設 300ms）。
                            轉換為秒後傳遞給 _capture_screen_frames 與
                            _apply_sync_marker，控制影片畫面上紅色方塊
                            的顯示時長。設為 0 可完全停用視覺標記。
        """
        # 將毫秒轉換為秒，供後續按時間比較使用（rel_ts 單位為秒）
        # max(0.0, ...) 確保負值輸入不會造成邏輯異常
        sync_marker_seconds = max(0.0, sync_marker_ms / 1000.0)
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 主螢幕
        frame_size = (monitor['width'], monitor['height'])
        output_file = self.output_dir / f"screen_{self.timestamp}.mp4"

        self._frame_queue = queue.Queue(maxsize=max(30, fps * 3))
        self._frame_queue_max_depth = 0
        self._frame_drop_count = 0
        self._frame_capture_count = 0
        self._frame_written_count = 0

        writer_thread = threading.Thread(
            target=self._write_screen_frames,
            args=(output_file, fps, frame_size),
            daemon=True,
        )
        writer_thread.start()

        self._capture_screen_frames(fps, duration_seconds, monitor, sync_marker_seconds)
        writer_thread.join(timeout=5)

    def on_key_press(self, key):
        """記錄鍵盤事件"""
        self._update_modifier_state(key, pressed=True)
        raw_key = self._extract_raw_key(key)
        normalized_key = self._normalize_key(raw_key)

        event = {
            'type': 'key_press',
            'key': normalized_key,
            'timestamp': self._relative_timestamp()
        }
        self._write_event(event)
        print(f"按鍵: {normalized_key}")

    def on_key_release(self, key):
        """記錄鍵盤釋放"""
        raw_key = self._extract_raw_key(key)
        normalized_key = self._normalize_key(raw_key)
        event = {
            'type': 'key_release',
            'key': normalized_key,
            'timestamp': self._relative_timestamp()
        }
        self._write_event(event)
        self._update_modifier_state(key, pressed=False)

    def on_mouse_move(self, x, y):
        """記錄滑鼠移動座標"""
        event = {
            'type': 'mouse_move',
            'x': x,
            'y': y,
            'timestamp': self._relative_timestamp()
        }
        self._write_event(event)

    def on_mouse_click(self, x, y, button, pressed):
        """記錄滑鼠點擊與座標"""
        event = {
            'type': 'mouse_press' if pressed else 'mouse_release',
            'button': str(button).split('.')[-1],
            'x': x,
            'y': y,
            'timestamp': self._relative_timestamp()
        }
        self._write_event(event)
        if pressed:
            print(f"滑鼠點擊: {button} at ({x}, {y})")

    def start_recording(self, duration_seconds=60, countdown_seconds=5, sync_marker_ms=300):
        """開始同時錄製螢幕與事件。

        sync_marker_ms 參數說明
        -----------------------
        同步標記（sync marker）是音視頻對齊的校準參考點，運作機制如下：

        1. **事件端**（events_*.json）：
           - 錄影啟動後立即寫入 ``sync_marker_start``，timestamp 固定為 0.0，
             代表錄影基準時刻。
           - 經過 sync_marker_ms 毫秒後由影格擷取執行緒寫入 ``sync_marker_end``，
             timestamp 為實際經過的相對秒數（應接近 sync_marker_ms/1000）。

        2. **影片端**（screen_*.mp4）：
           - 前 sync_marker_ms 毫秒內的每一幀左上角都繪製紅色方塊。
           - 可用影片播放器或 cv2.VideoCapture 逐幀搜尋「紅色方塊消失的幀」，
             即可得到影片時間軸上的對應時間點。

        3. **對齊校驗**：
           - 比較兩端的結束時間點，差距應 < 1 個影格週期（≈67ms @15fps）。
           - 若差距過大，表示影格寫入佇列存在積壓延遲。

        Args:
            duration_seconds: 錄製總時長（秒，預設 60）。
            countdown_seconds: 錄製前倒數秒數（預設 5）。
            sync_marker_ms: 同步標記持續毫秒數（預設 300ms）。
                            - 建議值：200–500ms（太短可能被掉幀跳過，太長影響使用者體驗）
                            - 設為 0 可完全停用同步標記（事件與視覺標記均不產生）
                            - 範例：--sync-marker-ms 500 產生 500ms 的紅色方塊與事件
        """
        for remaining in range(countdown_seconds, 0, -1):
            print(f"錄影將在 {remaining} 秒後開始...")
            time.sleep(1)
        print("開始錄影！")

        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.record_start_monotonic = time.perf_counter()
        self.events_file_path = self.output_dir / f"events_{self.timestamp}.json"
        self.frames_file_path = self.output_dir / f"frames_{self.timestamp}.jsonl"
        self._events_fp = open(self.events_file_path, 'w', encoding='utf-8', buffering=1)
        self._frames_fp = open(self.frames_file_path, 'w', encoding='utf-8', buffering=1)
        self._events_write_count = 0
        self._frames_write_count = 0
        self._event_queue = queue.Queue(maxsize=2000)
        self._event_queue_max_depth = 0
        self._event_drop_count = 0
        self._event_enqueued_count = 0
        self._event_written_count = 0
        self._sync_marker_end_emitted = False
        self._event_writer_thread = threading.Thread(target=self._event_writer_loop, daemon=True)
        self._event_writer_thread.start()

        self.recording = True
        self.modifier_state = {'ctrl': False, 'shift': False, 'alt': False}

        if sync_marker_ms > 0:
            # sync_marker_start 固定 timestamp=0.0，作為事件日誌的時間原點錨點。
            # duration_ms 記錄預期持續時間，供讀取端（auto_label_from_events.py）
            # 判斷標記結束時間；style 描述視覺外觀，便於日後擴充其他標記樣式。
            self._write_event(
                {
                    'type': 'sync_marker_start',
                    'timestamp': 0.0,        # 固定為 0.0，代表錄影的絕對起始點
                    'duration_ms': int(sync_marker_ms),  # 對應 --sync-marker-ms 參數值
                    'style': 'top_left_red_block',       # 左上角紅色方塊，與 _apply_sync_marker 一致
                }
            )

        # 啟動螢幕錄製執行緒
        screen_thread = threading.Thread(
            target=self.record_screen,
            args=(15, duration_seconds, sync_marker_ms)
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
                    join_timeout = (duration_seconds + 5) if duration_seconds else None
                    screen_thread.join(timeout=join_timeout)
                    self.recording = False
                    self._enqueue_frame_sentinel()
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)
            self._enqueue_event_sentinel()
            if self._event_writer_thread is not None:
                self._event_writer_thread.join(timeout=2)
                self._event_writer_thread = None
            if self._events_fp is not None:
                self._events_fp.flush()
                self._events_fp.close()
                self._events_fp = None
            if self._frames_fp is not None:
                self._frames_fp.flush()
                self._frames_fp.close()
                self._frames_fp = None
            self._event_queue = None

        # 保存事件日誌
        print(f"事件記錄已保存: {self.events_file_path}")
        print(f"影格時間軸已保存: {self.frames_file_path}")
        print(
            "錄影統計: "
            f"captured={self._frame_capture_count}, "
            f"written={self._frame_written_count}, "
            f"dropped={self._frame_drop_count}, "
            f"queue_peak={self._frame_queue_max_depth}"
        )
        print(
            "事件統計: "
            f"enqueued={self._event_enqueued_count}, "
            f"written={self._event_written_count}, "
            f"dropped={self._event_drop_count}, "
            f"queue_peak={self._event_queue_max_depth}"
        )

    def stop_recording(self):
        """停止錄製"""
        self.recording = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--duration", type=int, default=60, help="錄影秒數 (預設60秒)")
    parser.add_argument(
        "--sync-marker-ms",
        type=int,
        default=300,
        help=(
            "同步標記持續毫秒數（預設 300ms）。\n"
            "作用：在影片畫面左上角顯示紅色方塊，同時在事件日誌寫入 "
            "sync_marker_start / sync_marker_end，用於校驗影片與事件時間軸的對齊誤差。\n"
            "建議範圍：200–500ms。設為 0 可完全停用同步標記。\n"
            "範例：--sync-marker-ms 500"
        ),
    )
    args = parser.parse_args()
    recorder = ScreenEventRecorder()
    recorder.start_recording(duration_seconds=args.duration, sync_marker_ms=args.sync_marker_ms)
