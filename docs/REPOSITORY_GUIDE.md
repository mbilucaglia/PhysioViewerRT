# Repository guide

Start with [README](../README.md) to run the viewer, [Windows setup](../WINDOWS_SETUP.md)
for installation, and [architecture](ARCHITECTURE.md) to understand ownership and
extension points. This guide is a file map for navigating the code and deciding
which checks to run after a change.

## Workspaces and startup

| File or directory | Role |
| --- | --- |
| `main.py`, `start_windows.cmd` | Start the Qt application; the Windows launcher uses the local virtual environment. |
| `simulate.py`, `simulate_windows.cmd` | Publish synthetic EEG, PPG, and SC over LSL so the viewer can run without hardware. |
| `setup_windows.cmd` | Select a compatible Python, create `.venv`, and install the viewer dependencies. |
| `requirements.txt` | Main dependency entry point; includes the renderer, affect, and ASR manifests. |
| `requirements-vispy.txt`, `requirements-affect.txt`, `requirements-asr.txt` | Declare the VisPy rendering, cvxEDA decomposition, and meegkit ASR dependencies, respectively. |
| `README.md`, `WINDOWS_SETUP.md`, `TODO.md` | Quick start, setup and operation, and handoff priorities. |
| `.github/workflows/calibration-tests.yml` | Installs dependencies and runs core tests and Windows GUI checks in CI. |
| `.gitignore` | Keeps the environment, caches, build outputs, and `local-recordings/` outside tracked source. |
| `physiolab/` | Viewer code, grouped below. Package `__init__.py` files define importable namespaces. |
| `designer/`, `assets/` | Qt layout definitions and the images/icons they load at runtime. |
| `tests/`, `tests_gui/` | Core and Qt/integration regression suites. |
| `tools/`, `docs/` | Developer validation utilities, design notes, and example output. |
| `.venv/`, `.test-tmp/`, `local-recordings/` | Local dependencies, generated test outputs, and an optional home for private recordings. |
| Shimmer-LSL | Separate hardware bridge and repository. Local Shimmer files are not dependencies of the viewer. |

The working tree is the files currently on disk. A Git branch such as `main` is
a commit reference and can point elsewhere. Use `git status --short --branch`
to identify the active checkout before editing. A separate checkout can run
another branch without moving edits from this one.

On this checkout, existing baseline recordings and standalone Shimmer copies
stay at their original paths and are hidden from Git status by local exclusions.
Save new private recordings under `local-recordings/`.

## Data path

`main.py` starts `ui/gui.py`. The GUI discovers streams, then starts a receiver
for each selected modality. Receivers align samples and timestamps, apply source
conversion, and pass samples into the processing chain. Processing computes
observations from retained windows; the receiver delivers raw and processed
samples plus observations through a mailbox. Rendering consumes those outputs
without changing the samples used to calculate metrics. EYC and BSL use the
same relevant preprocessing when deriving references, whether ASR is on or off.

## Application files

The file names in each table are relative to the package named above it.

### `physiolab/`

| File | Role |
| --- | --- |
| `settings.py` | Validated immutable settings for viewer timing, history capacity, display defaults, and controls. |

### `physiolab/acquisition/`

| File | Role |
| --- | --- |
| `acquisition_contracts.py` | Defines the named chunk passed from the receiver to the GUI, including signal arrays, timestamps, and observations. |
| `channel_selection.py` | Resolves LSL channel labels, validates indices, and extracts selected columns in order. |
| `display_units.py` | Reads channel unit metadata and translates it into source labels and EEG display scaling. |
| `ingress.py` | Uses a locked bounded mailbox to deliver batches without a GUI event per sample. |
| `lsl_tasks.py` | Runs discovery and metadata lookups in Qt worker threads. |
| `raw_timing.py` | Removes invalid or non-increasing timestamps, slices visible chunks, and tracks viewport timing. |
| `signal_buffer.py` | Stores a bounded rolling sample window in a ring. |
| `source_conversion.py` | Validates gain, offset, and units, then converts selected samples once at ingress. |
| `worker.py` | Opens and drains an LSL inlet, processes chunks, attaches metric provenance, and delivers outputs to the mailbox. |

### `physiolab/signals/`

| File | Role |
| --- | --- |
| `processing.py` | Runs stateful preprocessing and optional transforms, retains raw/processed histories, and schedules metric windows. |
| `processing_filters.py` | Validates presets and builds causal SciPy second-order filter sections, including notches. |
| `peripheral_reduction.py` | Applies bounded Hampel or wavelet processing for PPG and SC, with explicit buffering and timestamp alignment. |
| `peripheral_runtime.py` | Translates reducer progress and recent activity into a status for the UI. |
| `sc_decomposition.py` | Uses cvxEDA to derive tonic SCL; live and baseline paths attach timing and configuration metadata. |
| `synthetic.py` | Generates seeded, labeled EEG, PPG, and SC signals with optional artifacts for demos and tests. |

### `physiolab/asr/`

| File | Role |
| --- | --- |
| `eeg_asr.py` | Adapts meegkit for model training and streaming correction, with source compatibility and channel-preservation checks. |
| `asr_quality.py` | Formats measured training/model information for the training report. |
| `asr_runtime.py` | Derives ASR status from the current receiver, startup, and correction timestamps. |
| `asr_session.py` | Owns independent training data, model selection, enablement, and reference-task generations. |
| `asr_tasks.py` | Fits models and replays matching EYC/BSL references in background tasks; replay accepts a plain filtered path without ASR. |
| `asr_training.py` | Accumulates fresh continuous training windows and tracks eligibility/accepted samples. |

### `physiolab/calibrations/`

| File | Role |
| --- | --- |
| `calibration.py` | Derives IAF from EYC, summarizes BSL metric distributions, normalizes values, and reads/writes validated NPZ recordings. |
| `calibration_session.py` | Captures fresh samples with fixed source metadata and checks recording completeness. |
| `calibration_tasks.py` | Runs calibration analysis off the Qt GUI thread and returns its result or error. |

### `physiolab/metrics/`

| File | Role |
| --- | --- |
| `physiological_metrics.py` | Defines metric windows and calculations: EEG spectral AWI/BAR, PPG peak-based HR, and the SC decomposition handoff. |
| `metric_catalog.py` | Defines modality/name keys, labels, units, colors, and presentation metadata. |
| `metric_observation.py` | Records source-window times, processing provenance, and canonical source configuration. |
| `metric_state.py` | Retains histories and latest observations, computes derived EI, and applies display normalization. |
| `metric_display.py` | Prepares display curves and unit labels; interpolation and smoothing leave measured observations intact. |
| `emotion.py` | Computes EI from HR and tonic SCL with baseline references, retaining the latest compatible inputs. |
| `affect_state.py` | Pairs normalized observations into Central and Peripheral trajectories with timestamps and freshness checks. |

### `physiolab/rendering/`

| File | Role |
| --- | --- |
| `amplitude_display.py` | Computes visible amplitude/gain from selected traces and the visible window. |
| `incremental_sweep.py` | Maintains bounded sweep-ring geometry and incrementally updates GPU layers. |
| `performance.py` | Aggregates optional timing measurements for rendering and acquisition diagnostics. |
| `raw_display_state.py` | Owns retained raw display data, source clocks, scaling, and frame version state. |
| `raw_snapshot.py` | Builds bounded source snapshots from signal history for raw rendering. |
| `raw_render.py` | Converts visible samples into render-ready arrays while preserving gaps and trace identity. |
| `raw_render_worker.py` | Prepares raw frames outside the GUI thread and returns tagged results. |
| `render_contracts.py` | Defines the data exchanged between raw frame request, preparation, and presentation. |
| `render_policy.py` | Centralizes raw viewport, geometry, and sample-budget policy. |
| `vispy_raw.py` | Implements VisPy raw panels and trace geometry for live sweeps. |
| `vispy_metrics.py` | Converts metric history into points/segments and presents the metric plot in VisPy. |
| `vispy_plot_engine.py` | Shares GPU canvas, label gutters, and scale-ruler plumbing between plot views. |

### `physiolab/ui/`

| File | Role |
| --- | --- |
| `gui.py` | Composes the Designer layout, connects controls, manages workers/capture, and routes state to renderers. |
| `affect_widgets.py` | Paints the Central/Peripheral plane and EI view from prepared trajectory state. |
| `asr_training_dialog.py` | Binds the training capture dialog to progress and cancellation. |
| `asr_widgets.py` | Binds ASR toggle, Train, threshold, and status controls. |
| `branding.py` | Applies the BrainLab logo and viewer window icon. |
| `desktop_widgets.py` | Provides reusable channel selection, responsive Sources, and timed calibration widgets. |
| `flow_layout.py` | Installs wrapping and responsive layouts on Designer-defined hosts. |
| `metric_widgets.py` | Builds metric toggles and readout rows from the metric catalog. |
| `modality_labels.py` | Maps internal identifiers to user-facing labels such as SC. |
| `panel_arrangement.py` | Coordinates panel placement and layout controls. |
| `scale_rulers.py` | Chooses readable physical scale bars from display units and pixel density and paints the rulers. |
| `source_conversion_widgets.py` | Edits per-source gain, offset, and units without performing the signal conversion. |
| `ui_icons.py` | Looks up the shared SVG icons and applies action-dependent button text and icons. |

## Designer and media

| File or group | Role |
| --- | --- |
| `designer/PhysioViewerRT_ClinicalLayout.ui` | Main window and named controls for Sources, Raw Data, Metrics, and Affect. |
| `designer/AffectWorkspace.ui`, `designer/AffectControls.ui` | Affect panel hosts and controls that Python connects to the live plot widgets. |
| `designer/ASRTrainingCapture.ui`, `designer/ASRTrainingReport.ui` | Training progress and result layouts. |
| `designer/CalibrationInspection.ui` | Layout for inspecting the recorded EYC or BSL analysis. |
| `designer/README.md` | Designer editing conventions and runtime bindings. |
| `assets/brainlab-logo*.png`, `assets/physioviewer.*` | BrainLab branding and app icon variants. |
| `assets/icons/*.svg` | Reusable action and metric artwork, referenced by Designer and Python. |
| `docs/demos/` | Recorded viewer examples and screenshots; the README explains the demos. |
| `docs/demos/asr-matched/` | Matched ASR comparison image, measured JSON report, and reproduction instructions. |
| `docs/demos/asr-second-pc/` | Paired ASR on/off screenshots from the second PC. |

## Tests and tools

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m unittest discover -s tests_gui -q
```

Core tests exercise array/metadata contracts with deterministic signals. GUI
tests exercise widget bindings and state transitions; the LSL integration
tests use local outlets. Offscreen mode cannot validate native OpenGL drawing.

| Files under `tests/` | Coverage |
| --- | --- |
| `test_acquisition_contracts.py`, `test_ingress_buffer.py` | Chunk fields and bounded mailbox delivery. |
| `test_channel_selection.py`, `test_lsl_metadata.py`, `test_source_conversion.py` | Channel identity/order, metadata, and source-unit conversion. |
| `test_raw_timing.py`, `test_synthetic.py`, `test_settings.py` | Timestamp cleanup/clock behavior, seeded signal generation, and settings validation. |
| `test_processing_presets.py`, `test_notch_filters.py` | Preset validation and filter responses. |
| `test_peripheral_reduction.py`, `test_peripheral_runtime.py`, `test_sc_decomposition.py` | Denoising, runtime status, and canonical tonic SCL. |
| `test_eeg_asr.py`, `test_asr_training.py`, `test_asr_quality.py`, `test_asr_runtime.py` | ASR model and channel invariants, training selection, reporting, and runtime status. |
| `test_calibration.py`, `test_calibration_session.py` | EYC/BSL analysis, normalization, recording validation, and NPZ round trips. |
| `test_eeg_metrics.py`, `test_metric_calculators.py`, `test_metric_catalog.py` | Spectral metrics, calculator windows/results, and catalog metadata. |
| `test_metric_state.py`, `test_metric_display.py`, `test_emotion.py` | Histories, presentation transforms, and EI reference calculations. |
| `test_affect_state.py`, `test_affect_pipeline.py` | Pairing, baseline handling, and trajectory behavior. |
| `test_amplitude_display.py`, `test_raw_gain.py`, `test_shared_amplitude.py` | Physical amplitude mapping, gain, and consistency across traces. |
| `test_raw_display_state.py`, `test_raw_snapshot.py`, `test_raw_render.py` | Display state, window snapshots, and waveform preparation. |
| `test_render_contracts.py`, `test_render_policy.py` | Frame-request data and rendering limits. |
| `test_incremental_sweep.py`, `test_sweep.py`, `test_vispy_layer_budget.py` | Sweep boundaries, incremental updates, and bounded graphics resources. |
| `test_vispy_metrics.py`, `test_vispy_raw.py` | Renderer geometry and view calculations independent of native drawing. |

| Files under `tests_gui/` | Coverage |
| --- | --- |
| `test_gui_smoke.py` | Main-window construction, view controls, source changes, and analysis-tab availability. |
| `test_flow_layout.py`, `test_scale_rulers.py`, `test_text_resources.py`, `test_ui_consistency.py` | Responsive layouts, physical rulers, UI resource integrity, and consistency. |
| `test_asr_widgets.py`, `test_asr_report.py`, `test_asr_training_capture.py` | ASR controls, report, and capture workflow. |
| `test_asr_integration.py`, `test_live_feedback.py`, `test_peripheral_reduction.py` | Live correction, status feedback, and reducer switching. |
| `test_calibration_tasks.py`, `test_reference_replay.py` | Background calibration, reference compatibility, and Metrics startup with ASR off. |
| `test_affect_widgets.py`, `test_affect_integration.py` | Affect rendering and trajectories from local streamed observations. |
| `test_lsl_integration.py` | End-to-end LSL delivery, source selection, and raw rendering behavior. |
| `test_metric_reconfiguration.py`, `test_vispy_metrics_real.py`, `test_waveform_playback.py` | Plot view changes, native renderer behavior, and live playback. |

| Tool | Purpose |
| --- | --- |
| `tools/benchmarks/benchmark_hampel_playback.py` | Measures playback timing with peripheral Hampel reduction enabled. |
| `tools/benchmarks/benchmark_raw_transitions.py` | Measures raw view changes, with a cold-start option. |
| `tools/benchmarks/benchmark_three_stream_playback.py` | Measures concurrent EEG/PPG/SC playback and processing. |
| `tools/validation/asr_comparison.py` | Produces matched ASR off/on figures and measurements from the same input. |
| `tools/validation/record_live_test.py` | Records a live synthetic-stream GUI demonstration. |

## Design and evidence

- [ARCHITECTURE.md](ARCHITECTURE.md): boundaries, data flow, and extension instructions.
- [RENDERING.md](RENDERING.md): sweep preparation, plot ownership, and performance checks.
- [EEG_ASR.md](EEG_ASR.md): training, correction, baseline replay, and usage.
- [AFFECT_VISUALIZATION_DESIGN.md](AFFECT_VISUALIZATION_DESIGN.md): trajectory
  and EI interpretation and presentation.
- [PERIPHERAL_CLEANING_DESIGN.md](PERIPHERAL_CLEANING_DESIGN.md): proposed
  reference-free cleaning and quality checks.
- [PERIPHERAL_REDUCTION_EVIDENCE.md](PERIPHERAL_REDUCTION_EVIDENCE.md): implemented
  reduction methods, experimental evidence, and validation limits.
