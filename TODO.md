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
