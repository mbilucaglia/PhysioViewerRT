# PhysioViewerRT Windows MVP

Local Python desktop application for LSL EEG, EDA/GSR and PPG monitoring.

## Windows 10/11 quick start

1. Have 64-bit Python 3.11 or 3.12 available. The installer accepts either the `python` command on PATH **or** the optional Windows `py` launcher. It does not require `py.exe` if `python` already works.
2. Clone or download the `feature/windows-lsl-mvp` branch into a writable folder.
3. Double-click `setup_windows.cmd` to create `.venv` and install dependencies.
4. Double-click `simulate_windows.cmd` to start demonstration EEG/EDA/PPG streams, or start your hardware LSL outlets.

### Synthetic LSL sources

The simulator now publishes **32 labeled EEG channels at 256 Hz** (Fp1/Fp2, F3/F4, O1/O2 and other standard montage electrodes), **EDA/skin conductance at 32 Hz** and **PPG at 128 Hz**. Signals vary over time: alpha/beta/slow EEG rhythms and frontal alpha asymmetry, tonic/phasic SCR events, and beat-to-beat heart-rate/pulse-amplitude variability. The EEG is expressed in approximate microvolts, EDA in microsiemens, and PPG in arbitrary units.

It also adds intermittent **common recording artifacts**, with default *moderate* severity: frontal blinks, temporal EMG bursts, electrode pops and slow drift (EEG); skin-electrode contact shifts and scratch-like motion (EDA); and transient optical-contact loss and wrist-motion oscillations (PPG). These are stylized simulations, not measured artifacts or physiological ground truth.

To select intensity from CMD instead of using `simulate_windows.cmd` defaults:

```cmd
.venv\\Scripts\\python.exe simulate.py --artifacts mild
.venv\\Scripts\\python.exe simulate.py --artifacts strong --seed 42
.venv\\Scripts\\python.exe simulate.py --artifacts none
```

Supported levels: `none`, `mild`, `moderate` (default), `strong`. The `--seed` argument makes results reproducible. Stop the old simulator before restarting with a different intensity. At least 60 s of simulator data is needed to capture a full baseline, and artifact-heavy simulated baselines can destabilize estimated references.

5. Double-click `start_windows.cmd`. Press **Refresh LSL**, select a stream and its channels for each modality, then press **▶ Play**.

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

- **Record EYC (60 s)...**: connect EEG first; follow the instruction to **Close your eyes**. A separate black movable, resizable, maximizable instruction window runs for 60 seconds. It initially overlays the application plots but can be dragged to another monitor. When it ends, the app displays **Open your eyes**. The acquired EEG is analyzed using the **average posterior-channel PSD**, Welch's method (Hann window, **1-second segments, 50% overlap**). The IAF is the **spectral center of gravity of 7–13 Hz**: sum(f * PSD(f)) / sum(PSD(f)). An inspection window plots the average PSD and IAF marker. The app then asks whether to **Save**. No posterior labeled channels -> EYC is rejected (no invented IAF); O1/O2/Oz/PO*/P*/TP* and related posterior labels are supported.
- **Record BSL (60 s)...**: connect all modalities to include in baseline before starting. Follow the instruction **Look at the dot**. A separate movable, resizable, maximizable black window displays a white fixation dot and countdown for 60 seconds. It starts over the plots and can be moved to a second monitor. The app then shows a table of **mu, sigma, median, IQR** (also MAD and quantile bounds) for available EEG/EDA/PPG metrics and EI when both HR and SCL are valid, computed at the existing **1-second/50%-overlap** cadence. The app asks whether to **Save**.
- **Load EYC file... / Load BSL file...**: open previously saved calibration files and inspect the stored analyses. Loaded BSL files are reanalyzed from their saved signals to ensure EI reference statistics use the current MATLAB convention. EYC sets the alpha band center used for AWI; BSL provides fixed references for normalization in the Metrics tab.
- **File format:** compressed `.npz`, with samples, LSL timestamps, sampling rates, channel labels and computed analysis; loaded without Python pickle.
- **Cancel:** Esc during a calibration recording discards the capture. Disconnects or insufficient samples reject the recording; no calibration is saved automatically.

**Recommended order:** EYC, then BSL, then live metrics. EYC needs labeled posterior EEG channels; the synthetic EEG simulator includes O1/O2 for testing. If EYC is not loaded, IAF defaults to **10 Hz** (alpha window 8–12 Hz). If no BSL is loaded, the **Original (identity)** mode shows unnormalized metrics. Other normalization choices require compatible saved BSL statistics. z-MAD uses median and 1.4826×MAD, robust-IQR uses median and IQR/1.349, and min-max uses **fixed BSL extrema**; no live moving extrema.

**Limits:** The EYC spectral center of gravity is not equivalent to a clear alpha peak or a validation of calibration signal quality. Current prototype does not implement dedicated artifact rejection for calibration windows or stream clock drift correction. Use the same montage, units, and signal-processing setup when reusing BSL references. IAF/BSL compatibility is not yet enforced by the UI. Subject-specific physiological metric validity must be verified before neurofeedback.

## Application tabs

- **Raw Data**: A vertically scrollable tab with enlarged waveform plots (EEG minimum 350 px high, EDA and PPG 300 px each); the lower plots and controls remain accessible by scrolling rather than being compressed. EEG, EDA/GSR, and PPG waveforms with independently switchable raw (solid) and filtered/processed (dashed) traces. The default view is **5 seconds**, with buffered history for **5 minutes**. Select 5 s / 10 s / 30 s / 1 min / 5 min, use **Zoom + / Zoom −**, or zoom and pan with the mouse to inspect the traces. Mouse-wheel time zoom keeps the newest samples visible in live-follow mode. Deliberately dragging/panning the time axis pauses following; the button changes to **Resume live (paused)** to make that state clear. The time axes of all three panels use a common LSL timestamp origin; trace rendering is downsampled for long windows to protect responsiveness. Incoming raw/filtered samples retain their original LSL timestamps instead of being re-timed on GUI arrival; duplicate or backward timestamps are rejected to prevent traces doubling back. Acquisition and metrics continue while the Metrics tab is open.
- **Metrics**: A vertically scrollable tab with a taller combined metrics plot (minimum 520 px high); metric readouts are placed below the plot and remain accessible by scrolling. One combined live plot of **AWI**, **BAR**, **SCL**, **HR** and **EI**, displaying **5 seconds by default** while retaining up to **5 minutes of metric history**, with individual plot-visibility checkboxes, a legend and their live values. Unchecking a metric hides only its plot curve, not its computation or numeric readout. A **Curve processing** toolbar offers **None / moving average / EMA / moving median** smoothing with selectable **1, 2, 3, 5 or 10 s** duration; interpolation choices are **None (points), linear, PCHIP (default), cubic spline**, plus a **Measured points** checkbox (on by default). These are display-only operations applied after the selected normalization. Smoothing is causal and gap-aware; interpolation is restricted to already observed points and cannot span missing readings or stream gaps. Plot interpolation at 20 points/s does not increase the physiological sampling rate (EEG metrics are typically 2 Hz). Numerical values, EI calculation and BSL statistics remain unchanged. Choose a time window (5 s, 10 s, 30 s, 1 min, 5 min) or use **Zoom + / Zoom −**. Mouse-wheel time zoom preserves automatic live following, keeping the newest samples at the right edge. Drag/pan pauses following to inspect earlier data; **Resume live (paused)** returns to the latest samples. Direct **Load EYC…** and **Load BSL…** buttons on this tab select calibration files and display the current filenames. IAF is shown as an EEG calibration parameter, not as a plot line. The **Original** mode plots mixed physiological units on one y-axis; z-score, robust z-MAD, robust IQR and fixed min-max modes transform each metric using its saved BSL reference. Invalid/insufficient values appear as gaps. EI standardizes current HR and SCL using their fixed **BSL means and standard deviations**, then uses the supplied MATLAB `EI_matrix` formula (`theta = atan2(SCL_z, HR_z)` with HR horizontal; 2.5π quadrant correction for nonnegative SCL_z and nonpositive HR_z); no separate 60-second live EI warm-up is required; EI becomes available once valid, fresh HR and SCL estimates and their BSL reference statistics exist. Optional subsequent EI normalization uses the **BSL EI distribution**. EEG, EDA and PPG metrics retain 1-second windows with 50% overlap; HR uses a longer beat history.

The current non-calibrated EEG default is **IAF 10 Hz**, with alpha power integrated over **8–12 Hz** (IAF ± 2 Hz). Guided EYC/BSL file capture and basic z-score/z-MAD/fixed-min-max normalization are implemented. ASR, PPG wavelets, and EDA artifact correction remain unimplemented.

## Assigning streams and channels

Each modality has two controls: **LSL stream** (every available stream is listed regardless of its LSL type) and **Channels** (checkbox dropdown). **EEG** supports one or more selected channels, with all channels checked initially. **EDA/GSR** and **PPG** each require exactly one checked channel. A single multichannel LSL stream may be independently connected for more than one modality; each receiver processes only its chosen columns. The source channel labels and selected order are retained for live plots, metrics, EYC and BSL recordings. Channel labels are read from **expanded metadata returned by the LSL inlet**, not just the abbreviated results of stream discovery. If the publisher supplies no channel labels or names, the picker shows `Ch1 (unlabeled)` and similar placeholders; configure electrode names in the source application. The collapsed selector shows abbreviated selected labels, and hovering reveals the full list. Check that channel labels match the actual EEG montage: AWI requires F3/F4 or Fp1/Fp2, and EYC needs posterior channel labels.

Each modality has its own **▶ Play / ■ Stop** button. Play starts local acquisition, waveform plotting and metric updates for that stream; Stop terminates only the app's receiver and closes its inlet, **not** the external LSL outlet/simulator. Stop clears the selected modality's live curves and metric history; stopping EDA or PPG clears recent EI readings but **retains the loaded BSL references**. To change an active stream or channel selection, press **Stop**, choose the new source/channels, then press **Play**. Recording an EYC/BSL calibration prevents stream stopping or changing until calibration finishes or is cancelled. Refreshing LSL repopulates the channel choices. The same source must have a positive nominal sample rate.

## Expected streams

All LSL stream types are available in each modality's stream menu. Assign the appropriate channels for EEG, EDA/GSR and PPG. EEG AWI uses F3/F4 labels (falling back to Fp1/Fp2).

## Metrics and timing

- Causal 50 Hz and 100 Hz IIR notch filters (Q=30) for EEG, EDA and PPG where the nominal stream rate has Nyquist strictly above the notch frequency. Frequencies at/above Nyquist are automatically skipped: at 128 Hz, only 50 Hz is available; at 256 Hz, both apply. For EEG and PPG, existing modality band-pass filters are applied after the notches.
- Continuous causal EEG band-pass (1–40 Hz) and PPG band-pass (0.5–8 Hz), limited by Nyquist.
- Nominal 1-second analysis windows with 50% overlap: metrics are evaluated approximately every 500 ms.
- AWI = ln(alpha power F4) − ln(alpha power F3) from Welch PSD over 8–12 Hz (default IAF 10 Hz ± 2 Hz).
- BAR = (mean 13–30 Hz beta power across eligible EEG channels) / (mean IAF±2 Hz alpha power across those channels), from a 1-second Hann-windowed Welch PSD. If insufficient spectral support, BAR is unavailable.
- EDA: one-second median skin-conductance level, in source units.
- PPG: heart rate from valid pulse intervals over up to 10 seconds of signal history; **not** a one-second-only HR estimate.
- Graph refresh approximately 25 FPS; displayed channels are normalized independently.

## Research prototype limitations

Not a medical device. Do not use for clinical decisions. Missing automated artifact detection, channel-quality gating, reference selection, inter-stream timestamp alignment, general recording/replay, SCR detection, sophisticated calibration artifact rejection, and closed-loop neurofeedback. The PPG peak detector is heuristic; the AWI and BAR estimates from one second are noisy. Simulated signals validate the software path only, not biological accuracy. Confirm montage, units, sampling rates, and signal quality with real hardware. The application has not undergone an end-to-end hardware/Windows integration test. Packaging as a standalone EXE is not yet provided.
