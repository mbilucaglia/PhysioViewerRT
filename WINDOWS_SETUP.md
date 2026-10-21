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

## Responsive LSL and rendering architecture

The GUI never waits for LSL source discovery or expanded channel metadata:
background control tasks resolve the stream descriptions and update the
selectors when ready. While metadata is loading, the selected modality's
**Play** button is disabled; playing streams in other modalities continue.

Each Receiver maintains a bounded, thread-safe mailbox of raw/filtered samples
and accompanying metric outputs. Instead of posting a GUI signal per LSL chunk,
the 30 FPS GUI timer drains these mailboxes in batches. A circular history
buffer avoids repeatedly copying 20 seconds of filtered signals per chunk.
The background raw renderer prepares at most one in-flight frame; painting
always remains on the GUI thread, and off-screen Raw Data panels are skipped.
Menus and active scroll movements take priority over visualization updates;
when interaction ends, GUI ingestion catches up in bounded batches.
EYC/BSL captures reject buffered LSL samples timestamped before recording
started, keeping baseline data independent of temporary GUI delays.
Receiver stop is asynchronous so stream changes do not block the interface.
LSL sample timestamps, metric algorithms and 5-minute plot history are retained.

### Optional performance report (Windows)

Open Command Prompt in the project folder and run:

```cmd
set PHYSIOLAB_PROFILE=1
start_windows.cmd
```

The application writes five-second summaries to
`%USERPROFILE%\\PhysioViewerRT-performance.jsonl`. The report includes
GUI timer delays, raw frame preparation/painting durations, and queue depths/
dropped-sample counts. It **does not record biosignal data or participant
information**. Reproduce scrolling and selector interactions for a few minutes,
then share the resulting JSONL log to diagnose any remaining stalls.
Unsetting `PHYSIOLAB_PROFILE` disables logging.

## Application tabs

- **Raw Data**: A vertically scrollable tab with enlarged waveform plots (EEG minimum 350 px high, EDA and PPG 300 px each); the lower plots and controls remain accessible by scrolling rather than being compressed. EEG, EDA/GSR, and PPG waveforms with independently switchable raw (solid) and filtered/processed (dashed) traces. The default view is **5 seconds**, with buffered history for **5 minutes**. Select 5 s / 10 s / 30 s / 1 min / 5 min, use **Zoom + / Zoom −**, or zoom and pan with the mouse to inspect the traces. Mouse-wheel time zoom keeps the newest samples visible in live-follow mode. Deliberately dragging/panning the time axis pauses following; the button changes to **Resume live (paused)** to make that state clear. The time axes of all three panels use a common LSL timestamp origin; trace rendering is downsampled for long windows to protect responsiveness. Incoming raw/filtered samples retain their original LSL timestamps instead of being re-timed on GUI arrival; duplicate or backward timestamps are rejected to prevent traces doubling back. A precise **30 FPS display timer** moves the live viewport between LSL deliveries without modifying recorded sample times. A monotone, jitter-resistant presentation clock advances the axes continuously and smoothly corrects LSL chunk arrival timing; it pauses when the publisher stops. Raw waveform cropping, decimation, and channel normalization now run on a **dedicated latest-only background thread**; Qt draws the prepared curves in the main thread. The GUI does not wait for older queued frames, and plotting is suspended while an axis context menu is open. The renderer scans only chunks overlapping the visible time range (not the full five-minute buffer) and freezes each channel's display scale after acquiring enough initial samples, to prevent vertical jumps. Waveform curves redraw on fresh samples or relevant display changes. Acquisition and metrics continue while the Metrics tab is open.
- **Metrics**: A vertically scrollable tab with a taller combined metrics plot (minimum 520 px high); metric readouts are placed below the plot and remain accessible by scrolling. One combined live plot of **AWI**, **BAR**, **SCL**, **HR** and **EI**, displaying **5 seconds by default** while retaining up to **5 minutes of metric history**, with individual plot-visibility checkboxes, a legend and their live values. Unchecking a metric hides only its plot curve, not its computation or numeric readout. A **Curve processing** toolbar offers **None / moving average / EMA / moving median** smoothing with selectable **1, 2, 3, 5 or 10 s** duration; interpolation choices are **None (points), linear, PCHIP (default), cubic spline**, plus a **Measured points** checkbox (on by default). These are display-only operations applied after the selected normalization. Smoothing is causal and gap-aware; interpolation is restricted to already observed points and cannot span missing readings or stream gaps. Plot interpolation at 20 points/s does not increase the physiological sampling rate (EEG metrics are typically 2 Hz). Numerical values, EI calculation and BSL statistics remain unchanged. Duplicate or backward **display timestamps** are ignored (with the latest reading retained on duplicate timestamps) so PCHIP/cubic interpolation cannot interrupt EYC/BSL save and refresh. Saved calibration recordings are unaffected. The Metrics time axis also moves on the independent **30 FPS display timer**, while metric curves and interpolation are only rebuilt when readings or display options change; physiological metrics still update at about 2 Hz. Choose a time window (5 s, 10 s, 30 s, 1 min, 5 min) or use **Zoom + / Zoom −**. Mouse-wheel time zoom preserves automatic live following, keeping the newest samples at the right edge. Drag/pan pauses following to inspect earlier data; **Resume live (paused)** returns to the latest samples. Direct **Load EYC…** and **Load BSL…** buttons on this tab select calibration files and display the current filenames. IAF is shown as an EEG calibration parameter, not as a plot line. The **Original** mode plots mixed physiological units on one y-axis; z-score, robust z-MAD, robust IQR and fixed min-max modes transform each metric using its saved BSL reference. Invalid/insufficient values appear as gaps. EI standardizes current HR and SCL using their fixed **BSL means and standard deviations**, then uses the supplied MATLAB `EI_matrix` formula (`theta = atan2(SCL_z, HR_z)` with HR horizontal; 2.5π quadrant correction for nonnegative SCL_z and nonpositive HR_z); no separate 60-second live EI warm-up is required; EI becomes available once valid, fresh HR and SCL estimates and their BSL reference statistics exist. Optional subsequent EI normalization uses the **BSL EI distribution**. EEG, EDA and PPG metrics retain 1-second windows with 50% overlap; HR uses a longer beat history.

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

## Experimental GPU Raw Data renderer (VisPy/OpenGL)

An optional A/B comparison of Raw Data visualization is available on branch
`experiment/vispy-raw-renderer`. It is inspired by the **LineVis**
OpenGL multi-channel rendering approach of Intheon's StreamViewer
(https://github.com/intheon/stream_viewer, MIT licensed), but is an
independent, lightweight renderer. No StreamViewer code is copied.

On Windows PowerShell, after switching to this branch and with the virtual
environment already installed:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-vispy.txt
.\start_windows.cmd
```

In the **Raw Data** tab, select the new **Waveform renderer** dropdown:
**pyqtgraph (original)** or **VisPy / OpenGL (experimental)**.
You can switch while synthetic LSL streams are playing. All processing,
Metrics, EYC/BSL and acquired timestamps still use the existing pipelines.

The OpenGL prototype batches multiple channels into one GPU line visual
per modality and trace layer (raw and filtered). It provides fixed channel
offsets, time-window and zoom buttons, live follow, show/hide raw and
filtered, and vertical page scrolling. **GPU mode currently omits the
pyqtgraph axis context menus and mouse-based plot panning.** Return to
pyqtgraph mode for those features; this is intentional so we can isolate
renderer performance before investing in alternative axis controls.

VisPy requires usable OpenGL drivers and may not work on all remote desktop
sessions. If OpenGL initialization fails, the app shows an error and retains
pyqtgraph. This experiment does not establish that the freeze is fixed.
Run the synthetic EEG+EDA+PPG workload for at least ten minutes with each
backend, and compare the optional performance JSONL profiles. Switching
renderers only affects Raw Data, not the Metrics tab.

## Experimental VisPy/OpenGL Metrics panel

Branch `experiment/vispy-metrics` extends the Raw Data GPU prototype with a
VisPy renderer for **Metrics**. Install the same optional dependencies:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-vispy.txt
.\start_windows.cmd
```

On a normal desktop, if VisPy is installed, **both Raw Data and Metrics default
to VisPy/OpenGL**; each tab has an independent renderer dropdown, so either
can be returned to the original pyqtgraph implementation. An offscreen test
session defaults to pyqtgraph.

The new Metrics canvas renders all five physiological series using the same
existing normalized/smoothed/interpolated arrays. Missing observations retain
their gaps; measured-point markers, axis labels, y-axis scaling, time-window,
zoom buttons, metric visibility switches, and live-follow remain supported.
Metrics OpenGL deliberately omits mouse-driven plot panning in this first
prototype; switch to pyqtgraph when manual dragging is needed. The series
legend is presently represented by the existing labeled metric checkboxes
rather than drawn within the GPU canvas.

Compare the same EEG, EDA and PPG synthetic session for at least ten minutes
with both tabs on VisPy, then switch Metrics alone back to pyqtgraph and verify
there are no changes to AWI, BAR, SCL, HR or EI values. These experiments do
not change calibration, samples, filters, numerical algorithms, or recordings.

## Shared VisPy engine and GPU sweep behavior

Raw Data and Metrics now reuse `physiolab/vispy_plot_engine.py` for the
white OpenGL background, viewport, axes, grid, scene and lifecycle.
The raw waveform renderer adds a **left-to-right sweep**: a completed pass
stays on the display while the following pass replaces it progressively.
The trace is split at sweep boundaries so the end of one pass is never
joined diagonally to the start of the next. This change is purely visual;
LSL timestamps, recording, processing and Metrics are not changed.

The default sweep window is **5 seconds**. The Raw Data **Time window**
selector offers 5, 8, 10, 15 and 30 seconds, and 1 or 5 minutes. Zoom
buttons adjust the same duration. Each modality has its own **vertical
amplitude** selector (0.25×, 0.5×, 1×, 2×, 4×, 8×); for EEG a single
factor applies consistently to all displayed EEG channels. Vertical
amplitude uses existing per-channel display normalization, and is **not**
a fixed ±100 µV scale or a physical calibration. Channel names are drawn
on the left of each GPU plot. All raw waveforms are red; processed
waveforms are black. The GPU canvas background is white in both tabs.

The two-pass sweep needs twice the selected time window in history. Existing
raw sample history is limited to five minutes, so at very long sweep
durations a full previous cycle cannot persist. The short 5–30s settings
are recommended for real-time viewing and stable two-cycle persistence.

Legacy pyqtgraph remains available as an independent fallback.

## Clinical three-tab UI and sweep controls (experimental)

The app now has **Raw Data**, **Metrics**, and **Sources** tabs. Stream
discovery, EEG/EDA/PPG source selectors, channel selectors and LSL Play/Stop
controls are on **Sources**. Reception and recording do not pause when
switching tabs.

The Raw Data tab is modeled on the clean clinical layout: a white GPU
plot for each EEG, PPG and skin conductance (EDA/SC) signal, with no axis
ticks/grids, red raw traces, black filtered traces and a **thin blue
sweep cursor**. There is no opaque white erase band. A draggable vertical
Qt splitter shares the available display height among the three plots;
dragging one divider enlarges one panel and reduces the adjacent panel.
The Raw Data default view does not need a vertical scrollbar.

**Amplitude** is adjusted independently for each of EEG, EDA/SC and
PPG using +/− buttons or an editable numeric spin box (0.05–50×).
The EEG amplitude multiplier applies equally to every displayed EEG
channel, not to physical units or a fixed 100 µV scale.

Both **Raw Data** and **Metrics** in VisPy use stable left-to-right
sweeps with the previous cycle retained until the cursor overwrites it.
Their default duration is 5 s and each tab retains its own time-window
selector and zoom controls. pyqtgraph remains available for the original
scrolling display. The plot cursor uses the shared VisPy scene engine,
and physiological algorithms, timestamps, calibration and recordings
are unchanged. Continuous gain and thin GPU cursor require the VisPy
renderer; they do not alter the historical pyqtgraph presentation.

## Incremental GPU sweep architecture — Raw Data and Metrics

Branch `experiment/incremental-gpu-sweep` contains a shared
`physiolab/incremental_sweep.py` implementation for **all** VisPy plots.
Each waveform channel (both raw and filtered) and each metric
(AWI, BAR, SCL, HR, EI, plus measured-point markers) has a persistent,
fixed-capacity sweep ring backed by a VisPy OpenGL vertex buffer.
New arrivals overwrite only the affected bins through partial
`VertexBuffer.set_subdata()` uploads. Already-drawn segments stay unchanged
until the sweep overwrites them. The same ring handles wraparound, NaN
observations and timestamps that skip bins. The blue sweep cursor does
not advance beyond the most recent real sample.

For Raw Data, the existing worker now crops and normalizes **only newly
arriving samples** once the initial sweep and fixed channel scaling have
been established. Its clock-anchored decimation rate stays consistent
with the full selected window. The existing acquisition and processing
pipelines are unchanged.

For Metrics, the existing normalization/smoothing/interpolation functions
still compute the mathematical values; the new renderer uploads only new
display vertices and points, not the complete trace. History is explicitly
replayed if the time window, normalization, smoothing, interpolation,
stream/source, or calibration reference changes. Live vertical limits
expand only when necessary to avoid rescaling flicker.

To test on your Windows notebook:
```powershell
git fetch origin
git switch --track origin/experiment/incremental-gpu-sweep
.venv\Scripts\python.exe -m pip install -r requirements-vispy.txt
.\start_windows.cmd
```
If the branch already exists locally use `git switch
experiment/incremental-gpu-sweep` followed by `git pull`.

This is a renderer experiment, not a claim that Intel/OpenGL behavior is
validated. Observe the Raw and Metrics tabs for at least 10 minutes while
all three LSL streams play, and inspect the regions before and after the
blue cursor for any retained holes or cross-boundary connections.

## Edit the actual GUI using Qt Designer (experimental PR #26)

The running application loads `designer/PhysioViewerRT_ClinicalLayout.ui`
on every launch, via PySide6 `QUiLoader`. Unlike the earlier mockup,
**this file is now the authoritative source of widget placement, top-level
tab order, plot hosts, main toolbar controls, font and stylesheet**.
The Python controller `physiolab/gui.py` finds widgets by `objectName`
and attaches the existing LSL receivers, metric processors and VisPy
incremental GPU canvases at runtime.

To edit it on Windows:

1. Switch to `experiment/clinical-ui-controls` and pull.
2. Open `designer/PhysioViewerRT_ClinicalLayout.ui` with Qt Designer.
3. Drag/rearrange widgets, change stylesheet properties or reorder tabs.
4. Save the same file and restart PhysioViewerRT.

Plot placeholders (`EEGPlotHost`, `PPGPlotHost`, `EDAPlotHost`,
`metricsPlotHost`) are ordinary editable Qt `QFrame` containers.
At runtime the controller inserts its QStackedWidget containing pyqtgraph
and the existing VisPy `SceneCanvas.native` into each host. Resizing those
containers in Designer therefore resizes the real waveform panels; the
single vertical `rawPlotSplitter` can also be dragged during a session.

**Keep objectName properties unchanged** for connected controls and plot
hosts, since they form the contract between Designer and Python.
Changing labels, size policies, layouts, tab order, fonts or colors is safe.
The application reports the missing widget's name if the contract breaks.

The initial integration retains the existing calibration and processing
algorithms. Source-selection controls, baseline New/Load/Default entry
points, renderer switches and plot-only pause controls are connected.
The follow-up clinical-workflow changes (preprocessing preset semantics,
EEG display count, calibration-gated Metrics, and subtle plot axes)
are a separate stage; they are **not implied** by visual placeholders.
Do not merge draft PR #26 until a test on the target Windows GPU passes.
