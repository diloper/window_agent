"""Real-time microphone frequency analyzer (pure standard library).

This script captures live audio from the default microphone, computes a
Fast Fourier Transform (FFT) on each block of samples, and shows a live
frequency-spectrum bar chart.

No third-party packages are used:
- Audio capture  -> Windows ``winmm`` waveIn API via ``ctypes``.
- FFT            -> hand-written iterative Cooley-Tukey radix-2 (no numpy).
- Display        -> ``tkinter`` Canvas (bundled with CPython on Windows).

Stop the program with Ctrl+C, the Escape/Q key, or by closing the window.
"""

import array
import cmath
import ctypes
import signal
import threading
import time
from ctypes import wintypes

# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 44100        # Hz
CHUNK = 1024               # samples per FFT block (must be a power of two)
N_BUFFERS = 4              # number of rotating waveIn capture buffers
FREQ_MIN = 20              # Hz, lowest frequency shown
FREQ_MAX = 8000            # Hz, highest frequency shown
UPDATE_INTERVAL_MS = 40    # GUI refresh period
MIN_DB = -80.0             # spectrum value mapped to bottom of the chart
MAX_DB = 0.0               # spectrum value mapped to top of the chart
SMOOTH_ALPHA = 0.45        # exponential smoothing factor (0..1, higher = faster)

CANVAS_WIDTH = 1000
CANVAS_HEIGHT = 520


# --------------------------------------------------------------------------- #
# Manual FFT (iterative Cooley-Tukey, radix-2)
# --------------------------------------------------------------------------- #
def fft(samples):
    """In-place iterative radix-2 FFT.

    ``samples`` is a list of ``complex`` whose length must be a power of two.
    Returns the same list, transformed in place.
    """
    n = len(samples)
    if n & (n - 1) != 0:
        raise ValueError("FFT length must be a power of two")

    # Bit-reversal permutation.
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            samples[i], samples[j] = samples[j], samples[i]

    # Butterfly stages.
    length = 2
    while length <= n:
        angle = -2j * cmath.pi / length
        w_len = cmath.exp(angle)
        half = length >> 1
        for start in range(0, n, length):
            w = 1 + 0j
            for k in range(half):
                u = samples[start + k]
                v = samples[start + k + half] * w
                samples[start + k] = u + v
                samples[start + k + half] = u - v
                w *= w_len
        length <<= 1
    return samples


# --------------------------------------------------------------------------- #
# Windows waveIn structures and function prototypes
# --------------------------------------------------------------------------- #
WAVE_FORMAT_PCM = 1
WAVE_MAPPER = 0xFFFFFFFF      # default input device
CALLBACK_NULL = 0
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_void_p),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.c_void_p),
    ("reserved", ctypes.c_void_p),
]

_winmm = ctypes.windll.winmm

_winmm.waveInOpen.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.UINT,
    ctypes.POINTER(WAVEFORMATEX),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_winmm.waveInOpen.restype = wintypes.UINT

for _name in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
    _fn = getattr(_winmm, _name)
    _fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
    _fn.restype = wintypes.UINT

for _name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
    _fn = getattr(_winmm, _name)
    _fn.argtypes = [wintypes.HANDLE]
    _fn.restype = wintypes.UINT


# --------------------------------------------------------------------------- #
# Audio capture using the waveIn API
# --------------------------------------------------------------------------- #
class AudioCapture:
    """Captures 16-bit mono PCM audio into a rolling latest-block buffer."""

    def __init__(self, sample_rate=SAMPLE_RATE, chunk=CHUNK, n_buffers=N_BUFFERS):
        self.sample_rate = sample_rate
        self.chunk = chunk
        self.n_buffers = n_buffers
        self._handle = wintypes.HANDLE()
        self._headers = []
        self._buffers = []
        self._latest = [0.0] * chunk
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        fmt = WAVEFORMATEX(
            wFormatTag=WAVE_FORMAT_PCM,
            nChannels=1,
            nSamplesPerSec=self.sample_rate,
            nAvgBytesPerSec=self.sample_rate * 2,
            nBlockAlign=2,
            wBitsPerSample=16,
            cbSize=0,
        )
        res = _winmm.waveInOpen(
            ctypes.byref(self._handle),
            WAVE_MAPPER,
            ctypes.byref(fmt),
            None,
            None,
            CALLBACK_NULL,
        )
        if res != MMSYSERR_NOERROR:
            raise OSError(f"waveInOpen failed (error {res}); no microphone available?")

        nbytes = self.chunk * 2
        for _ in range(self.n_buffers):
            buf = ctypes.create_string_buffer(nbytes)
            hdr = WAVEHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = nbytes
            hdr.dwFlags = 0
            self._prepare_and_add(hdr)
            self._buffers.append(buf)
            self._headers.append(hdr)

        res = _winmm.waveInStart(self._handle)
        if res != MMSYSERR_NOERROR:
            raise OSError(f"waveInStart failed (error {res})")

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _prepare_and_add(self, hdr):
        _winmm.waveInPrepareHeader(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        _winmm.waveInAddBuffer(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def _run(self):
        while self._running:
            for idx, hdr in enumerate(self._headers):
                if hdr.dwFlags & WHDR_DONE:
                    recorded = hdr.dwBytesRecorded
                    if recorded:
                        raw = ctypes.string_at(self._buffers[idx], recorded)
                        pcm = array.array("h")
                        pcm.frombytes(raw)
                        block = [s / 32768.0 for s in pcm]
                        if len(block) == self.chunk:
                            with self._lock:
                                self._latest = block
                    _winmm.waveInUnprepareHeader(
                        self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr)
                    )
                    hdr.dwFlags = 0
                    hdr.dwBytesRecorded = 0
                    self._prepare_and_add(hdr)
            time.sleep(0.005)

    def get_samples(self):
        with self._lock:
            return list(self._latest)

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        _winmm.waveInStop(self._handle)
        _winmm.waveInReset(self._handle)
        for hdr in self._headers:
            _winmm.waveInUnprepareHeader(
                self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr)
            )
        _winmm.waveInClose(self._handle)


# --------------------------------------------------------------------------- #
# tkinter spectrum display
# --------------------------------------------------------------------------- #
class SpectrumApp:
    def __init__(self, root, capture):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.capture = capture
        self.chunk = capture.chunk
        self.sample_rate = capture.sample_rate

        # Precompute the Hann window to reduce spectral leakage.
        n = self.chunk
        self.window = [
            0.5 - 0.5 * cmath.cos(2 * cmath.pi * i / (n - 1)).real
            for i in range(n)
        ]

        # Frequency bin range to display.
        self.bin_lo = max(1, int(FREQ_MIN * n / self.sample_rate))
        self.bin_hi = min(n // 2, int(FREQ_MAX * n / self.sample_rate))
        self.n_bins = self.bin_hi - self.bin_lo + 1
        self.smoothed = [0.0] * self.n_bins

        root.title("Real-time Frequency Analyzer (FFT)")
        root.configure(bg="#101018")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Escape>", lambda _e: self.on_close())
        root.bind("q", lambda _e: self.on_close())

        self.canvas = tk.Canvas(
            root,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            bg="#101018",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._draw_axes()

        bar_w = CANVAS_WIDTH / self.n_bins
        self.bars = []
        for i in range(self.n_bins):
            x0 = i * bar_w
            x1 = x0 + max(1.0, bar_w - 1.0)
            bar = self.canvas.create_rectangle(
                x0, CANVAS_HEIGHT, x1, CANVAS_HEIGHT, fill="#33d6ff", width=0
            )
            self.bars.append(bar)

        self._closing = False

    def _draw_axes(self):
        # Horizontal frequency gridlines / labels.
        for hz in (100, 500, 1000, 2000, 4000, 8000):
            if hz < FREQ_MIN or hz > FREQ_MAX:
                continue
            frac = (hz - FREQ_MIN) / (FREQ_MAX - FREQ_MIN)
            x = frac * CANVAS_WIDTH
            self.canvas.create_line(
                x, 0, x, CANVAS_HEIGHT, fill="#202030"
            )
            label = f"{hz // 1000}k" if hz >= 1000 else f"{hz}"
            self.canvas.create_text(
                x + 2, CANVAS_HEIGHT - 8, text=label, anchor="w",
                fill="#6a6a80", font=("Consolas", 8),
            )

    def _color_for(self, frac):
        # Blue -> cyan -> green -> yellow -> red gradient by height.
        frac = max(0.0, min(1.0, frac))
        if frac < 0.5:
            t = frac / 0.5
            r = int(0x33 + t * (0x33 - 0x33))
            g = int(0xd6 + t * (0xff - 0xd6))
            b = int(0xff + t * (0x66 - 0xff))
        else:
            t = (frac - 0.5) / 0.5
            r = int(0x33 + t * (0xff - 0x33))
            g = int(0xff + t * (0x66 - 0xff))
            b = int(0x66 + t * (0x33 - 0x66))
        return f"#{r:02x}{g:02x}{b:02x}"

    def update(self):
        if self._closing:
            return

        samples = self.capture.get_samples()
        if len(samples) == self.chunk:
            windowed = [complex(s * w, 0.0) for s, w in zip(samples, self.window)]
            spectrum = fft(windowed)

            norm = 2.0 / self.chunk
            for i in range(self.n_bins):
                mag = abs(spectrum[self.bin_lo + i]) * norm
                db = 20.0 * cmath.log10(mag + 1e-9).real
                level = (db - MIN_DB) / (MAX_DB - MIN_DB)
                level = max(0.0, min(1.0, level))
                self.smoothed[i] = (
                    SMOOTH_ALPHA * level + (1 - SMOOTH_ALPHA) * self.smoothed[i]
                )

            for i, bar in enumerate(self.bars):
                frac = self.smoothed[i]
                y0 = CANVAS_HEIGHT * (1.0 - frac)
                coords = self.canvas.coords(bar)
                self.canvas.coords(bar, coords[0], y0, coords[2], CANVAS_HEIGHT)
                self.canvas.itemconfigure(bar, fill=self._color_for(frac))

        self.root.after(UPDATE_INTERVAL_MS, self.update)

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.capture.stop()
        self.root.after(50, self.root.destroy)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    import tkinter as tk

    capture = AudioCapture()
    capture.start()

    root = tk.Tk()
    app = SpectrumApp(root, capture)

    # Allow Ctrl+C from the console to close the window cleanly.
    signal.signal(signal.SIGINT, lambda _s, _f: app.on_close())

    # Keep the interpreter responsive so the SIGINT handler can fire.
    def _keep_alive():
        if not app._closing:
            root.after(200, _keep_alive)

    root.after(UPDATE_INTERVAL_MS, app.update)
    root.after(200, _keep_alive)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.on_close()
    finally:
        capture.stop()


if __name__ == "__main__":
    main()
