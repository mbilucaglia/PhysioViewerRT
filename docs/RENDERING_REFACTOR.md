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
by `ViewerSettings.bounded_view_seconds`, including mouse zoom and programmatic
commands; the default maximum is the retained 300 seconds.

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
reuse, paused Metrics mouse zoom and bounded view durations. Obsolete geometry helper tests were removed
with their unused runtime helpers; the independent sparse-marker oracle remains
under tests to verify actual ring geometry.

## Audit disposition

| Finding | Implemented correction and evidence |
| --- | --- |
| R1 command ownership | Raw/metric controllers own commands and transitions; zero direct `MainWindow` assignments to raw display state; paused command regressions. |
| R2 scheduling | Per-source lanes, coalesced pending work, generation cancellation and explicit terminal outcomes; injected slow/failing/uncooperative preparations. |
| R3 resource isolation | Disjoint staging/active banks and atomic commit; active visibility/identity tests, native channel/timebase matrix. |
| R4 extrema | Paired min/max selection reaches actual ring geometry at original timestamps; impulse 100 remains 100. |
| R5 gaps/freshness | Old ring slots expire, large-gap clock rebase, no-data recovery, source expiry/restart; no interpolation across gaps. |
| R6 authoritative history | Explicit Center uses full visible history; paused history survives live pruning; native gain/center invariants. |
| R7 packetization | Fixed startup sample count, read-only once-latched references; identical samples in different packets yield identical references. |
| R8 contracts/diagnostics | Named immutable frames and lifecycle metadata; queue/preparation/frame/sample-age percentiles, actual draws and tip advances. Performance acceptance and long-run/device evidence remain open. |

## Validation and checkpoints

`8870b5c` establishes the ownership refactor. `19a909a` batches fragmented replay
uploads and is the revision used for the complete core/GUI suites and isolated
performance matrix. `403355a` corrects the fallback window caption found during
screenshot inspection; its targeted native suite and transition tool were rerun.

- Core: **230 tests passed in 17.928 s**.
- Full GUI: **136 tests in 145.769 s**, no failures, **three skips** requiring
  native OpenGL/camera/pixel verification. This suite uses Qt offscreen and does
  not establish native GPU performance.
- Final targeted native scheduler/command/upload regressions: **12 passed in 6.083 s**.
- Native transition tool: **30 backend/channel/timebase transitions passed**,
  plus trace combinations, Center/Fit invariants, five-minute windows, frozen
  history retention, gaps and source restart. Actual EEG layer/geometry checks
  verify 8 and 32 displayed channels. The run recorded 119 EEG, 125 PPG and
  123 SC canvas draws; window close took **122.841 ms**. Its settle timings include
  cold resource construction and are correctness diagnostics, not the matched
  live-playback performance comparison. The fallback caption matches every
  requested timebase, including an empty paused viewport.
- Repeat audit: PPG returned in **4.08 ms** despite 150 ms injected EEG work;
  Center median **10.0** instead of incremental-tail **10.9327**; no old-cycle
  gap lines; paused fallback has two curves and the requested 10-second range;
  gap recovery reaches the actual latest sample within two seconds.
- **21 alternating 300/5-second memory transitions** retained
  **203,788,800 bytes** of ring arrays after the first transition (first:
  210,470,400), and **136 graphics layers** throughout. Working set ranged from
  **812,810,240 to 975,654,912 bytes**; private commit from **2,386,632,704 to
  2,548,822,016 bytes**. The last five 300-second working sets span 3,584,000
  bytes. These are process-wide native measurements, not only NumPy estimates.
  A bounded resource pool and this short plateau do not prove an hours-long soak.

The first isolated matrix exposed a replay performance regression at 32
channels: EEG Off p99 draw interval was 148.2 ms versus baseline 73.4 ms. A new
regression reproduced **427 small GPU uploads per channel** for irregular extrema
slots. Checkpoint `19a909a` batches more than eight fragmented ranges into one
copied complete-geometry upload, preserving every vertex, gap and empty slot.
Contiguous live updates remain partial. This changes driver command batching,
not sample selection, buffer sizes, processing or the presentation delay. The
final isolated comparison below reruns every workload after that fix.

The matrix performance results and exact distributions are recorded separately
below and in `RENDERING_REFACTOR_RESULTS.json`.

## Isolated native performance comparison

Hardware: AMD Ryzen Threadripper PRO 5975WX (32 cores/64 logical processors),
NVIDIA GeForce GT 730, Windows 11 build 22631, Python 3.12.10. RAM capacity and
GPU driver version were not recorded. Both revisions ran on this same machine
with the same seeded independent producer, native Qt backend and ASR workload.

Each case is one 23-second trial; draw statistics cover the portion after the
first five seconds. Internal queue/preparation/backend timing includes startup.
The workload acquires 32 EEG channels at 256 Hz and checks actual display of
8 or 32 channels, PPG at 128 Hz and SC at 32 Hz. EEG-inactive cases contain both
peripherals. Timebases change through 5/10/30/5/15 seconds. No other test suites
ran during this comparison. These are descriptive percentiles from short runs,
not repeated-trial confidence intervals or physical screen-presentation times.

| Case | EEG draw p95 / p99 ms | PPG draw p95 / p99 ms | SC draw p95 / p99 ms | EEG sample age p95 / p99 ms |
| --- | --- | --- | --- | --- |
| baseline-32-both | 41.6 / 65.7 | 44.8 / 71.5 | 44.7 / 71.3 | 293.6 / 304.2 |
| baseline-32-off | 40.5 / 66.7 | 40.8 / 72.8 | 41.8 / 71.8 | 292.1 / 306.1 |
| baseline-8-both | 36.2 / 45.0 | 39.2 / 48.5 | 39.1 / 47.3 | 278.5 / 285.7 |
| baseline-8-off | 36.8 / 46.3 | 37.7 / 52.7 | 37.4 / 50.8 | 283.3 / 289.5 |
| refactor-32-both | 46.9 / 71.6 | 46.6 / 74.5 | 46.2 / 71.4 | 290.9 / 300.2 |
| refactor-32-eda | 45.4 / 75.3 | 45.7 / 76.7 | 44.5 / 74.7 | 292.6 / 310.2 |
| refactor-32-off | 44.0 / 79.0 | 43.6 / 79.7 | 43.0 / 80.2 | 293.6 / 319.9 |
| refactor-32-ppg | 51.2 / 80.5 | 48.0 / 82.0 | 50.4 / 83.2 | 293.5 / 308.9 |
| refactor-8-both | 37.4 / 54.1 | 39.1 / 55.0 | 39.6 / 52.6 | 275.9 / 282.6 |
| refactor-8-eda | 37.3 / 53.0 | 38.4 / 51.2 | 39.2 / 52.2 | 282.8 / 324.0 |
| refactor-8-off | 36.6 / 54.0 | 38.2 / 49.9 | 37.8 / 57.6 | 275.4 / 284.7 |
| refactor-8-ppg | 37.5 / 48.9 | 38.7 / 51.8 | 39.0 / 52.5 | 273.7 / 279.9 |
| refactor-no-eeg-both | — / — | 36.5 / 41.1 | 36.1 / 39.5 | — / — |
| refactor-no-eeg-eda | — / — | 35.9 / 38.1 | 35.7 / 39.6 | — / — |
| refactor-no-eeg-off | — / — | 35.6 / 38.6 | 35.8 / 37.5 | — / — |
| refactor-no-eeg-ppg | — / — | 36.1 / 39.5 | 36.1 / 39.3 | — / — |

The 32-channel Off replay fix reduced p99 draw intervals from 148.2 ms before
batching to 79.0 ms after batching; p95 drawn-sample age fell from 428.4 to
293.6 ms. The final matched baseline is still faster in the tails: 66.7 ms p99
Off and 65.7 ms with both Hampel, versus 79.0 and 71.6 ms respectively. This
refactor therefore does **not** claim a general playback-speed improvement.
The baseline loses narrow peaks and mutates active staging resources; retaining
the corrected behavior while reducing the remaining transition/draw cost is
the next performance task. Do not increase the presentation buffer to mask it.

For the final 32-channel/both-Hampel case, EEG produced **520 draws with 519
data-tip advances**. Advancing-tip intervals were **46.948 / 71.585 ms p95/p99**;
drawn EEG sample age **290.891 / 300.197 ms**; prepared-frame age at draw
**34.946 / 51.033 ms**; request age at draw **35.637 / 52.509 ms**; preparation
queue age **0.977 / 7.099 ms** (queue timings include startup). PPG sample age was
**319.465 / 332.994 ms**, SC **450.011 / 463.394 ms**, retaining their actual
Hampel lookahead. EEG's first draws at new timebases took **65.084, 101.766,
85.094 and 110.001 ms**. At the 30-second switch, PPG and SC completed their new
view draws in **22.116 and 20.189 ms**, independently of EEG. All cursor-lead
measurements were zero; that observation is accompanied by actual draw/tip
measurements and is not itself evidence of smooth playback. Full per-source
p50/p95/p99/max values and counts are retained in the JSON.

## Next session and remaining gate

1. Continue on `refactor/rendering-ownership`. On this machine use the retained
   `rendering-refactor` worktree; the original Desktop checkout stays on `main`.
   On another machine, fetch and check out the remote refactor branch before
   running `main.py`. There are no new dependency requirements.
2. Confirm playback with real EEG/PPG/SC devices on the intended PC. Repeat the
   same channel counts, ASR, reducer combinations, transitions and paused/live
   controls. Record draw and advancing-tip intervals, sample/frame/queue ages,
   source disconnect/restart behavior and Stop responsiveness.
3. Repeat longer trials and an hours-long memory soak. The 21-transition check
   establishes fixed retained arrays/layer counts and a short process-memory
   plateau, not indefinite allocator/driver stability.
4. Profile remaining 32-channel GUI/backend transition costs and agree actual
   p95/p99 acceptance budgets against the intended workload. Keep the existing
   250 ms buffer, gap/peak invariants and disjoint resource generations.
5. Keep product/denoiser features frozen until these checks pass. The verified
   R1–R8 correctness/ownership fixes are implemented and regression-tested;
   real-device smoothness and performance acceptance remain outstanding.

Native screenshots: [VisPy 32 channels](demos/rendering-refactor/vispy-32.png),
[pyqtgraph 32 channels](demos/rendering-refactor/pyqtgraph-32.png),
[VisPy 8 channels](demos/rendering-refactor/vispy-8.png),
[pyqtgraph 8 channels](demos/rendering-refactor/pyqtgraph-8.png).
