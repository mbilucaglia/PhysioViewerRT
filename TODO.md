# PhysioViewerRT handoff — 23 October 2026

## Completed in this delivery

- Modern Qt Sources, Raw Data, Metrics and Affect layouts; shared action icons
  and BrainLab assets live in the repository and Designer UI.
- Shared raw amplitude/time rulers, per-signal expansion/autoscale controls,
  multichannel EEG display and asynchronous source/channel reconfiguration.
- Central AWI/BAR and Peripheral HR/SCL trajectories, plus original signed EI.
  Peripheral response and EI require live PPG and SC; both analysis tabs remain
  visible but disabled until EYC and BSL are available.
- One canonical SCL from cvxEDA decomposition, shared by Metrics, EI and baseline
  statistics; no extra 20-second startup or edge exclusion.
- ASR is in Sources under EEG filters: enable, Train, threshold and status.
  Train records fresh EEG for 45 seconds independently of EYC/BSL. All selected
  channels, order, labels and sample count are kept. No channel deletion mode.
- Processing order: raw input → source conversion/device-specific filtering →
  optional EEG ASR → cleaned signals → baseline analysis and live metrics.
- EYC PSD and EEG BSL statistics use this same chain. Mode/threshold/IAF changes
  replay retained BSL EEG for matching reference statistics without training ASR
  from BSL. Loading/clearing baselines does not discard the trained ASR model.
- Metrics and Affect share the same baseline compatibility policy. Baseline
  references are not silently mixed across different preprocessing settings.

## Continue on another Windows PC

1. Clone `https://github.com/mbilucaglia/PhysioViewerRT.git`, branch `main`, or
   run `git pull --ff-only` in the existing checkout.
2. Install 64-bit Python 3.11 or 3.12, then run `setup_windows.cmd`. It installs
   the viewer plus `requirements-affect.txt` and `requirements-asr.txt`.
   Keep the pinned meegkit revision; released 0.1.9 has known fitting problems.
3. Run `simulate_windows.cmd` or the hardware LSL publishers, then
   `start_windows.cmd`. Select sources/channels/units and press Play.
4. For EEG ASR: Train first, then record EYC and BSL. ASR models currently live
   in memory, so train again after restarting the application/on the other PC.
5. For repeatable ASR training tests, use clean simulator output:
   `.venv\Scripts\python.exe simulate.py --artifacts none`.
6. Local `.npz` baseline recordings, `.venv`, `.test-tmp` screenshots/logs and
   executables are not part of this viewer commit. Transfer recordings separately
   if needed, or record fresh baselines on the new setup. Saved raw recordings
   are reanalyzed with the current preprocessing chain when loaded.

The separate `Shimmer-LSL` work shares this local checkout but is outside this
viewer delivery. Its untracked package/build files have been left untouched;
use its own repository/chat for continuing that work.

## Validation

- Viewer core suite: 200 passed. Offscreen GUI/LSL suite: 82 tests, 80 passed
  and two native-OpenGL checks skipped. Focused native Windows checks: 14 passed.
- A native Train-button test recorded a real 45-second local LSL EEG stream,
  trained/enabled ASR without EYC/BSL, and preserved all four channels.
- A 32-channel live LSL test verifies ASR toggling, matching AWI/BAR references,
  continuous raw samples and downstream metrics. The simulated publisher runs
  independently of the GUI, as hardware does.
- Offscreen GUI tests intentionally skip two native OpenGL checks and may emit
  unsupported-OpenGL warnings. Synthetic validation is not physical-device
  validation.

Run checks from the repository root:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m unittest discover -s tests_gui -q
$env:QT_QPA_PLATFORM = 'windows'
.venv\Scripts\python.exe -m unittest tests_gui.test_asr_integration -v
```

## Second-PC ASR follow-up — 23 October 2026

- [x] Installed Python 3.12 and updated all requirements on the second Windows PC.
      The missing ASR backend now imports successfully; pip check passes.
      This is a local environment repair, not a change to the pinned backend.
- [x] Clarified the existing checkbox as **Apply ASR**, with a tooltip and an
      explicit ASR-off status. Turning it off retains the selected EEG filters.
- [x] Passed nine ASR processing tests and nine ASR GUI/integration tests.
- [x] Launched the native desktop app, trained ASR for 45 seconds using clean
      synthetic 32-channel EEG at 256 Hz, and verified enabling/disabling ASR.
      Observed live VisPy/OpenGL EEG rendering on this PC.
- [x] Restarted the simulator with strong artifacts and captured native screenshots.
      Red is raw EEG; black includes filters and, when enabled, ASR.
      The on/off images show different time intervals and do not quantify ASR
      attenuation. See [ASR on](docs/demos/asr-second-pc/asr-on.jpg),
      [ASR off](docs/demos/asr-second-pc/asr-off.jpg),
      [artifacts with ASR](docs/demos/asr-second-pc/strong-artifacts-asr-on.jpg),
      and [artifacts without ASR](docs/demos/asr-second-pc/strong-artifacts-asr-off.jpg).
- [x] Replay the same artifact-contaminated recording with ASR on/off and compare
      matched time windows at identical gain; quantify attenuation and preservation.
      Completed for a controlled four-channel synthetic case on 26 October 2026;
      see tools/asr_comparison.py and docs/demos/asr-matched/README.md.
- [ ] Extend matched replay to multiple seeds, artifact types and real recordings.
- [ ] Complete high-DPI and full Train → EYC → BSL → Metrics/Affect validation
      on this PC. The live check above covered EEG acquisition, ASR and Raw Data.

The viewer and synthetic publishers were stopped at the end of the session.
Restart the app and train a fresh ASR model next time; models remain in memory only.

## Prioritized next tasks

- [ ] Validate with real EEG, SC and PPG hardware: units/gain/offset, clean ASR
      training, motion artifacts, stream gaps/reconnection and long sessions.
      Confirm channel order and corrected-signal amplitudes against recordings.
- [ ] Retain EYC raw recording in session state and automatically recompute
      IAF when ASR/filter settings change. Currently record/reload EYC after
      such changes; automatic BSL reference replay already exists.
- [ ] Add optional ASR model save/load using the existing JSON-safe coefficient,
      source-configuration and integrity metadata. Reject incompatible channels,
      units, filters and backend versions; preserve every channel.
- [ ] Implement reference-free PPG/SC quality assessment and cleaning only after
      agreeing the algorithm/parameters. Research and proposed boundaries are in
      `docs/PERIPHERAL_CLEANING_DESIGN.md`; these additions are not implemented.
- [ ] Profile cvxEDA latency and metric cadence on target hardware with multiple
      streams. Keep canonical decomposed SCL and the current startup behavior.
- [ ] Extend metric definitions/configuration through `metric_catalog.py` and
      the documented processing/state boundaries; avoid modality-specific UI
      duplication. See `docs/ARCHITECTURE.md`.
- [ ] Add reproducible recordings for regression checks of ASR attenuation,
      clean-signal preservation, baseline normalization and affect trajectories.
- [ ] Verify high-DPI layouts and native GPU rendering on the second PC, then
      capture an updated demo of Train → EYC → BSL → Metrics/Affect.

## Brainstorming — 24 October 2026 (ideas only)

These are exploratory ideas, not agreed requirements or scheduled implementation.
The measures, statistical assumptions and presentation still need discussion.

- **ASR training-quality / effectiveness popup.** After training, show a summary
  of the quality of the training EEG and how suitable the fitted model may be
  for subsequent ASR processing. Explore what useful indicators could be shown
  (for example usable clean duration, residual contamination or model stability).
  Training-data quality is the intended reading of "WiFi of the data"; confirm
  that wording with the author. Keep training quality distinct from demonstrated
  future artifact-removal performance, which needs separate validation.
- **Baseline-relative uncertainty in Metrics or Affect.** Alongside a z-score
  or another baseline-normalized metric, explore answering: "How confident are
  we that this observed value differs from the baseline reference / zero?"
  One proposed direction is fitting a probability density to baseline data
  (beta distribution was suggested as a possibility, not a selected model) and
  describing how unusual the observation is under that baseline distribution.
  Open questions: density versus percentile/tail probability versus an interval
  for the baseline-relative effect; which distribution suits each metric and
  its domain; how to handle baseline sample size, overlapping/time-correlated
  windows, and repeated live comparisons. A density value alone should not be
  labeled as the probability that an effect is real. Define the intended
  interpretation before choosing an estimator or a UI confidence indicator.
