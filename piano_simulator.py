#!/usr/bin/env python3
"""不使用第三方套件的鍵盤鋼琴模擬器.

Audio    : 標準函式庫 winsound + wave 在記憶體合成 PCM WAV 後播放
Synthesis: 基音 + 3 個泛音 + 指數衰減包絡 (exponential decay)，模擬鋼琴音色
Polyphony: 多個音混音至同一緩衝區 → 同時按住多鍵可奇出和聲
Input    : 標準函式庫 ctypes 呼叫 GetAsyncKeyState 即時偵測所有按住的鍵
Range    : C4 ~ C6（兩個八度以上，含黑鍵 / 半音）
Exit     : 按 Esc 離開
Platform : Windows only（winsound / ctypes user32 為 Windows 標準函式庫）

純標準函式庫，無任何第三方相依套件。
"""

import argparse
import ctypes
import io
import math
import struct
import sys
import threading
import time
import wave

try:
    import winsound
except ImportError:  # pragma: no cover - 非 Windows 平台
    winsound = None

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


def midi_to_freq(midi: int) -> float:
    """將 MIDI 編號轉換為平均律頻率 (Hz)。"""
    return A4_FREQ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def midi_to_name(midi: int) -> str:
    """將 MIDI 編號轉換為音名（含八度），例如 60 -> 'C4'。"""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def note_samples(freq: float, duration: float = NOTE_DURATION) -> list:
    """合成單一音高的正規化浮點樣本（基音 + 3 泛音 + 指數衰減）。

    回傳值約落在 [-1.0, 1.0]，尚未套用主振幅，方便後續混音。
    """
    num_samples = int(SAMPLE_RATE * duration)
    harmonic_norm = sum(amp for _, amp in HARMONICS)
    out = [0.0] * num_samples
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        envelope = math.exp(-DECAY * t)        # 指數衰減包絡
        sample = 0.0
        for ratio, amp in HARMONICS:
            sample += amp * math.sin(2.0 * math.pi * freq * ratio * t)
        out[i] = (sample / harmonic_norm) * envelope
    return out


def samples_to_wav(voices: list) -> bytes:
    """將一個或多個音的樣本陣列混音成單一 WAV 位元組。

    多個音同時混入同一緩衝區即可奇出和聲；以發聲數正規化避免削波。
    """
    if not voices:
        return b""
    length = len(voices[0])
    count = len(voices)
    max_int = (1 << (BITS - 1)) - 1
    ints = [0] * length
    for i in range(length):
        total = 0.0
        for v in voices:
            total += v[i]
        total = (total / count) * AMPLITUDE     # 依發聲數正規化
        ints[i] = int(max(-1.0, min(1.0, total)) * max_int)
    data = struct.pack("<%dh" % length, *ints)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(BITS // 8)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data)
    return buffer.getvalue()


def synthesize_wav(freq: float, duration: float = NOTE_DURATION) -> bytes:
    """合成單一音高的 WAV 位元組。"""
    return samples_to_wav([note_samples(freq, duration)])


def build_sample_cache() -> dict:
    """預先合成每個 MIDI 音的樣本陣列，供即時混音奇和聲。"""
    return {
        midi: note_samples(midi_to_freq(midi))
        for midi in sorted(set(KEY_TO_MIDI.values()))
    }


def play(data: bytes) -> None:
    """播放記憶體中的 WAV 位元組。

    winsound 不允許 SND_MEMORY 與 SND_ASYNC 並用，故改在 daemon 累程中
    同步播放，讓互動主迴圈保持反應。
    """
    if not data:
        return
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
    """即時鍵盤演奏主迴圈（用 GetAsyncKeyState 偵測同時按住多鍵以奏和聲）。"""
    if winsound is None:
        print("此程式需要 Windows 環境（winsound）。", file=sys.stderr)
        return 1
    try:
        user32 = ctypes.windll.user32
    except AttributeError:  # pragma: no cover - 非 Windows 平台
        print("此程式需要 Windows 環境（GetAsyncKeyState）。", file=sys.stderr)
        return 1
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

    print("正在合成音色…")
    cache = build_sample_cache()
    print_keymap()
    print("開始演奏！單鍵發音；同時按住多鍵即可奏出和聲；Esc 離開。\n")

    VK_ESCAPE = 0x1B
    key_to_vk = {key: ord(key.upper()) for key in KEY_TO_MIDI}

    def is_down(vk: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    prev = frozenset()
    while True:
        if is_down(VK_ESCAPE):
            break
        pressed = frozenset(
            midi for key, midi in KEY_TO_MIDI.items() if is_down(key_to_vk[key])
        )
        if pressed - prev:                      # 有新按下的鍵 → 重新觸發整組和聲
            chord = sorted(pressed)
            play(samples_to_wav([cache[m] for m in chord]))
            names = " + ".join(midi_to_name(m) for m in chord)
            print(f"\r  \u266a {names:<48}", end="", flush=True)
        elif not pressed and prev:              # 全部放開 → 清除顯示
            print(f"\r{' ' * 52}\r", end="", flush=True)
        prev = pressed
        time.sleep(0.01)

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

    print("Demo：示範同時發聲的和聲（多音混入單一緩衝區）…")
    cache = build_sample_cache()
    chords = [
        ("C 大三和弦", [60, 64, 67]),
        ("F 大三和弦", [65, 69, 72]),
        ("G 大三和弦", [67, 71, 74]),
        ("C 大三和弦（八度疊加）", [60, 64, 67, 72]),
    ]
    for label, midis in chords:
        names = " + ".join(midi_to_name(m) for m in midis)
        print(f"  {label}: {names}")
        play(samples_to_wav([cache[m] for m in midis]))
        time.sleep(NOTE_DURATION * 1.1)
    time.sleep(NOTE_DURATION)  # 讓最後一組和聲播放完整
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
