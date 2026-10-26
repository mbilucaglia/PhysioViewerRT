# Peripheral reduction and display-clock coupling — 26 October 2026

## Reproduction and cause

The user observed better playback after disabling EEG and then disabling each
Hampel reducer, with continued stuttering after timebase changes. Matching
native trials compared the actual pre-Hampel source snapshot (022cec2), current
Off, current Hampel, and the independent-clock fix. All used the same installed
dependencies, 32-channel EEG acquisition with ASR and eight channels displayed,
PPG at 128 Hz and SC at 32 Hz. Sixty seconds of seeded synthetic plot history
preceded live local LSL delivery. The timebase changed 5 → 10 → 30 → 5 → 15 s.
Each trial ran 23 seconds, measuring after initial warmup.

The shared viewport was capped by the slowest fresh source. Hampel's three
future samples delay SC by 93.75 ms at 32 Hz, versus 23.4375 ms for PPG at 128 Hz.
Depending on chunk-arrival phase, the slowest-source cap repeatedly stopped the
other displays even though their own data was available. A deterministic
arrival-phase reproduction confirms the coupling independently of GUI load.
Hampel computation itself was around/below 1 ms per received block in these
trials; it did not explain the much longer draw gaps.

## Measured comparison

Native canvas draw interval, 95th percentile, milliseconds; smaller is better.
These are canvas events, not measured monitor presentation times or hard
real-time guarantees. One local run per case is not a hardware validation.

| Case | EEG | PPG | SC |
| --- | ---: | ---: | ---: |
| Pre-Hampel snapshot (022cec2), Off | 44.3 | 46.9 | 47.2 |
| Before fix, Off | 38.6 | 39.2 | 39.0 |
| Before fix, both Hampel | 67.0 | 67.5 | 67.6 |
| After fix, Off | 36.6 | 37.0 | 36.9 |
| After fix, both Hampel | 37.1 | 39.3 | 39.4 |

Full numeric transition and reducer timing summaries are in
[PERIPHERAL_PLAYBACK_TIMING.json](PERIPHERAL_PLAYBACK_TIMING.json).

## Fix and invariants

- Each source owns a presentation clock and viewport. The shared origin and
  original acquisition timestamps remain unchanged; a signal with lookahead or
  delayed delivery cannot stall another panel.
- Frame requests/results carry every source's own presentation head through
  asynchronous preparation to both renderers. Each cursor is still clamped to
  the actual samples drawn for that source. Panels can therefore have slightly
  different cursor phases, correctly reflecting different source availability.
- Between arrivals, clock corrections adjust speed instead of stopping at a
  slightly stale estimated target. A clock stops at the last acquired sample;
  samples are never extrapolated or fabricated.
- The presentation buffer remains 250 ms for every source. No denoiser, metric,
  ASR training, baseline, filtering, source conversion or sample value changes.
- Timebase changes preserve per-source heads and initial centering, resize the
  viewport and replay retained history as needed. Automatic centering still
  happens only at acquisition start; Center is explicit and Fit adjusts gain.

Core regressions cover delayed-neighbor isolation and timebase/reference
preservation. Native/fallback GUI checks cover source-head handoff and rendered
cursor alignment. Reproduce with tools/benchmark_timebase_switches.py using
--label trial-off --reducer off, then --label trial-hampel --reducer hampel.
PHYSIOLAB_BENCH_REPO can point at a separate source snapshot and
PHYSIOLAB_REPORT_ROOT can choose the output folder. No private recordings are
needed. Real hardware/PC confirmation remains open.
