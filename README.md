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

The Affect tab shows Central/Peripheral trajectories and Emotional Index
z-scored against its own fixed baseline EI distribution. Record or load EYC and BSL first. SC decomposition starts on the
first one-second update, using the available history without edge exclusion. See [Affect visualization](docs/AFFECT_VISUALIZATION_DESIGN.md).

Metrics exposes one **SCL**, the tonic cvxEDA result. EI and the Peripheral
response use that same decomposed SCL and matching baseline references.
Metric readouts/rulers follow the selected normalization: original values retain
their source units; z-score uses baseline standard deviations; robust modes use
their respective baseline scale and min–max uses the baseline span. EI always
uses its own BSL z-score, independently of the selector. Metrics **Auto range**
continuously fits the vertical display range; **Fit** fits once and **−/+** hold
a manual zoom. These controls do not change values or normalization.

**ASR** is under the EEG filter settings in Sources. Press **Train (45 s)** to record an independent clean EEG sample and enable
correction, preserving every channel. EYC/BSL and live metrics use the cleaned
signal. Threshold changes reuse the training sample. The Raw Data ASR indicator
reports off, waiting, monitoring, correcting or bypassed. Its green LED pulses
for 0.5 seconds after backend reconstruction; monitoring stays gray. ASR changes filtered
traces; the Raw trace preserves original input. See [EEG ASR](docs/EEG_ASR.md).

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
