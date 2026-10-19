# PhysioViewerRT Windows MVP

Local Python desktop application for LSL EEG, EDA/GSR and PPG monitoring.

## Windows 10/11 quick start

1. Have 64-bit Python 3.11 or 3.12 available. The installer accepts either the `python` command on PATH **or** the optional Windows `py` launcher. It does not require `py.exe` if `python` already works.
2. Clone or download the `feature/windows-lsl-mvp` branch into a writable folder.
3. Double-click `setup_windows.cmd` to create `.venv` and install dependencies.
4. Double-click `simulate_windows.cmd` to start demonstration EEG/EDA/PPG streams, or start your hardware LSL outlets.
5. Double-click `start_windows.cmd`, press **Refresh LSL**, and connect each modality.

If the installer cannot locate Python, open Command Prompt and run `python --version`, `where python`, and `py --list`. The command may be unavailable even though Python is installed, if its directory is missing from PATH. Python 3.13+ or 32-bit-only installations are not selected by this MVP installer. If an old/incomplete `.venv` exists, delete that folder and rerun setup.

Internet access is needed for the dependency installation, but not for ordinary local operation. LSL may trigger a Windows Defender Firewall prompt; allow only on trusted/private networks.

## Cross-platform development setup

```bash
python -m venv .venv
# On Windows: .venv\Scripts\activate
# On macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python simulate.py  # optional, in terminal 1
python main.py      # terminal 2
```

If `pylsl` cannot find the compatible `liblsl` shared library, install the appropriate OS binary and follow pylsl's library-loading instructions.

## Application tabs

- **Raw Data**: EEG, EDA/GSR, and PPG waveforms with independently switchable raw (solid) and filtered/processed (dashed) traces. Acquisition and metrics continue while the Metrics tab is open.
- **Metrics**: EEG FAA and alpha powers, EDA SCL, and PPG HR, with per-modality status. Metrics use 1-second windows and 50% overlap; HR uses an extended pulse history.

The current non-calibrated EEG default is **IAF 10 Hz**, with alpha power integrated over **8–12 Hz** (IAF ± 2 Hz). Subject-specific IAF calibration, z-score/z-MAD, ASR, PPG wavelets, and EDA artifact correction are not yet implemented in this branch.

## Expected streams

LSL stream types must be `EEG`, `EDA` or `GSR`, and `PPG`. EEG alpha asymmetry uses F3 and F4 labels (falls back to Fp1 and Fp2).

## Metrics and timing

- Continuous causal EEG band-pass (1–40 Hz) and PPG band-pass (0.5–8 Hz), limited by Nyquist.
- Nominal 1-second analysis windows with 50% overlap: metrics are evaluated approximately every 500 ms.
- FAA = ln(alpha power F4) − ln(alpha power F3) from Welch PSD over 8–12 Hz (default IAF 10 Hz ± 2 Hz).
- EDA: one-second median skin-conductance level, in source units.
- PPG: heart rate from valid pulse intervals over up to 10 seconds of signal history; **not** a one-second-only HR estimate.
- Graph refresh approximately 25 FPS; displayed channels are normalized independently.

## Research prototype limitations

Not a medical device. Do not use for clinical decisions. Missing automated artifact detection, channel-quality gating, reference selection, inter-stream timestamp alignment, recording/replay, notch filtering, SCR detection, baseline calibration, and closed-loop neurofeedback. The PPG peak detector is heuristic; the FAA estimate from one second is noisy. Simulated signals validate the software path only, not biological accuracy. Confirm montage, units, sampling rates, and signal quality with real hardware. The application has not undergone an end-to-end hardware/Windows integration test. Packaging as a standalone EXE is not yet provided.
