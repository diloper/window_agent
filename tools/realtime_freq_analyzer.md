# 即時頻率分析器：演算法說明與論文對照

本文件解釋 [realtime_freq_analyzer.py](realtime_freq_analyzer.py) 所使用的核心演算法，並對照其背後的經典論文與數學理論。整支程式 **僅使用 Python 標準函式庫**，FFT 為手寫實作（未使用 numpy）。

---

## 1. 處理流程總覽

```mermaid
flowchart LR
    A[麥克風<br/>winmm waveIn] --> B[16-bit PCM 取樣]
    B --> C[Hann 視窗加權]
    C --> D[手寫 FFT<br/>Cooley-Tukey radix-2]
    D --> E[幅值 → dB 轉換]
    E --> F[指數平滑]
    F --> G[tkinter 長條圖]
```

| 階段 | 程式位置 | 對應理論 |
| --- | --- | --- |
| 類比訊號取樣 | `AudioCapture`、`SAMPLE_RATE=44100` | Nyquist–Shannon 取樣定理 |
| 視窗函數 | `SpectrumApp.__init__` 的 `self.window` | Hann window（Blackman/Harris 視窗理論） |
| 頻譜轉換 | `fft()` | Cooley–Tukey FFT（DFT 定義） |
| 幅值/分貝 | `update()` 內 `20*log10(mag)` | 功率頻譜密度、分貝刻度 |
| 顯示平滑 | `SMOOTH_ALPHA` 指數加權 | 一階 IIR / 指數移動平均 |

---

## 2. 取樣與 Nyquist 定理

程式以 `SAMPLE_RATE = 44100` Hz、16-bit、單聲道擷取音訊（`WAVEFORMATEX`）。

根據 **Nyquist–Shannon 取樣定理**，可無失真重建的最高頻率為取樣率的一半：

$$
f_{\text{Nyquist}} = \frac{f_s}{2} = \frac{44100}{2} = 22050 \text{ Hz}
$$

因此 FFT 輸出只有前 $N/2$ 個 bin（`spectrum[0 .. N/2]`）含有意義的資訊，程式只顯示到 `FREQ_MAX = 8000` Hz。

**對照論文**
- C. E. Shannon, *"Communication in the Presence of Noise"*, Proc. IRE, vol. 37, no. 1, pp. 10–21, 1949.
- H. Nyquist, *"Certain Topics in Telegraph Transmission Theory"*, Trans. AIEE, vol. 47, pp. 617–644, 1928.

---

## 3. 離散傅立葉轉換（DFT）定義

每一個音框 $x[n]$（長度 $N = 1024$）的 DFT 定義為：

$$
X[k] = \sum_{n=0}^{N-1} x[n]\, e^{-j 2\pi k n / N}, \quad k = 0, 1, \dots, N-1
$$

直接計算為 $O(N^2)$。每個 bin 對應的實際頻率為：

$$
f_k = \frac{k \cdot f_s}{N} = \frac{k \cdot 44100}{1024} \approx 43.07 \cdot k \text{ Hz}
$$

這也是頻率解析度（bin 寬度）為 ~43 Hz 的原因；驗證測試中 1000 Hz 正弦波落在 bin 23（$23 \times 43.07 \approx 990.5$ Hz）即由此而來。

---

## 4. 快速傅立葉轉換：Cooley–Tukey radix-2

程式中的 `fft()` 函式實作 **iterative（疊代式）radix-2 Cooley–Tukey** 演算法，把複雜度從 $O(N^2)$ 降到：

$$
O(N \log_2 N)
$$

### 4.1 分治原理

Cooley–Tukey 將長度 $N$ 的 DFT 拆成偶數項與奇數項兩個長度 $N/2$ 的 DFT：

$$
X[k] = E[k] + W_N^k \, O[k]
$$
$$
X[k + N/2] = E[k] - W_N^k \, O[k]
$$

其中旋轉因子（twiddle factor）：

$$
W_N^k = e^{-j 2\pi k / N}
$$

這對加減結構即為著名的 **蝴蝶運算（butterfly）**。

### 4.2 程式碼對照

**(a) 位元反轉重排（bit-reversal permutation）**

```python
j = 0
for i in range(1, n):
    bit = n >> 1
    while j & bit:
        j ^= bit
        bit >>= 1
    j ^= bit
    if i < j:
        samples[i], samples[j] = samples[j], samples[i]
```

疊代式 FFT 必須先把輸入依「索引位元反轉」順序重排，之後才能就地（in-place）做蝴蝶運算。此即原始論文中 decimation-in-time 的資料重排步驟。

**(b) 蝴蝶運算階層**

```python
length = 2
while length <= n:
    w_len = cmath.exp(-2j * cmath.pi / length)   # 該層的旋轉因子基底
    half = length >> 1
    for start in range(0, n, length):
        w = 1 + 0j
        for k in range(half):
            u = samples[start + k]
            v = samples[start + k + half] * w     # W_N^k * O[k]
            samples[start + k]        = u + v      # X[k]
            samples[start + k + half] = u - v      # X[k + N/2]
            w *= w_len                             # 遞增旋轉因子
    length <<= 1
```

- 外層 `while length` 共執行 $\log_2 N$ 層。
- `u + v` / `u - v` 正是上面兩條蝴蝶公式。
- `w *= w_len` 以遞乘方式產生 $W_N^k$，避免每次重算 `exp`。

**對照論文（核心）**
- J. W. Cooley and J. W. Tukey, *"An Algorithm for the Machine Calculation of Complex Fourier Series"*, Mathematics of Computation, vol. 19, no. 90, pp. 297–301, 1965.

> 此篇即 FFT 的奠基論文；本程式的 `fft()` 為其 radix-2、decimation-in-time、iterative 形式。

延伸閱讀：
- E. O. Brigham, *The Fast Fourier Transform and Its Applications*, Prentice-Hall, 1988.
- Cormen, Leiserson, Rivest, Stein, *Introduction to Algorithms*, 第 30 章（疊代式 FFT 與位元反轉的標準教科書寫法）。

---

## 5. Hann 視窗（減少頻譜洩漏）

在做 FFT 前，每個音框先乘上 **Hann 視窗**：

```python
self.window = [0.5 - 0.5 * cos(2*pi*i/(N-1)) for i in range(N)]
```

$$
w[n] = 0.5 - 0.5 \cos\!\left(\frac{2\pi n}{N-1}\right)
$$

由於擷取的音框並非訊號的整數週期，直接做 DFT 會在邊界產生不連續，造成 **頻譜洩漏（spectral leakage）**。Hann 視窗讓兩端平滑趨近 0，抑制旁瓣（side lobe）。

**對照論文**
- F. J. Harris, *"On the Use of Windows for Harmonic Analysis with the Discrete Fourier Transform"*, Proc. IEEE, vol. 66, no. 1, pp. 51–83, 1978.

> 此篇系統性比較各種視窗（Hann、Hamming、Blackman 等）的旁瓣與主瓣特性，是視窗函數的權威參考。Hann 視窗以 Julius von Hann 命名。

---

## 6. 幅值轉分貝（對數刻度）

```python
mag = abs(spectrum[bin_lo + i]) * (2.0 / CHUNK)
db  = 20.0 * log10(mag + 1e-9)
```

- `2.0 / CHUNK`：單邊頻譜的幅值正規化（補回只取一半頻譜的能量，並消除 $N$ 倍縮放）。
- `20*log10`：將線性幅值換成 **分貝（dB）**，符合人耳對響度近似對數的感知（Weber–Fechner 定律）。
- `+ 1e-9`：避免 $\log(0)$ 數值錯誤。

之後把 dB 線性映射到 `[MIN_DB, MAX_DB] = [-80, 0]` 區間作為長條高度比例。

---

## 7. 顯示端的指數平滑

```python
self.smoothed[i] = SMOOTH_ALPHA * level + (1 - SMOOTH_ALPHA) * self.smoothed[i]
```

這是一階 **指數移動平均（EMA）**，等價於一階 IIR 低通濾波器：

$$
y_t = \alpha\, x_t + (1 - \alpha)\, y_{t-1}, \quad \alpha = 0.45
$$

目的是讓長條圖在每幀（`UPDATE_INTERVAL_MS = 40` ms）之間平滑過渡，降低視覺抖動，並非影響頻率分析本身的精度。

---

## 8. 複雜度總結

| 項目 | 複雜度 / 數值 |
| --- | --- |
| 直接 DFT | $O(N^2) = 1024^2 \approx 10^6$ 次運算 |
| 本程式 FFT | $O(N \log_2 N) = 1024 \times 10 \approx 10^4$ 次運算 |
| 頻率解析度 | $f_s / N \approx 43$ Hz / bin |
| 顯示更新率 | $1000 / 40 = 25$ FPS |

---

## 9. 參考文獻彙整

1. J. W. Cooley, J. W. Tukey, "An Algorithm for the Machine Calculation of Complex Fourier Series," *Math. Comput.*, 19(90):297–301, 1965.
2. F. J. Harris, "On the Use of Windows for Harmonic Analysis with the Discrete Fourier Transform," *Proc. IEEE*, 66(1):51–83, 1978.
3. C. E. Shannon, "Communication in the Presence of Noise," *Proc. IRE*, 37(1):10–21, 1949.
4. H. Nyquist, "Certain Topics in Telegraph Transmission Theory," *Trans. AIEE*, 47:617–644, 1928.
5. E. O. Brigham, *The Fast Fourier Transform and Its Applications*, Prentice-Hall, 1988.
6. T. H. Cormen et al., *Introduction to Algorithms*, 3rd ed., Ch. 30 (FFT), MIT Press, 2009.
