# Rendering implementation handoff — 27 October 2026

This implements the ownership refactor following audit commit `bcd8d35` on
`refactor/rendering-ownership`. The original audit and its JSON remain historical
evidence. The implementation preserves the 250 ms presentation buffer and all
ASR, Hampel, wavelet, filter, metric and calibration mathematics. New features
remain frozen pending the performance/device work below.

## Ownership and contracts

| Owner | Responsibility |
| --- | --- |
| `SignalHistory` | Authoritative paired raw/cleaned samples with original timestamps; source generations; acquisition-start reference. |
| `RawDisplayState` | View generation, one clock/viewport per source, frozen pause snapshot, command requests and accepted frame cache. |
| `PlotController` | Commands, snapshot coverage, source validity, retries, backend selection, Center and gain-only Fit. |
| `RawRenderWorker` | Source-specific pending work, cancellation, execution and terminal outcomes. |
| `raw_render` | Pure numerical selection, transforms and peak/gap preservation. |
| Raw backend adapters | Their own curves, GPU buffers, sweep rings, staging and drawing. |
| `MetricPlotController` | Sparse metric view state, frozen observations and commands, with the existing numerical preparation and backend drawing. |
| `MainWindow` | Widgets, layout, acquisition composition and command forwarding. |

`PreparedFrame` names times, paired values, centers/scales, channel names and the
edge-ending connectivity mask. Arrays are read-only. `RawSourceRequest` names
source generation, full/incremental coverage, unit, availability time and command;
`RawFrameRequest` carries the view generation and ticket. A result has explicit
ready/no-data/failed/cancelled outcomes and queue/start/ready timing. Lifecycle
metadata never comes from tuple positions. Six-field iteration remains only for
older numerical diagnostic callers; the runtime controller uses named fields.

The small raw backend interface is `present`, `reset`, `invalidate_history`,
`history_needs_replay`, `close`. pyqtgraph consumes full windows. VisPy consumes
incremental tails after a full replay. Both preserve actual sample pairing and
gap edges. Metric adapters use the existing sparse-series interface; raw sample
execution lanes are unnecessary for their low-rate observation histories.

## Lifecycle and behavior

Each source has two preparation lanes and one coalesced pending snapshot. An
obsolete call can finish while its replacement runs; unrelated sources complete
independently. Numerical preparation checks cancellation between operations.
Python cannot forcibly interrupt an arbitrary native numerical call: if both
lanes are uncooperative, that source waits for a lane, without blocking peers.
Stop cancels and joins for at most 100 ms; workers never own graphics/widgets.

Failures release the source slot and retry up to three times, including paused
commands. A new command or source reset clears that limit. Empty coverage is an
availability condition and never consumes the failure budget. Stale completions
cannot release a newer slot or update its graphics. Source reset only changes
that source's generation.

VisPy's active and staging resources are disjoint. Active traces remain visible
until the replacement is populated and committed. Spare resources are reused;
reset hides retired banks, which are reconfigured only before reuse. Native live
warmup links one spare channel pair per tick, up to two banks of displayed
channels. It does not change history or presentation delay.

Startup references use the first `max(2, ceil(fs * 0.25))` actual samples and latch
once per acquisition. They are independent of packet sizes, displayed channels
and later history pruning. Explicit Center reads authoritative visible history;
Fit only changes gain. Drift, trace toggles, timebase and displayed-channel
changes never implicitly recenter. Paused commands replay the frozen snapshot
even after the live history has pruned those samples.

Visual reduction selects original endpoints and the union of raw/cleaned extrema
per channel in origin-anchored time bins. The point budget is soft when preserving
topology/extrema requires more points. No samples are interpolated or invented.
The ring uses original sample positions and explicit gap edges; it expires old
geometry on gaps. The source clock rebases after a large discontinuity instead
of slewing through missing seconds; normal playback keeps the 250 ms buffer.

## Bounds and limitations

History is limited by source time and 64 MiB of arrays per source, in immutable
blocks of at most 512 samples. Pause can retain one extra bounded history.
Outstanding requests retain bounded snapshots; six execution lanes plus one
pending request per source bound their number. Diagnostic timing retains at most
20,000 samples per timing key. Rings use nominal source rate to preserve narrow
peaks and can be large at five-minute, 32-channel settings. Backend pools retain
at most two banks at the largest configured channel count; duration is bounded
by the supported UI/settings range.

Five-minute transition measurements establish behavior over that sequence, not
a long-run allocator/driver memory plateau. Real-device smoothness is not proven
by synthetic LSL success. Canvas draw callbacks measure application rendering,
not physical monitor scanout. See the results JSON and final validation section
for hardware, exact counts, distributions and outstanding work.

## Reproduction

Use the repository requirements in a Python 3.12 environment with native Qt,
VisPy and OpenGL. From the checkout:

```powershell
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s tests_gui -v
python -B tools/audit_rendering_boundaries.py
python -B tools/audit_paused_plot_commands.py
python -B tools/validate_rendering_native.py
python -B tools/benchmark_rendering_matrix.py --baseline <checkout-at-bcd8d35>
```

The matrix launches a separate producer process per case and closes only its own
workers/window/producer. It trains ASR, checks processed EEG sample counts and
actual displayed channel counts, then measures draw events and advancing data
tips under repeated 5/10/30/5/15-second changes. It includes EEG inactive and
peripheral reduction Off, PPG only, SC only and both. The original comparison
checkout is read-only and never imports personal calibration files.

Regression tests were established before fixes, including follow-up failures
found by independent review: short-packet gap recovery, absent-source buffer
reuse and paused Metrics mouse zoom. Obsolete geometry helper tests were removed
with their unused runtime helpers; the independent sparse-marker oracle remains
under tests to verify actual ring geometry.
