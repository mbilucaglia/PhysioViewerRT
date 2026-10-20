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

## EYC and BSL guided calibrations

Use **Calibration** in the application menu:

- **Record EYC (60 s)...**: connect EEG first; follow the instruction to **Close your eyes**. A black fullscreen instruction screen runs for 60 seconds. When it ends, the app displays **Open your eyes**. The acquired EEG is analyzed using the **average posterior-channel PSD**, Welch's method (Hann window, **1-second segments, 50% overlap**). The IAF is the **spectral center of gravity of 7–13 Hz**: sum(f * PSD(f)) / sum(PSD(f)). An inspection window plots the average PSD and IAF marker. The app then asks whether to **Save**. No posterior labeled channels -> EYC is rejected (no invented IAF); O1/O2/Oz/PO*/P*/TP* and related posterior labels are supported.
- **Record BSL (60 s)...**: connect all modalities to include in baseline before starting. Follow the instruction **Look at the dot**. A black fullscreen window displays a white fixation dot for 60 seconds. The app then shows a table of **mu, sigma, median, IQR** (also MAD and quantile bounds) for available EEG/EDA/PPG metrics, computed at the existing **1-second/50%-overlap** cadence. The app asks whether to **Save**.
- **Load EYC file... / Load BSL file...**: open previously saved calibration files and inspect the stored analyses. EYC sets the alpha band center used for FAA; BSL provides fixed references for normalization in the Metrics tab.
- **File format:** compressed `.npz`, with samples, LSL timestamps, sampling rates, channel labels and computed analysis; loaded without Python pickle.
- **Cancel:** Esc during a fullscreen recording discards the capture. Disconnects or insufficient samples reject the recording; no calibration is saved automatically.

**Recommended order:** EYC, then BSL, then live metrics. EYC needs labeled posterior EEG channels; the synthetic EEG simulator includes O1/O2 for testing. If EYC is not loaded, IAF defaults to **10 Hz** (alpha window 8–12 Hz). If no BSL is loaded, the **Original (identity)** mode shows unnormalized metrics. Other normalization choices require compatible saved BSL statistics. z-MAD uses median and 1.4826×MAD, robust-IQR uses median and IQR/1.349, and min-max uses **fixed BSL extrema**; no live moving extrema.

**Limits:** The EYC spectral center of gravity is not equivalent to a clear alpha peak or a validation of calibration signal quality. Current prototype does not implement dedicated artifact rejection for calibration windows or stream clock drift correction. Use the same montage, units, and signal-processing setup when reusing BSL references. IAF/BSL compatibility is not yet enforced by the UI. Subject-specific physiological metric validity must be verified before neurofeedback.

## Application tabs

- **Raw Data**: EEG, EDA/GSR, and PPG waveforms with independently switchable raw (solid) and filtered/processed (dashed) traces. Acquisition and metrics continue while the Metrics tab is open.
- **Metrics**: EEG FAA and alpha powers, EDA SCL, and PPG HR, with per-modality status. Metrics use 1-second windows and 50% overlap; HR uses an extended pulse history.

The current non-calibrated EEG default is **IAF 10 Hz**, with alpha power integrated over **8–12 Hz** (IAF ± 2 Hz). Guided EYC/BSL file capture and basic z-score/z-MAD/fixed-min-max normalization are implemented. ASR, PPG wavelets, and EDA artifact correction remain unimplemented.

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

Not a medical device. Do not use for clinical decisions. Missing automated artifact detection, channel-quality gating, reference selection, inter-stream timestamp alignment, general recording/replay, notch filtering, SCR detection, sophisticated calibration artifact rejection, and closed-loop neurofeedback. The PPG peak detector is heuristic; the FAA estimate from one second is noisy. Simulated signals validate the software path only, not biological accuracy. Confirm montage, units, sampling rates, and signal quality with real hardware. The application has not undergone an end-to-end hardware/Windows integration test. Packaging as a standalone EXE is not yet provided.
