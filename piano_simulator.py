#!/usr/bin/env python3
"""不使用第三方套件的鍵盤鋼琴模擬器.

Audio    : 標準函式庫 winsound + wave 在記憶體合成 PCM WAV 後非阻塞播放
Synthesis: 基音 + 3 個泛音 + 指數衰減包絡 (exponential decay)，模擬鋼琴音色
Input    : 標準函式庫 msvcrt 即時讀取單一按鍵
Range    : C4 ~ C6（兩個八度以上，含黑鍵 / 半音）
Exit     : 按 Esc 離開
Platform : Windows only（winsound / msvcrt 為 Windows 標準函式庫）

純標準函式庫，無任何第三方相依套件。
"""

import argparse
import io
import math
import struct
import sys
import threading
import time
import wave

try:
    import msvcrt
    import winsound
except ImportError:  # pragma: no cover - 非 Windows 平台
    msvcrt = None
    winsound = None

try:
    from pynput import keyboard as pynput_kb
except ImportError:  # pragma: no cover
    pynput_kb = None

# ── Configuration ────────────────────────────────────────────────────────────
SAMPLE_RATE   = 44100          # 取樣率 (Hz)
BITS          = 16             # 每樣本位元數
AMPLITUDE     = 0.45           # 主振幅 (0.0 ~ 1.0)，預留 headroom 避免削波
NOTE_DURATION = 0.55           # 單音長度 (秒)
DECAY         = 6.0            # 指數衰減速率，越大衰減越快
HARMONICS     = (              # (倍頻, 相對振幅)：基音 + 3 個泛音
    (1.0, 1.00),
    (2.0, 0.50),
    (3.0, 0.25),
    (4.0, 0.12),
)

A4_MIDI = 69                   # A4 的 MIDI 編號
A4_FREQ = 440.0                # A4 頻率 (Hz)
MIDI_LOW  = 60                 # C4
MIDI_HIGH = 84                 # C6

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
ESC = "\x1b"


def midi_to_freq(midi: int) -> float:
    """將 MIDI 編號轉換為平均律頻率 (Hz)。"""
    return A4_FREQ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def midi_to_name(midi: int) -> str:
    """將 MIDI 編號轉換為音名（含八度），例如 60 -> 'C4'。"""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def synthesize_wav(freq: float, duration: float = NOTE_DURATION) -> bytes:
    """合成單一音高的 WAV 位元組（基音 + 3 泛音 + 指數衰減）。"""
    num_samples = int(SAMPLE_RATE * duration)
    max_int = (1 << (BITS - 1)) - 1
    frames = bytearray()

    # 預先正規化泛音總振幅，避免疊加後削波
    harmonic_norm = sum(amp for _, amp in HARMONICS)

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        envelope = math.exp(-DECAY * t)        # 指數衰減包絡
        sample = 0.0
        for ratio, amp in HARMONICS:
            sample += amp * math.sin(2.0 * math.pi * freq * ratio * t)
        sample = (sample / harmonic_norm) * envelope * AMPLITUDE
        value = int(max(-1.0, min(1.0, sample)) * max_int)
        frames += struct.pack("<h", value)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(BITS // 8)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def build_sound_cache() -> dict:
    """為所有對應到的 MIDI 音預先合成並快取 WAV 位元組，避免按鍵延遲。"""
    cache = {}
    for midi in sorted(set(KEY_TO_MIDI.values())):
        cache[midi] = synthesize_wav(midi_to_freq(midi))
    return cache


def play(data: bytes) -> None:
    """播放記憶體中的 WAV 位元組。

    winsound 不允許 SND_MEMORY 與 SND_ASYNC 並用，故改在 daemon 累程中
    同步播放，讓互動主迴圈保持反應。
    """
    threading.Thread(
        target=winsound.PlaySound,
        args=(data, winsound.SND_MEMORY),
        daemon=True,
    ).start()


def print_keymap() -> None:
    """印出鍵位對照表。"""
    print("=" * 56)
    print("  不使用套件的鍵盤鋼琴  (Esc 離開)")
    print("=" * 56)
    for key, midi in sorted(KEY_TO_MIDI.items(), key=lambda kv: kv[1]):
        print(f"   [{key.upper():>1}]  ->  {midi_to_name(midi):<3}  ({midi_to_freq(midi):7.2f} Hz)")
    print("=" * 56)


def run_interactive() -> int:
    """即時鍵盤演奏主迴圈（支援同時按住多鍵奏出和聲）。"""
    if winsound is None:
        print("此程式需要 Windows 環境（winsound）。", file=sys.stderr)
        return 1

    print("正在合成音色…")
    cache = build_sound_cache()
    print_keymap()
    print("開始演奏！單鍵發音；同時按住多鍵可奏出和聲；Esc 離開。\n")

    # ── fallback：pynput 不可用時退回 msvcrt 單鍵模式 ──
    if pynput_kb is None:
        if msvcrt is None:
            print("[ERROR] msvcrt / pynput 均不可用。", file=sys.stderr)
            return 1
        while True:
            ch = msvcrt.getwch()
            if ch == ESC:
                break
            midi = KEY_TO_MIDI.get(ch.lower())
            if midi is not None:
                play(cache[midi])
        print("\n再見！")
        return 0

    # ── pynput 模式：press/release 追蹤多鍵同時按下 ──
    held: set[str] = set()   # 目前按住的小寫字元集合
    done = threading.Event()

    def _refresh_display() -> None:
        """在同一行顯示目前按住的所有音名（和聲預覽）。"""
        held_midi = sorted(KEY_TO_MIDI[k] for k in held if k in KEY_TO_MIDI)
        if held_midi:
            chord = " + ".join(midi_to_name(m) for m in held_midi)
            print(f"\r  \u266a {chord:<44}", end="", flush=True)
        else:
            print(f"\r{' ' * 50}\r", end="", flush=True)

    def on_press(key):
        try:
            ch = key.char
        except AttributeError:
            if key == pynput_kb.Key.esc:
                done.set()
                return False   # 停止 Listener
            return
        if not ch:
            return
        lower = ch.lower()
        if lower in held:
            return             # 按住不放產生的重複事件，忽略
        midi = KEY_TO_MIDI.get(lower)
        if midi is not None:
            held.add(lower)
            play(cache[midi]) # 非阻塞，與其他正在播放的音自然疊合
            _refresh_display()

    def on_release(key):
        try:
            ch = key.char
            if ch:
                held.discard(ch.lower())
                _refresh_display()
        except AttributeError:
            pass

    with pynput_kb.Listener(on_press=on_press, on_release=on_release) as listener:
        done.wait()
        listener.stop()

    print("\n再見！")
    return 0


def run_demo() -> int:
    """非互動示範：依序彈奏兩個八度的 C 大調音階後結束（供自動驗證）。"""
    if winsound is None:
        print("此程式需要 Windows 環境（winsound）。", file=sys.stderr)
        return 1

    print("Demo：彈奏兩個八度的 C 大調音階…")
    scale = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]
    step = NOTE_DURATION * 0.6
    for midi in scale:
        print(f"  {midi_to_name(midi):<3}  ({midi_to_freq(midi):7.2f} Hz)")
        play(synthesize_wav(midi_to_freq(midi)))
        time.sleep(step)
    time.sleep(NOTE_DURATION)  # 讓最後一音播放完整
    print("Demo 完成。")
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
