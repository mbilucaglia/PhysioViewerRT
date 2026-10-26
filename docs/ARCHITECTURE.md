# Application boundaries and extension guide

PhysioViewerRT separates acquisition, signal processing, and presentation. Display
pause, gain, smoothing, interpolation, and sweep duration are presentation choices;
they must not change the samples passed to physiological processing.

## Current modules

| Responsibility | Modules | Contract |
| --- | --- | --- |
| LSL discovery and stream reception | `lsl_tasks.py`, `worker.py` | Blocking LSL work runs outside the GUI thread. |
| Bounded delivery | `acquisition_contracts.py`, `ingress.py` | Named acquisition chunks preserve timestamps and metric observation time; a locked mailbox batches delivery for GUI draining. |
| Channel identity and timestamps | `channel_selection.py`, `raw_timing.py` | Preserve selected labels and source timestamps together with samples. |
| Processing cadence and retained windows | `processing.py`, `signal_buffer.py` | Stateful filtering and metric cadence own bounded sample histories sized for declared metric windows. |
| Source conversion | `source_conversion.py`, `source_conversion_widgets.py` | Immutable gain/offset/unit configuration is applied once by the receiver before processing. The editor remembers each source separately within the session. |
| Filter construction | `processing_filters.py` | Presets, validation and SciPy SOS construction have one owner. |
| Metric calculations | `physiological_metrics.py` | Pure modality calculators declare their required history; no widgets or acquisition threads. |
| Calibration capture and analysis | `calibration_session.py`, `calibration.py` | Capture owns metadata/sample copies, boundaries and completeness checks; analysis and file serialization remain separate. |
| Metric session state | `metric_state.py`, `emotion.py` | Own qualified histories, latest observations, derived EI, reset and normalization without Qt. |
| Raw display session | `raw_display_state.py` | Own retained samples, shared clock, scale references, autoscale requests and frame ticket/version lifecycle without Qt. |
| Raw display preparation | `raw_snapshot.py`, `raw_render.py`, `raw_render_worker.py`, `incremental_sweep.py` | Prepare bounded render payloads; preserve gaps and sweep boundaries. |
| Plot contracts and GPU presentation | `render_contracts.py`, `vispy_raw.py`, `vispy_metrics.py`, `vispy_plot_engine.py` | VisPy owns graphics; presentation helpers remain testable without OpenGL. |
| Metric display transforms | `metric_display.py` | SciPy interpolation and causal display smoothing preserve original observations. |
| Metric presentation metadata and controls | `metric_catalog.py`, `metric_widgets.py` | Qualified `(modality, name)` keys identify metrics across histories and controls. |
| Shared policy | `settings.py`, `render_policy.py` | Centralize viewer timing/history/gain limits and raw geometry/sample budgets. Rulers, labels, autoscale and both renderers use the same geometry. |
| Desktop widgets | `desktop_widgets.py`, `metric_widgets.py`, `scale_rulers.py` | Reusable Qt views do not own acquisition or processing session state. |
| Application composition | `gui.py` | Connect Designer controls, asynchronous stream lifecycles, session models, calibration dialogs and renderers. |
| Diagnostics and test sources | `performance.py`, `synthetic.py` | Optional timing summaries and reproducible demonstration inputs. |

The Designer project under `designer/` controls widget layout and appearance.
Static action icons are shared SVG assets referenced directly by the `.ui` and
by `ui_icons.py` for running/paused states. EEG ASR is a minimal Designer-owned
Sources control. Train captures fresh EEG independently of BSL/EYC; threshold
edits reuse that training sample. Baseline analysis and live metrics both follow
filtering and optional channel-preserving ASR. Separate background EEG reference
replay tracks processing-mode and IAF changes without retraining the model. The former standalone ASR tab and diagnostic preview have been removed.
Qt handles application widgets, pylsl handles LSL transport, VisPy handles GPU
rendering, and NumPy/SciPy handle numerical operations. Reuse those libraries
before adding custom infrastructure.

## Add an EEG, EDA, or PPG metric

1. Add a `MetricDefinition` to `DEFAULT_METRICS` in `metric_catalog.py`, supplying
   its modality, unique name within that modality, description and unit.
2. Return that name and value from the modality calculator in
   `physiological_metrics.py`. Its `MetricCalculator.window_seconds` declares
   required history; `Processor` allocates at least that amount. Calculators
   retain the current common measurement cadence; display frames never compute
   physiological observations. For metrics with different windows in one
   modality, declare the largest required window and slice inside the calculator.
3. Add algorithm tests with known expected values, missing data and startup
   behavior. Processing algorithms and preprocessing changes are deferred in
   this development pass.
4. Verify the generated selector, readout, history and plot in the application.
   The catalog supports repeated names across modalities. Colors extend beyond
   the original five entries using deterministic HSV colors.

IAF remains an EEG calibration parameter rather than a plotted catalog metric.
Adding a new modality still requires acquisition, processing and lifecycle
integration; adding a catalog entry alone does not implement a new signal type.
Metric units are descriptive metadata, not automatic conversion instructions.
Mixed physical units require a deliberate normalization/display policy.

## Change viewer policy

Construct a `ViewerSettings` instance and pass it to the application composition
entry point instead of duplicating constants. Counts must be positive integers,
durations must be finite and positive, the default view must fit retained history,
and multiplicative gain steps must exceed one. Immutable settings prevent
partially updated policy while a session is running. Runtime UI choices remain
separate from those construction defaults.

## State and dependency rules

The GUI owns widgets and running Qt workers. `RawDisplayState` owns raw session
state; `MetricState` owns observations; `CalibrationSession` owns a recording.
Do not add a second copy of these histories or timing fields to a widget.
Pure models import neither Qt nor VisPy. `RawFrameRequest`, `RawSourceRequest`
and `RawFrameResult` define the preparation boundary; acquisition uses
`AcquisitionChunk`. Renderers expose configuration/replay status publicly so
application code does not inspect GPU implementation fields.

A view change increments the raw frame version. Only a matching in-flight ticket
can free its worker slot, and only a matching version may paint. A returned
presentation cutoff commits waveforms and every visible raw cursor together.
A stale response must never replace a newly requested timebase or channel layout.

The main window remains the composition and interaction layer. Stream controls,
modal calibration dialogs, and plot presentation belong there; signal formulas,
retention, sample capture validation and normalization do not. Avoid mixins,
forwarding layers without ownership, and creating a generic plugin framework
before a concrete extension needs it.

Algorithm constants remain beside their numerical owner with names and units.
Shared viewer defaults belong in `settings.py`; shared plot geometry and budgets
belong in `render_policy.py`. Styling/layout lives in the Designer project or the
owning reusable widget. The existing processing import surface remains available
for callers, while implementation lives in the focused modules above.

New modalities still need explicit stream lifecycle and processing integration.
The calculator registry is configured before processors are created; changing a
calculator's window during a session requires recreating that processor. It does
not promise dynamic plugin loading or independent per-metric schedules.

## Validation

Run the pure Python suite with `.venv/Scripts/python.exe -m unittest discover -s
tests`. `test_settings.py` covers policy invariants and `test_metric_catalog.py`
covers qualified keys, catalog immutability, and colors beyond five metrics.
`test_raw_display_state.py`, `test_metric_state.py` and
`test_calibration_session.py` verify session ownership/lifecycle independently of
Qt. `test_metric_calculators.py` checks history sizing for future metrics.
The separate `tests_gui` suite exercises Qt and real local LSL outlets. Actual
OpenGL driver behavior, physical devices, and sustained-session performance
require checks on the intended workstation.

## Sensor gain, offset and unit conversion

Sources exposes `output = gain × input + offset` for each modality. The same
conversion applies to every selected channel of that receiver. Identity defaults
preserve source samples and metadata. A blank output unit retains source units;
missing metadata displays a.u. Unit text alone does not calculate a conversion:
use the calibration coefficients specified for the sensor. µV to µS, for example,
is a sensor transfer calibration rather than a universal unit conversion.

Conversion controls are locked while that receiver runs. Stop it, change the
coefficients, then start it again. Selected-source settings are remembered during
the current app session. The receiver converts cleaned samples before Processor,
so raw display history, filtered signals, physiological metrics and calibration
capture all consume the same converted values. Source LSL timestamps are retained.

Calibration files store converted arrays together with gain, offset, output unit,
original channel units and resulting units. Loading a saved file analyzes those
arrays directly; it does not apply the conversion again. Older calibration files
without these optional metadata fields remain readable.

## Live source/channel changes and panel focus

Changing Stream or Channels for an active modality schedules an asynchronous
receiver replacement. `ViewerSettings.source_change_debounce_ms` coalesces rapid
selections; metadata completion and receiver shutdown both retry the same pending
intent using the latest choices. Old raw/metric histories are cleared immediately
and old receiver mailboxes are discarded while replacement is pending. Other
modalities keep their receivers. Explicit Stop cancels an automatic reconnect;
changes to an already stopped modality do not start acquisition. Empty channel
selections wait for a valid selection. Calibration defers replacement until the
capture finishes, so one recording never mixes channel/source configurations.

`set_raw_focus` implements expansion for EEG, PPG and EDA. Each panel's Expand
button uses the same policy, preserves the original splitter sizes, and restores
all panels through Show all signals. Hidden signals continue acquisition.

The implemented Affect tab is described in [Affect visualization](AFFECT_VISUALIZATION_DESIGN.md).
`AffectState` owns source-time pairing, baseline normalization and bounded trails;
`AffectView` presents persistent VisPy geometry and the original signed EI. The
cvxEDA adapter runs on the receiver thread and produces the canonical tonic `SCL`
metric with source-window provenance. Live and BSL processing share that adapter.
`CalibrationAnalysisTask` performs baseline analysis away from the GUI thread.
Peripheral coordinates require compatible tonic pipeline and input metadata;
EI uses the same decomposed SCL and matching baseline statistics. No median SCL
fallback is exposed in Metrics, Affect, or calibration.


## Adaptive desktop layouts

Designer owns toolbar groups and styling in PhysioViewerRT_ClinicalLayout.ui
and AffectControls.ui. A widget marked with the wrapControls property has its
preview grid replaced at startup by flow_layout.FlowLayout. This preserves each
label/control group, signal connection and named widget while allowing groups to
wrap using Qt size hints. Sources uses its existing one/two-column controller;
Affect cards adapt to viewport width. Scroll areas keep controls reachable when
window height is limited. New controls should join an appropriate Designer group
rather than adding a new permanent row or hard-coded screen coordinates.


AffectWorkspace.ui defines Affect cards and splitter placement. Metrics panes
and default metric-card Move controls live in PhysioViewerRT_ClinicalLayout.ui.
The shared panel_arrangement.PanelArrangement attaches swap/reset menus to existing
splitter widgets or wrapping cards; it reorders presentation objects without
replacing plots, histories or processing state. Arrangement choices are local to
the current session. Source availability continues to control Affect visibility.


## Shared action conventions

Keep static control layout and default icons in Qt Designer. Dynamic expansion
and view-pause states use ui_icons.set_panel_expanded and set_view_paused. Pane
headers use title, Move, Expand/Restore in that order. Expand uses expand.svg;
Restore uses collapse.svg; view Play/Pause uses play.svg/pause.svg. Source
Play/Stop uses the white variants on filled acquisition buttons. Recording,
loading and clearing use record.svg, open.svg and clear.svg respectively.
Zoom + increases detail; zoom − shows a wider range. The autoscale symbol means
fit the visible data. Tooltips explain whether an action affects the display or
acquisition. Icon size is 16 px; pane headings use a shared 11 pt hierarchy.

Metrics vertical zoom/Fit changes presentation bounds only. The manual range is
held through new observations and renderer changes until Auto range is enabled.
In auto mode the GPU range expands for arriving values; Fit tightens it to the
visible finite observations. CPU and GPU rendering share the same UI controls.
