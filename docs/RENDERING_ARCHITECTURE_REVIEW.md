# Rendering architecture review — 26 October 2026

Reviewed source: **3029828** (rendering implementation b675999). Scope: Raw Data,
Metrics, shared graphics resources, presentation state, preparation scheduling,
UI commands, and the acquisition/presentation boundary. This is a review, not a
production refactor. No denoising, calibration, processing or UI behavior changes
are included in this delivery. Evidence is in
[RENDERING_ARCHITECTURE_REVIEW.json](RENDERING_ARCHITECTURE_REVIEW.json).

## Verdict

**The renderer is partially modular, but not yet a stable platform for further
features.** More features should wait for a focused rendering stabilization and
ownership refactor. The recent fixes improved symptoms and timing, but retained
overlapping state and controller responsibilities. They do not establish that
the architecture is sufficiently isolated.

This is not a recommendation to discard Qt, VisPy, the numerical processing
code, or every existing module. There are useful foundations: bounded mailboxes,
pure preparation functions, retained sample history, partial GPU uploads,
shader-based gain, resource reuse, independent source clocks and versioned frame
responses. Keep these where they meet explicit contracts.

File count and passing-test count are not measures of modularity. MainWindow is
about 2,300 lines with 104 methods; more significantly, it directly assigns raw
display state in 22 places, computes centering, owns fallback curves, chooses
GPU history replay and accepts/rejects frames. The architecture document calls
it a composition layer, but it is also a rendering controller and lifecycle
manager. The main issue is responsibility ownership, not line count by itself.

## Verified findings

### R1 — High: rendering commands have no single lifecycle owner

Locations: [gui.py](../physiolab/gui.py), especially set_raw_renderer (1659),
set_raw_time_window (1762), render_frame (1894), draw (1962), apply_raw_frame (2023).

View validity depends on dirty, paused, autoscale_requests,
_raw_trace_selection_refresh, epoch, inflight_ticket and backend configuration.
Different commands set different subsets. There is no single command/reducer
that determines the next valid display state.

Native reproduction: switch from VisPy to pyqtgraph while paused with a valid
prepared PPG frame. The CPU backend has **zero curves** and stays blank even
though dirty is true. Then select a 10-second timebase: the control requests
10 seconds, but the paused plot still spans **5 seconds**. Center/Fit force
redraw through other special cases, which is why tests of those actions can pass
while backend/timebase changes fail.

Required boundary: the view controller owns command transitions and decides
whether to redraw a frozen sample snapshot. Backend adapters only execute the
resulting view. A paused view command must not require resuming acquisition or
plot motion to take effect.

### R2 — High: independent clocks do not mean independent frame scheduling

Locations: [raw_display_state.py](../physiolab/raw_display_state.py):163 and
[raw_render_worker.py](../physiolab/raw_render_worker.py):23–64.

There is one in-flight ticket and one request containing all sources. The
preparer processes those sources serially and emits only the whole result.
Injecting 150 ms of EEG preparation delayed a healthy PPG result by **153 ms**.
A new timebase increments epoch, but a replacement request cannot be submitted
until the obsolete in-flight request completes. The worker's latest-pending
replacement behavior is therefore largely defeated by the caller's global gate.

An unexpected exception has no explicit failure/completion contract. Selected
validation errors become None frames, conflating failure and no data; another
exception can end the worker without clearing the GUI's outstanding ticket.

Required boundary: source-scoped identities and completion, explicit cancelled /
stale / no-data / failed outcomes, bounded/coalesced jobs and fairness. A source
restart must invalidate that source's frames, while a global timebase change
has an explicit view generation. Choose worker parallelism from profiling;
adding threads alone is not the architectural fix.

### R3 — High: active and staging GPU resources are not isolated

Location: [vispy_raw.py](../physiolab/vispy_raw.py):268–346.

The documented contract says active channels remain visible until a replacement
is ready. In the cold channel-growth path, pending layers reuse active pool
objects and reconfigure/hide them before commit. A 4-to-8-channel reproduction
hid all eight active raw/processed visuals on the first staging step while
replacement_ready was still false. Pending resources aliased active resources.

Required boundary: separate active/staging buffer ownership and an atomic commit
or rollback. Reuse programs/resources without mutating the active generation
before the new generation is ready. Resource lifetime belongs to the backend.

### R4 — High: downsampling does not preserve diagnostic waveform extrema

Location: [raw_render.py](../physiolab/raw_render.py):67–79.

The reducer keeps every nth sample. At a supported 30-second sweep, a 256 Hz
signal with a single amplitude-100 pulse produced a displayed peak of **zero**:
15,360 input samples became 2,195 points and the pulse fell between retained
indices. This is independent of ASR/Hampel. It can make a raw artifact comparison
misleading even though the acquired data is intact.

Required boundary: define the visual reduction contract and use a gap-aware,
stable-bin extrema/envelope or suitable multiresolution representation. Budget
against plot width and preserve narrow peaks. Do not treat display reduction as
a denoiser, and do not claim reconstructed high-frequency detail.

### R5 — High: freshness and gap recovery are not specified as invariants

Locations: [raw_timing.py](../physiolab/raw_timing.py):58–84 and
[incremental_sweep.py](../physiolab/incremental_sweep.py):49–139, 258–272.

After a 20-second source gap, input ending at time 120.9 was available, but the
view head was 101.05. Two seconds later it was 104.05: **16.85 seconds behind**
the newly available data. Monotone slewing alone does not ensure a live view.

Separately, line-ring slots are not expired across long gaps. After samples at
20.0/20.1 arrived, **48 drawn slots** still belonged to a much older window.
Marker expiry exists, but line expiry does not. Previous-cycle persistence is
useful during normal sweeps; much older samples must not masquerade as current.

Required boundary: explicit discontinuity/recovery semantics, source freshness
metadata and a bound on presentation lag behind available data while following
live. Recover to a valid current window without fabricating lines across gaps.
Paused inspection is intentionally exempt from the live freshness budget.

### R6 — Medium: authoritative history and incremental frames are confused

Locations: [gui.py](../physiolab/gui.py):1712–1738,
[raw_snapshot.py](../physiolab/raw_snapshot.py):19–27.

Center operates on raw_display.frames, but a normal GPU frame is only a new
tail. In a five-second view it used **0.1016 seconds** of cached data. For a known
cosine with a full visible median of 10, Center selected **10.9327**. The GUI
command is relying on the incidental contents of a backend update packet.

Fit already requests a full window; Center does not. This is an example of a
missing semantic contract, not a reason for another ad-hoc redraw flag.

Required boundary: Center/Fit query the authoritative visible history through
the controller; an incremental geometry update is not a history-query result.
Center remains explicit and one-shot; Fit remains amplitude-only.

### R7 — Medium: startup references depend on packetization

Location: [raw_display_state.py](../physiolab/raw_display_state.py):88–103.

The same ten samples centered at **4.5** when delivered in one packet and at
**0.5** when delivered as two samples followed by eight. The first packet with
two or more samples determines the reference. A transport/processing batching
change therefore alters appearance without changing the signal.

Required boundary: define an initial physical-time/sample-count reference
interval, accumulate it independently of packet sizes, then latch it once.
This preserves the user's startup-only centering requirement.

### R8 — Medium: contracts and diagnostics are too weak for safe extension

Locations: [render_contracts.py](../physiolab/render_contracts.py),
[performance.py](../physiolab/performance.py), [gui.py](../physiolab/gui.py).

Request/result wrappers are named, but the prepared frame remains a six-position
tuple with object-typed references; dictionaries and NumPy arrays remain mutable
inside frozen dataclasses. The main window and backends infer coverage, scale,
freshness and replay requirements from several fields. Shared overview clock /
bounds coexist with per-source clocks / bounds and fallback paths. This makes
old versus new state easy to mix accidentally.

There is no common backend interface: pyqtgraph curve handling is in MainWindow,
whereas VisPy owns a separate renderer object. Metrics interpolation/smoothing
also runs in the GUI orchestration path. Some older geometry helpers are tested
but no longer used by the incremental renderer; passing those tests is not proof
of the runtime path.

Define named PreparedFrame and ViewSpec contracts with source/view generations,
coverage (full window versus tail), units, display transform and availability.
Make immutable ownership enforceable or explicit. Record per-source draw age,
queue age, rejected/cancelled frames and p50/p95/p99/max, rather than mean/worst
callback time alone. Benchmarks should use independent producers; the current
GUI-loop synthetic publisher partly couples input supply to rendering stalls.

## Performance and integration concerns requiring profiling

- Partial GPU uploads and retained shader programs are good foundations. However,
  there are two visuals/rings per displayed channel and warmup reserves all
  acquired channels. GPU linking and buffer replacement still run on the GUI
  thread; there is no enforced frame-time budget. Existing local traces include
  warmup callbacks above 100 ms. Profile batching channels into fewer visuals
  and separating programs from active/staging buffers before selecting a design.
- The full window is concatenated before decimation, so a 2,500-point output
  budget does not bound temporary memory or replay work. Retention is in seconds,
  not bytes. Establish limits for supported sample rates/channel counts/history.
- The processing/acquisition edge currently publishes display chunks after metric
  and tonic calculations. Without judging those algorithms, the display contract
  is still coupled to slow analysis. Keep waveform availability and metric
  availability explicit and independently consumable. Preserve required pairing
  of raw/cleaned samples; do not invent missing cleaned data.

These are profiling/design targets, not proof that every array allocation,
thread, or per-channel visual must be replaced. Native rendering remains on the
GUI thread; numerical work should remain outside it.

## Target ownership, not another collection of helper files

| Owner | Responsibility | Must not own |
| --- | --- | --- |
| Qt main window | Widgets, layout, forwarding commands, showing status | Clock policy, numerical centering, frame validity, GPU buffers |
| Plot controller / view state | Pause/live, source viewports, explicit Center/Fit, view generations | Physiological algorithms or backend internals |
| Signal history / reference model | Timestamped authoritative data, initial-reference policy, visible queries | Widget state or draw scheduling |
| Frame scheduler / pure preparation | Bounded source jobs, coalescing/cancellation, complete typed outcomes | Qt widgets or graphics contexts |
| Backend adapter (VisPy or pyqtgraph) | Rendering a prepared frame, resource ownership, transactional reconfiguration | Acquisition, processing, scientific normalization, arbitrary history queries |

These responsibilities can reuse/refine existing modules. Do not create a generic
plugin framework, parallel replacement state, or mixin hierarchy. One owner per
fact and a small shared backend protocol matter more than the number of files.
Affect's snapshot-driven presentation is a useful existing boundary; its plane
does not need to be forced through a raw-waveform backend.

## Refactoring order and feature gate

1. Convert these probes into behavioral regression tests and write down the
   rendering invariants, including full-window versus incremental payloads.
2. Extract the rendering controller and backend adapters from MainWindow. Move
   command transitions into one owner; remove duplicate state as calls migrate.
3. Make job identity, completion, cancellation and failure source-scoped; bound
   preparation work and preserve healthy-source progress under injected stalls.
4. Correct extrema preservation, discontinuity recovery, active/staging ownership,
   authoritative Center queries and packet-independent startup references.
5. Profile and optimize only against the resulting stable contracts. Consider
   batched visuals/multiresolution history where measurements justify them.

Before new features: require parity tests for both backends; pause/timebase/
channel/source/trace/Center/Fit transition matrices; delayed/failing-source
isolation; deterministic packetization; extrema/gap fidelity; and long runs with
bounded memory. Define a supported hardware/workload matrix. At 30 FPS the normal
frame budget is about 33 ms, but acceptance must measure tail latency, frame age
and configuration changes, not promise universal perfect scheduling.

Independent source clocks are a useful fix already present, but they do not
remove the scheduler, controller and resource-ownership problems above. Do not
declare the renderer stable solely because the existing 233/124 tests pass.

## Reproducing this review

Run tools/audit_rendering_boundaries.py for the pure scheduling/state/data probes
and tools/audit_paused_plot_commands.py for the isolated native UI probes.
They write JSON under .test-tmp/rendering-audit and do not touch recordings or
change production code. The native tool opens and closes its own test window.
**Exit success means the diagnostic ran, not that the architecture passed.**
The observed results are saved in the companion review JSON. No application
behavior fixes are bundled with this audit.
