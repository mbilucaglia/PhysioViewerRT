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

See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for calibration and detailed controls.

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
