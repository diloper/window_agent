#!/usr/bin/env python3
"""不使用第三方套件的鍵盤鋼琴模擬器（即時串流合成版）.

Audio    : 標準函式庫 ctypes 直接驅動 Windows WinMM waveOut，連續串流混音
Synthesis: 波表合成（基音 + 3 泛音）+ ADSR 包絡，按住持續發聲、放開才釋放
Polyphony: 音訊串流中即時混合多個獨立聲部 → 真正的多鍵和聲（電子鋼琴效果）
Input    : 標準函式庫 ctypes 呼叫 GetAsyncKeyState 即時偵測所有按住的鍵
Range    : C4 ~ C6（兩個八度以上，含黑鍵 / 半音）
Exit     : 按 Esc 離開
Platform : Windows only（ctypes winmm / user32 為 Windows 標準函式庫）

純標準函式庫，無任何第三方相依套件。
"""

import argparse
import ctypes
import ctypes.wintypes as wintypes
import math
import struct
import sys
import threading
import time

# ── Configuration ────────────────────────────────────────────────────────────
SAMPLE_RATE  = 44100           # 取樣率 (Hz)
BITS         = 16              # 每樣本位元數
HARMONICS    = (               # (倍頻, 相對振幅)：基音 + 3 個泛音，決定音色
    (1.0, 1.00),
    (2.0, 0.50),
    (3.0, 0.25),
    (4.0, 0.12),
)

# 波表（單一週期，所有音高共用此波形，靠相位增量決定頻率）
TABLE_SIZE   = 2048
TABLE_MASK   = TABLE_SIZE - 1

# 串流緩衝參數（區塊越小延遲越低，但越容易破音）
BLOCK_FRAMES = 1024            # 每個音訊區塊的取樣數（約 23ms）
NUM_BUFFERS  = 3               # 環狀緩衝數量

# ADSR 包絡（秒）：電子鋼琴式 —— 起音快、按住持續、放開才釋放
ATTACK_S     = 0.006
RELEASE_S    = 0.18
MASTER_GAIN  = 0.30            # 主音量，預留 headroom 供多聲部疊加

A4_MIDI = 69                   # A4 的 MIDI 編號
A4_FREQ = 440.0                # A4 頻率 (Hz)

# ── 鍵位對應：電腦鍵盤字元 -> MIDI 編號 ────────────────────────────────────────
# 下八度（C4~B4）放在 Z 排白鍵，黑鍵放上方 S D G H J
# 上八度（C5~B5）放在 Q 排白鍵，黑鍵放數字列 2 3 5 6 7
# , . / 延伸到 C6 一帶
KEY_TO_MIDI = {
    # ── 下八度 C4(60) ~ B4(71) ──
    "z": 60,  # C4
    "s": 61,  # C#4
    "x": 62,  # D4
    "d": 63,  # D#4
    "c": 64,  # E4
    "v": 65,  # F4
    "g": 66,  # F#4
    "b": 67,  # G4
    "h": 68,  # G#4
    "n": 69,  # A4
    "j": 70,  # A#4
    "m": 71,  # B4
    # ── 上八度 C5(72) ~ B5(83) ──
    "q": 72,  # C5
    "2": 73,  # C#5
    "w": 74,  # D5
    "3": 75,  # D#5
    "e": 76,  # E5
    "r": 77,  # F5
    "5": 78,  # F#5
    "t": 79,  # G5
    "6": 80,  # G#5
    "y": 81,  # A5
    "7": 82,  # A#5
    "u": 83,  # B5
    # ── 延伸至 C6(84) ──
    "i": 84,  # C6
}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_freq(midi: int) -> float:
    """將 MIDI 編號轉換為平均律頻率 (Hz)。"""
    return A4_FREQ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def midi_to_name(midi: int) -> str:
    """將 MIDI 編號轉換為音名（含八度），例如 60 -> 'C4'。"""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


# ── 波表與包絡（模組層級預先計算） ────────────────────────────────────────────
_HARMONIC_NORM = sum(amp for _, amp in HARMONICS)
WAVETABLE = [
    sum(amp * math.sin(2.0 * math.pi * ratio * i / TABLE_SIZE)
        for ratio, amp in HARMONICS) / _HARMONIC_NORM
    for i in range(TABLE_SIZE)
]
ATK_INC = 1.0 / (ATTACK_S * SAMPLE_RATE)              # 起音每樣本遞增量
REL_MUL = math.exp(-1.0 / (RELEASE_S * SAMPLE_RATE))  # 釋音每樣本衰減比例
REL_END = 0.001                                       # 釋音低於此值即移除聲部
_GAIN_INT = MASTER_GAIN * ((1 << (BITS - 1)) - 1)
_MAX_INT = (1 << (BITS - 1)) - 1
_MIN_INT = -(1 << (BITS - 1))

# ── WinMM waveOut ctypes 介面 ─────────────────────────────────────────────────
_WINMM = ctypes.windll.winmm if hasattr(ctypes, "windll") else None
WAVE_FORMAT_PCM = 1
WAVE_MAPPER     = 0xFFFFFFFF
CALLBACK_NULL   = 0
WHDR_DONE       = 0x00000001
HWAVEOUT = wintypes.HANDLE


class _WAVEFORMATEX(ctypes.Structure):
    """對應 Windows WAVEFORMATEX (mmeapi.h)。"""
    _fields_ = [
        ("wFormatTag",      wintypes.WORD),
        ("nChannels",       wintypes.WORD),
        ("nSamplesPerSec",  wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign",     wintypes.WORD),
        ("wBitsPerSample",  wintypes.WORD),
        ("cbSize",          wintypes.WORD),
    ]


class _WAVEHDR(ctypes.Structure):
    """對應 Windows WAVEHDR (mmeapi.h)。"""
    _fields_ = [
        ("lpData",          ctypes.c_void_p),
        ("dwBufferLength",  wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser",          ctypes.c_size_t),
        ("dwFlags",         wintypes.DWORD),
        ("dwLoops",         wintypes.DWORD),
        ("lpNext",          ctypes.c_void_p),
        ("reserved",        ctypes.c_size_t),
    ]


_WAVEHDR_SIZE = ctypes.sizeof(_WAVEHDR)


class _Voice:
    """單一發聲中的聲部狀態（相位 + ADSR 包絡）。"""
    __slots__ = ("phase", "inc", "env", "releasing")

    def __init__(self, inc: float):
        self.phase = 0.0
        self.inc = inc            # 每樣本的波表相位增量（決定音高）
        self.env = 0.0            # 目前包絡值
        self.releasing = False    # 是否已進入釋音階段


class WaveOutSynth:
    """以 WinMM waveOut 連續串流混音的即時複音合成引擎。

    每個按鍵對應一個獨立聲部，音訊串流持續把所有活躍聲部即時混合輸出，
    因此可同時奏出多音和聲；按住持續發聲、放開才進入釋音，貼近電子鋼琴。
    """

    def __init__(self):
        self._hwo = HWAVEOUT()
        self._voices = {}             # midi -> _Voice
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._buffers = []            # 保留緩衝區參考避免被 GC 回收
        self._headers = []

    # ── 對外 API ──────────────────────────────────────────────────────────
    def start(self) -> None:
        """開啟音訊裝置、配置環狀緩衝並啟動串流執行緒。"""
        if _WINMM is None:
            raise RuntimeError("WinMM 不可用（需 Windows）。")

        fmt = _WAVEFORMATEX()
        fmt.wFormatTag = WAVE_FORMAT_PCM
        fmt.nChannels = 1
        fmt.nSamplesPerSec = SAMPLE_RATE
        fmt.wBitsPerSample = BITS
        fmt.nBlockAlign = BITS // 8
        fmt.nAvgBytesPerSec = SAMPLE_RATE * (BITS // 8)
        fmt.cbSize = 0
        rc = _WINMM.waveOutOpen(
            ctypes.byref(self._hwo), WAVE_MAPPER, ctypes.byref(fmt),
            None, None, CALLBACK_NULL,
        )
        if rc != 0:
            raise RuntimeError(f"waveOutOpen 失敗 (MMRESULT={rc})。")

        block_bytes = BLOCK_FRAMES * (BITS // 8)
        for _ in range(NUM_BUFFERS):
            buf = ctypes.create_string_buffer(block_bytes)
            hdr = _WAVEHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = block_bytes
            _WINMM.waveOutPrepareHeader(self._hwo, ctypes.byref(hdr), _WAVEHDR_SIZE)
            self._buffers.append(buf)
            self._headers.append(hdr)

        self._running = True
        self._thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止串流並釋放音訊資源。"""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if _WINMM is not None and self._hwo:
            _WINMM.waveOutReset(self._hwo)
            for hdr in self._headers:
                _WINMM.waveOutUnprepareHeader(
                    self._hwo, ctypes.byref(hdr), _WAVEHDR_SIZE
                )
            _WINMM.waveOutClose(self._hwo)
        self._headers.clear()
        self._buffers.clear()

    def note_on(self, midi: int) -> None:
        """觸發（或重新觸發）某個音，使其進入起音 / 持續。"""
        inc = midi_to_freq(midi) * TABLE_SIZE / SAMPLE_RATE
        with self._lock:
            v = self._voices.get(midi)
            if v is None:
                self._voices[midi] = _Voice(inc)
            else:
                v.releasing = False   # 釋音中又被按下 → 取消釋音回到持續

    def note_off(self, midi: int) -> None:
        """放開某個音，使其進入釋音階段。"""
        with self._lock:
            v = self._voices.get(midi)
            if v is not None:
                v.releasing = True

    # ── 內部：合成與串流 ──────────────────────────────────────────────────
    def _render_block(self) -> bytes:
        """混合所有活躍聲部，產生一個 16-bit PCM 區塊。"""
        mix = [0.0] * BLOCK_FRAMES
        table = WAVETABLE
        with self._lock:
            dead = []
            for midi, v in self._voices.items():
                phase = v.phase
                env = v.env
                inc = v.inc
                releasing = v.releasing
                for i in range(BLOCK_FRAMES):
                    if releasing:
                        env *= REL_MUL
                    elif env < 1.0:
                        env += ATK_INC
                        if env > 1.0:
                            env = 1.0
                    mix[i] += table[int(phase) & TABLE_MASK] * env
                    phase += inc
                    if phase >= TABLE_SIZE:
                        phase -= TABLE_SIZE
                v.phase = phase
                v.env = env
                if releasing and env <= REL_END:
                    dead.append(midi)
            for midi in dead:
                del self._voices[midi]

        out = [0] * BLOCK_FRAMES
        for i in range(BLOCK_FRAMES):
            s = int(mix[i] * _GAIN_INT)
            if s > _MAX_INT:
                s = _MAX_INT
            elif s < _MIN_INT:
                s = _MIN_INT
            out[i] = s
        return struct.pack("<%dh" % BLOCK_FRAMES, *out)

    def _submit(self, idx: int) -> None:
        """渲染下一區塊、寫入緩衝並送進 waveOut 佇列。"""
        data = self._render_block()
        ctypes.memmove(self._buffers[idx], data, len(data))
        hdr = self._headers[idx]
        hdr.dwFlags &= ~WHDR_DONE
        _WINMM.waveOutWrite(self._hwo, ctypes.byref(hdr), _WAVEHDR_SIZE)

    def _audio_loop(self) -> None:
        """串流主迴圈：保持環狀緩衝持續被填滿。"""
        for idx in range(NUM_BUFFERS):       # 先把所有緩衝填滿並送出
            self._submit(idx)
        while self._running:
            progressed = False
            for idx in range(NUM_BUFFERS):
                if self._headers[idx].dwFlags & WHDR_DONE:
                    self._submit(idx)
                    progressed = True
            if not progressed:
                time.sleep(0.001)


def print_keymap() -> None:
    """印出鍵位對照表。"""
    print("=" * 56)
    print("  不使用套件的鍵盤鋼琴  (Esc 離開)")
    print("=" * 56)
    for key, midi in sorted(KEY_TO_MIDI.items(), key=lambda kv: kv[1]):
        print(f"   [{key.upper():>1}]  ->  {midi_to_name(midi):<3}  ({midi_to_freq(midi):7.2f} Hz)")
    print("=" * 56)


def run_interactive() -> int:
    """即時鍵盤演奏主迴圈（GetAsyncKeyState 偵測按住的鍵，串流引擎即時混音）。"""
    if _WINMM is None or not hasattr(ctypes, "windll"):
        print("此程式需要 Windows 環境（ctypes winmm / user32）。", file=sys.stderr)
        return 1
    user32 = ctypes.windll.user32
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

    synth = WaveOutSynth()
    try:
        synth.start()
    except RuntimeError as exc:
        print(f"[ERROR] 無法開啟音訊裝置：{exc}", file=sys.stderr)
        return 1

    print_keymap()
    print("開始演奏！按住即持續發聲、放開即釋放；同時按住多鍵可奏出和聲；Esc 離開。\n")

    VK_ESCAPE = 0x1B
    key_to_vk = {key: ord(key.upper()) for key in KEY_TO_MIDI}

    def is_down(vk: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    prev = set()
    try:
        while True:
            if is_down(VK_ESCAPE):
                break
            pressed = {
                midi for key, midi in KEY_TO_MIDI.items() if is_down(key_to_vk[key])
            }
            for midi in pressed - prev:         # 新按下 → 觸發
                synth.note_on(midi)
            for midi in prev - pressed:          # 放開 → 釋音
                synth.note_off(midi)
            if pressed != prev:
                if pressed:
                    names = " + ".join(midi_to_name(m) for m in sorted(pressed))
                    print(f"\r  \u266a {names:<48}", end="", flush=True)
                else:
                    print(f"\r{' ' * 52}\r", end="", flush=True)
            prev = pressed
            time.sleep(0.008)
    finally:
        for midi in prev:
            synth.note_off(midi)
        time.sleep(RELEASE_S + 0.1)              # 讓釋音自然收尾
        synth.stop()

    print("\n再見！")
    return 0


def run_demo() -> int:
    """非互動示範：用串流引擎彈奏音階與「持續按住」的和聲後結束（供自動驗證）。"""
    if _WINMM is None:
        print("此程式需要 Windows 環境（ctypes winmm）。", file=sys.stderr)
        return 1

    synth = WaveOutSynth()
    try:
        synth.start()
    except RuntimeError as exc:
        print(f"[ERROR] 無法開啟音訊裝置：{exc}", file=sys.stderr)
        return 1

    try:
        print("Demo：彈奏兩個八度的 C 大調音階…")
        scale = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]
        for midi in scale:
            print(f"  {midi_to_name(midi):<3}  ({midi_to_freq(midi):7.2f} Hz)")
            synth.note_on(midi)
            time.sleep(0.18)
            synth.note_off(midi)
            time.sleep(0.05)
        time.sleep(0.3)

        print("Demo：示範持續按住的和聲（音訊串流中即時混合多個獨立聲部）…")
        chords = [
            ("C 大三和弦", [60, 64, 67]),
            ("F 大三和弦", [65, 69, 72]),
            ("G 大三和弦", [67, 71, 74]),
            ("C 大三和弦（八度疊加）", [60, 64, 67, 72]),
        ]
        for label, midis in chords:
            names = " + ".join(midi_to_name(m) for m in midis)
            print(f"  {label}: {names}")
            for midi in midis:                  # 同時按住整組和弦
                synth.note_on(midi)
            time.sleep(0.9)                     # 持續發聲，展示真正的多聲部
            for midi in midis:                  # 一起放開
                synth.note_off(midi)
            time.sleep(0.3)
        time.sleep(RELEASE_S + 0.2)             # 讓最後的釋音收尾
        print("Demo 完成。")
    finally:
        synth.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="不使用第三方套件的鍵盤鋼琴模擬器（Windows）。"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="非互動模式：自動彈奏兩個八度的 C 大調音階後結束。",
    )
    args = parser.parse_args()

    if args.demo:
        return run_demo()
    return run_interactive()


if __name__ == "__main__":
    sys.exit(main())
