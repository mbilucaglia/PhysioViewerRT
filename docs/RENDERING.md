# Rendering changes and validation

EEG uses one shared voltage scale across displayed channels. Unit metadata is
converted for display only (V/mV/µV/nV); data retained for processing and
calibration remain unchanged. Missing units are labeled a.u.
Channel-specific DC centering does not rescale amplitudes. A single amplitude
ruler and a single time ruler sit outside each raw canvas and track gain,
timebase, channel count, and widget size. Adding/removing displayed channels
does not change their voltage conversion. Display gain remains separate from
signal processing.

PPG and EDA fit raw and filtered display offsets separately, since a bandpass
output can have a different DC baseline. Their display range expands/recenters
when traces would escape the available range; the retained window is replayed
using existing GPU resources. This avoids permanently latching the tiny range
of a nearly flat startup chunk. Recorded samples and metric calculations are
unchanged. EEG retains its common physical voltage scale.

Each amplitude field has an Autoscale button beside its editable value, plus
separate minus/plus buttons. Autoscale is a one-shot fit: it prepares the entire
visible window, measures extrema of the enabled raw/filtered layers, and sets a
single gain with headroom. EEG channels share that gain, preserving amplitude
ratios. It does not switch on continuous automatic EEG scaling. Flat or hidden
data leave the current gain unchanged. The small spinbox arrow controls are
removed to avoid duplicating the separate minus/plus buttons.

Dense EEG channel labels are painted in the Qt gutter at their trace baselines.
Only labels that fit without overlap are shown at compact heights; expanding
the panel restores more labels. The gutter tooltip lists every channel.

All three raw sweep cursors use the same presentation clock and phase. The
clock is advanced once per GUI tick and applied to every visible raw panel,
independently of individual stream chunk delivery. A delayed source can leave
a gap before that shared cursor; its waveform keeps its original LSL timestamps.

Raw frames and the cursor are committed with the same sample-time cutoff. A
configurable 250 ms presentation buffer absorbs normal chunk delivery jitter;
it does not delay acquisition or processing. A source that has become stale
does not indefinitely freeze the remaining streams. Only the segment ending
at an arriving sample is overwritten; the next old segment retains its own
old endpoints until its replacement arrives. Full-history replay preserves
those endpoints even when both cycles occur within one preparation batch.
There is no anticipatory clearing of the segment after the cursor.

Signal processing and acquisition are independent of display reconfiguration.
Changing amplitude modifies shader uniforms. Changing timebase resets the sweep
ring and replays retained data into existing GPU storage and linked programs.
Raw channel layers are cached up to the largest displayed channel count in the
session; reducing then restoring channels reuses them. The selected/acquired
source channel count is now warmed one spare channel pair per GUI tick, including
VisPy's lazy shader linking in a tiny offscreen framebuffer. This starts in
Sources and continues as needed without altering the currently displayed frame.
A source reset clears samples but retains these resources. A fully warmed channel
selection can replay and commit in one preparation round, rather than waiting for
successive four-channel allocation rounds. Closing the renderer releases the pool.
If Raw Data is opened immediately before warmup finishes, first-use allocation
can still occur. Warmup moves the unavoidable initialization work earlier; it does
not remove its total cost or move OpenGL work to a background thread.

Metrics likewise retain their visuals across duration, normalization, smoothing,
and visibility changes. Timebase changes mark the display dirty immediately;
they do not wait for another physiological measurement. Tab entry schedules the
metric redraw on the display timer instead of performing it in the tab handler.

Channel labels and the two external rulers are painted by Qt. The normal
clean plot creates no VisPy text, font atlas, or hidden grid/axis visuals.
This removes GPU font initialization from tab entry; explicit debug axes remain
an optional plot-engine feature.

## Measurements on the development Windows workstation

These are local microbenchmarks, not cross-machine guarantees:

| Operation | Measured wall time |
| --- | ---: |
| First draw, 32 channel labels plus axes, original | 11,847 ms |
| Intermediate label workload, batched text/shared font atlas | 775 ms |
| Current Qt gutter, isolated 64-label scene first native render | 4.66 ms |
| Repeat label draw, original / batched | 28.1 / 6.6 ms |
| Full raw scene, first 32-channel preparation and native draw | 1,818 ms |
| Raw, 32 channels, change sweep 5 to 10 seconds | 105 ms |
| Raw, reduce 32 to 8 channels | 32 ms |
| Raw, restore 32 channels and 5-second sweep | 102 ms |
| Two metric series, first native draw | 145 ms |
| Metrics, 5 to 10 / 10 to 5 second sweeps | 24 / 14 ms |

The raw transition benchmark includes eight set-frame calls and a synchronous
canvas render using ten seconds of synthetic history. First use still has
driver/context and shader startup costs; newly introduced channels may
also incur compilation. Sustained performance and user-perceived latency need
verification with the intended device, graphics driver, and monitor setup.

Regression tests verify shader/visual identity and replay across timebase and
channel-count changes, metric visibility/transformation changes, and Qt
label grow/shrink/reset. The isolated label measurements are historical
comparisons, not an end-to-end live latency benchmark. The local LSL integration test exercises actual pylsl
outlets, GUI acquisition and native Windows OpenGL rendering.

The native integration check also computes EYC and BSL references from synthetic
recordings, then acquires fresh EEG/EDA/PPG data. It checks finite observations
for all five current metrics, cycles EEG through 8/16/32 displayed channels and
5/10/30-second sweeps, changes gain, expands/restores EEG, switches tabs, and
changes the Metrics timebase and normalization. It verifies retained shader
program identities, EEG voltage metadata conversion, ruler span, unchanged
receiver instances, and no mailbox sample drops during the raw transitions.
Late raw frames are rejected after a timebase change so the previous viewport
cannot overwrite the newly requested one.

## Reproduce first-use and channel-growth measurements

Run `tools/benchmark_raw_transitions.py --cold` and then the same command without
`--cold`, in separate processes on Windows. The latter simulates channel warmup
that the application normally spreads over Sources ticks. Both report upload,
synchronous GPU draw and preparation-round counts for 8 then 32 EEG channels.
These are isolated render measurements, not an end-to-end tab latency guarantee.
The native GUI suite checks retained samples/programs across warmup and reset,
and the real LSL integration continues to exercise acquisition and display.

Local comparison after the warmup change (same synthetic history and workstation):

| Transition | Cold upload + draw | Warmed upload + draw | Preparation rounds, cold / warm |
| --- | ---: | ---: | ---: |
| First 8-channel frame | 695.5 ms | 43.8 ms | 2 / 1 |
| Increase 8 to 32 channels | 1191.1 ms | 70.3 ms | 8 / 1 |

Total resource warmup was 1660.4 ms in this isolated run. In the app it is spread
across ticks while source controls remain usable. Driver and machine differences
apply; opening Raw Data before resources are ready can still incur cold costs.

Amplitude rulers read the selected source channel units for EDA and PPG as well
as EEG. Common metadata names are shortened (microsiemens → µS); missing units
use a.u. The vertical label gutter grows to fit both numeric value and unit,
including scientific notation, instead of clipping the leading number.

The acquisition-driven presentation clock now advances on every GUI tick,
including Sources and Metrics. Hidden tabs no longer leave the first Raw Data
snapshot at an old cutoff that excludes later-started or restarted streams.
Plot pause and manual navigation freeze only the viewport; the live clock keeps
tracking received data for resume. Receivers enable LSL proc_clocksync so the
library maps remote host timestamps into the viewer's local LSL clock domain.
No manual per-modality timestamp shifting is used.

Sweep slots use nearest nominal sample bins rather than flooring at bin edges.
Alternating tiny early/late timestamp jitter previously produced repeated and
skipped bin IDs, potentially leaving no consecutive drawable segments even with
valid input. Centered bins prevent that boundary effect; line endpoints keep the
measured LSL timestamps, real gaps remain disconnected, and only the arriving
sample's segment is replaced. Regression tests cover jitter at EEG, PPG and EDA
sample rates as well as tab dwell and receiver stop/restart.

Every raw panel now has Expand / Show all signals controls. Expansion changes
panel visibility and available plotting area only; receivers, metric calculations
and source selections continue unchanged.

Metrics uses external time and amplitude rulers in both VisPy and the fallback
renderer. Time is seconds. Amplitude shows baseline σ for z-score, σ (MAD) for
z-MAD, σ (IQR) for robust IQR, and norm. for fixed min–max baseline fractions.
Original mode resolves units from visible finite metric series and converted
source units; unlike units are explicitly labeled mixed units, with metric/unit
details in the tooltip. Rulers track current viewport size/range and display
settings without changing observations or allocating new GPU programs.


## Inactive tabs and GPU preparation

Only the active Raw Data, Metrics, or Affect page paints live data. Metric readout
labels also defer live updates while hidden, then catch up on entry. Acquisition,
source-time histories, SC decomposition, and metric calculations continue across
tabs so returning to a view uses current data and preserves the affect trails.
Raw GPU warm-up is separate from plotting: Sources and Raw Data may prepare one
spare channel pair per timer tick. It is suspended while Metrics or Affect is
active. Existing GPU resources remain allocated across tab changes; suppressing
hidden repainting does not discard the linked shaders or preallocated channels.
