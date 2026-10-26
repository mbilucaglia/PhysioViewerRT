# PhysioViewerRT

Local desktop prototype for real-time LSL biosignal visualization and research neurofeedback (EEG, EDA/GSR and PPG).

The desktop app uses PySide6 and VisPy/OpenGL for live waveforms and metrics,
with pylsl acquisition and NumPy/SciPy processing. pyqtgraph remains available
as a compatibility fallback. This repository is not a validated medical device.

## Run on Windows

Run `setup_windows.cmd` once, `simulate_windows.cmd` for demonstration streams,
then `start_windows.cmd`. In Sources, refresh LSL, select the source and channels
for each modality, and press Play. Raw Data shows the live waveforms; gain,
channel count, sweep duration, and plot pause change the display only.

Raw Data uses a fixed 50 ms presentation buffer. PPG/SC use small delivery
blocks; Hampel adds three samples of lookahead. A slower stream retains its
own timestamps without delaying the other panels. Hardware/network batching
and wavelet buffering can still add delay.

The Affect tab shows Central/Peripheral trajectories and Emotional Index.
Every displayed metric follows that tab's selected normalization using its own
fixed baseline distribution. Record or load EYC and BSL first. SC decomposition starts on the
first one-second update, using the available history without edge exclusion. See [Affect visualization](docs/AFFECT_VISUALIZATION_DESIGN.md).

Metrics exposes one **SCL**, the tonic cvxEDA result. EI and the Peripheral
response use that same decomposed SCL and matching baseline references.
Metric readouts/rulers follow the selected normalization: original values retain
their source units; z-score uses baseline standard deviations; robust modes use
their respective baseline scale and min–max uses the baseline span. EI follows
the same selector as the other metrics. Its internal formula still requires HR
and SCL z-scores; that computation is separate from display normalization. Metrics **Auto range**
continuously fits the vertical display range; **Fit** fits once and **−/+** hold
a manual zoom. These controls do not change values or normalization.

**ASR** is under the EEG filter settings in Sources. Press **Train (auto · ≥60 s)** to record an independent clean EEG sample and enable
correction, preserving every channel. EYC/BSL and live metrics use the cleaned
signal. Threshold changes update cached rejection thresholds without retraining. The Raw Data ASR indicator
reports off, waiting, monitoring, correcting or bypassed. Its green LED pulses
for 0.5 seconds after backend reconstruction; monitoring stays gray. ASR changes filtered
traces; the Raw trace preserves original input. See [EEG ASR](docs/EEG_ASR.md).


PPG and SC Processing panels offer **Off**, **Spike reduction (Hampel)** and
**Wavelet (8 s · experimental)**. Choose processing before recording BSL; changing
it requires a matching baseline. Hampel waits three samples. Wavelet buffers
eight seconds initially, then updates every second. Raw and processed traces
share original timestamps; metric histories use their source window end.
A small dot beside each Raw Data signal title shows recent waveform modification
(green), buffering/waiting (amber), or no current modification (gray). Hover for
the exact state. Wavelet can modify clean signals continuously; green does not
guarantee artifact removal. Wavelet can alter real pulse/SCR morphology. These are research-based streaming
adaptations with synthetic/LSL tests; real-hardware efficacy remains unverified.
See [method sources, parameters and limits](docs/PERIPHERAL_REDUCTION_EVIDENCE.md).
After pulling, rerun `setup_windows.cmd` to install pinned PyWavelets.

See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for calibration and detailed controls.

For continuation on another PC, see the setup steps and prioritized tasks in [TODO.md](TODO.md).

## Extending and maintaining the app

See [Application boundaries and extension guide](docs/ARCHITECTURE.md) for state
ownership, shared settings, and adding metrics. See
[Rendering behavior and validation](docs/RENDERING.md) for sweep, amplitude and
GPU resource rules.

## Validation

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m unittest discover -s tests_gui
```

The GUI suite includes real local LSL outlets for EEG, EDA and PPG. To exercise
the installed Windows OpenGL drivers with a visible 32-channel Raw Data window:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
.venv\Scripts\python.exe -m unittest discover -s tests_gui -p test_lsl_integration.py
```

These checks validate the software path using synthetic signals. Physical
devices and long sessions still need validation on the target setup.


Adaptive ASR training counts **accepted EEG seconds**, rather than stopping at a
fixed wall-clock duration. The quality popup gives the subject live instructions:
green = no obvious problems detected; amber = possible movement, relax and keep
still; red = check signal/electrodes or connection. Two startup windows and
windows with detected problems do not increase accepted time. Screening uses
one-second windows, channel flatness/plateaus, channel dependence and transient
amplitude relative to the median of earlier accepted windows (last 30 windows).
It is a heuristic, not a guarantee of artifact-free EEG.

Training automatically completes after at least 60 accepted seconds **and** a
successful backend fit. On fitting failure, it collects 10 more accepted seconds
before retrying (up to 180 stored accepted seconds and a five-minute session).
Cancel/timeout preserves the previous model. Original timestamps and window
boundaries are retained; continuous conversion/filtering happens before window
selection, and ASR is not applied to the training input. The library must still
retain at least 30 clean seconds for fitting. Validate screening and calibration
success on representative real EEG before relying on the quality flag.


Changing the ASR cutoff preserves the learned calibration and updates only its
rejection threshold matrix. The initial training caches RMS distribution factors
using the pinned backend routines. Threshold changes do not record EEG, repeat
clean-window selection, or fit calibration again. Matching EYC/BSL references
are replayed because correction behavior has changed. Raw-only EEG is centered
on raw values; cleaned-only and overlaid raw/cleaned views center on cleaned EEG.
