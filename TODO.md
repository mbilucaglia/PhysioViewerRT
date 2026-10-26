# PhysioViewerRT handoff — 23 October 2026

## EI normalization correction — 26 October 2026

- [x] Keep required HR/SCL baseline z-scores inside the raw EI formula.
      Normalize resulting EI like every other metric using the selected display
      method and the EI baseline distribution. Metrics and Affect selectors are
      independent; EI is no longer forced to a second z-score.
- [x] Remove special standardized-EI labeling. Keep the card named Emotional
      Index, explain the selected method's numerical zero and fixed min/max
      endpoints, and use normalization-specific units without clipping values.
- [x] Preserve raw EI history and baseline computation; missing/degenerate EI
      spread affects only normalized views. Designer controls/tooltips and tests
      cover independent selectors, robust scales and out-of-baseline min–max.

- Validation: 212 core tests passed; 73 focused core/GUI checks passed with two
  offscreen GL skips; 12 native Affect checks passed, including live LSL input.
  Native preview inspected. Selector combinations, missing/zero baseline spread,
  retained raw EI and unbounded min–max values are covered.

## Next development priority — published PPG and SC artifact reduction

User clarification, 26 October 2026: reduce artifacts in original waveforms,
not quality assessment or rejection of metric windows. Offer Off / spike
reduction / broader motion reduction as selectable alternatives per modality.

- [ ] Select reproducible, published waveform-reconstruction methods for PPG and
      SC, with exact source citations, algorithm steps and documented parameters.
      Research candidates and provenance checks: docs/PERIPHERAL_REDUCTION_EVIDENCE.md.
- [ ] Verify complete papers/reference implementations and numerical reproduction
      before integration. The unpublished causal Haar draft was removed, not shipped.
- [ ] Implement selected methods with explicit streaming latency, boundaries and
      settings. Clearly distinguish a faithful reproduction from an adaptation.
- [ ] Add Designer Processing selectors, preserve original/processed comparison,
      and apply identical transformations to BSL and live HR/SCL/EI/Affect.
- [ ] Validate both attenuation and preservation of physiological morphology on
      matched synthetic and real recordings. No peripheral-reduction code is
      currently enabled; existing filters and cvxEDA remain unchanged.


## Threshold updates and EEG display — 26 October 2026

- [x] Cutoff changes reuse the learned mixing matrix, retained calibration and
      cached RMS distribution factors. Only the rejection threshold matrix is
      rebuilt; no new recording or backend refit. EYC/BSL references still replay
      against the changed cleaning behavior. Older models without cached factors
      require one new training session rather than silently refitting.
- [x] EEG channel centering follows visible traces: raw-only anchors to raw;
      cleaned-only and both anchor to cleaned. Switching traces invalidates old
      render geometry and redraws a paused view without changing stored samples.

- Validation: 212 core tests passed; full GUI suite passed 116 tests with two
  offscreen GL skips. Five native checks passed, including actual viewport-median
  centering during pause in both renderers and threshold updates guarded against
  any ASR fitting call. Updated thresholds match full-refit results numerically.

## High priority — real-data ASR reliability and feedback

- [x] Adaptive ASR training accumulates at least 60 seconds of accepted
      one-second windows, excluding startup and detected flat/clipped/dependent
      signals, interruptions and large amplitude transients. Continuous live
      filtering precedes selection and ASR. Rejected intervals do not advance
      accepted time; source timestamps/window boundaries are retained.
- [x] Designer training popup shows a large quality LED and subject-facing
      instructions, accepted/elapsed/excluded seconds and fit status. Automatic
      completion requires a successful backend fit; failed fitting collects more
      accepted EEG and retries after 10 additional accepted seconds. Five-minute
      timeout/cancel preserves the previous model. Quality screening is heuristic;
      green does not guarantee artifact-free EEG or future cleaning effectiveness.
- Validation: 210 core tests passed; full GUI suite passed 112 tests with two
  offscreen OpenGL skips, plus cancellation/retry lifecycle checks. Native live
  LSL training completed automatically in 65.6 seconds with at least 60 accepted
  EEG seconds. Captured and inspected subject-feedback previews.
- [ ] Validate the screening criteria and training success on real EEG hardware.
      The adaptive amplitude reference updates only from accepted windows after
      startup. Review failures, false acceptance and false rejection on recordings.
- [x] Distinguish ASR monitoring from correction in Raw Data. Green lights only
      for backend non-identity reconstruction (including release blending), with
      a 0.5-second visible pulse. Monitoring remains gray; waiting, off and bypass
      states stay distinct. Tested against backend matrices and injected artifacts.
      Real-hardware effectiveness validation remains open.

## Live processing and baseline display — 26 October 2026

- Raw Data ASR indicator reports actual worker execution: idle, off, waiting,
  monitoring, correcting, or bypassed. Green indicates recent reconstruction,
  not guaranteed artifact-removal effectiveness.
- Raw EI retains the angular HRz/SCLz formula. Metrics and Affect apply their
  respective selected display normalization to EI, with no ±1 clip.
- EI input references follow live peripheral pipeline compatibility; changing
  baseline clears old EI observations. Affect exposes HRz/SCLz/raw EI diagnostics.
- Metric readouts and rulers show normalization-specific units for every metric,
  including EI. Original HR/SCL use bpm/source units; mixed units are identified.
- Metrics Auto range continuously fits Y; Fit is a one-time fit and −/+ hold a
  manual zoom. These affect display only, independently of normalization.
- Real hardware ASR efficacy still needs a controlled artifact comparison with
  representative clean training EEG. An active indicator alone cannot establish it.

## Completed in this delivery

- Modern Qt Sources, Raw Data, Metrics and Affect layouts; shared action icons
  and BrainLab assets live in the repository and Designer UI.
- Shared raw amplitude/time rulers, per-signal expansion/autoscale controls,
  multichannel EEG display and asynchronous source/channel reconfiguration.
- Central AWI/BAR and Peripheral HR/SCL trajectories, plus EI following the selected display normalization.
  Peripheral response and EI require live PPG and SC; both analysis tabs remain
  visible but disabled until EYC and BSL are available.
- One canonical SCL from cvxEDA decomposition, shared by Metrics, EI and baseline
  statistics; no extra 20-second startup or edge exclusion.
- ASR is in Sources under EEG filters: enable, Train, threshold and status.
  Train accumulates at least 60 accepted EEG seconds independently of EYC/BSL. All selected
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

## Remaining backlog (after PPG/SC preprocessing)

- [ ] Validate with real EEG, SC and PPG hardware: units/gain/offset, clean ASR
      training, motion artifacts, stream gaps/reconnection and long sessions.
      Confirm channel order and corrected-signal amplitudes against recordings.
- [x] Retain EYC raw recording and replay EYC first, then EEG BSL, when
      active ASR/filter settings change. BSL uses the new IAF and matching cleaned
      pipeline. Pending/failed replay blocks references; incompatible recordings
      are rejected. Completed 26 October 2026; see WINDOWS_SETUP.md.
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

- **ASR training-quality / effectiveness popup.** Initial duration-based report
  implemented on 26 October 2026 (see below); further quality measures remain
  exploratory. After training, show a summary
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


## Compact Sources UI — 26 October 2026

- [x] Group existing filters into Designer-owned Processing panels for EEG,
      PPG and SC; EEG also includes ASR with compact training/threshold rows.
- [x] Scroll Sources vertically and stack cards on narrow windows. Native
      Windows previews checked at 1024×700, 1280×720 and 1600×1000.
- [x] Keep channel checkbox popup open for repeated selections; Escape/outside
      click dismisses it. EEG remains multichannel; PPG/SC select one channel.


## ASR training report — 26 October 2026

- [x] First implementation of the training-quality popup: automatically show
      recorded, retained and excluded duration/percentages, minimum retained
      duration, channel count, sampling rate and cutoff after successful new
      training. Reopen using Training report in EEG Processing, even after Stop.
      Threshold refits update the report without repeatedly opening a popup.
- The popup is nonmodal and defined in designer/ASRTrainingReport.ui. It reports
      backend training-window selection, not verified clean-data percentage or
      predicted cleaning effectiveness. Contamination and model-stability
      estimates remain exploratory; the metric-uncertainty idea is unchanged.


## Adaptive layouts and compact styling — 26 October 2026

- [x] Compact EEG Processing into a filter row, wrapping ASR action groups and
      a separate status line. Reduce nested borders and panel padding.
- [x] Wrap Raw Data and Metrics toolbars by related control groups. Wrap metric
      selectors/readout cards and stack Affect cards when space is limited.
- [x] Move Affect toolbar controls into designer/AffectControls.ui; preserve
      action names and processing behavior. All main tabs have scroll fallback.
- [x] Native Windows previews checked at 100%, 125% and 150% Qt scaling with
      1024×700 and 1280×720 logical windows, plus 853×480 and 900×560 at 150%.
      No horizontal scrolling in the checked states. Windows limits the largest
      150% preview to available screen height. These previews used empty plots;
      extended hardware sessions and active-data visual checks remain open.
- Validation: full GUI suite 90 tests, 88 passed / two native OpenGL skips;
      the additional resize/connection regression test passed separately.


## Maximized-window fitting — 26 October 2026

- [x] Let Raw Data, Metrics and Affect plots shrink from preferred height to
      the available viewport, so fitting content does not force a scrollbar.
      Preserve scrolling when controls/plots genuinely need more space.
- [x] Adapt Sources to one, two or three columns. Wide windows show EEG, PPG
      and SC side by side, with natural-height cards rather than stretched boxes.
      The wide default and viewport-fit flags are defined in Qt Designer.
- Native maximized 1920×1009 client-area checks: all four tabs fit with zero
      horizontal/vertical scroll range. Smaller windows retain scrolling.
- [x] Put Raw Data and Metrics Play/Pause beside Live, with matching icons
      and labels. Display pause keeps acquisition and ASR processing running.


## Stop buttons after stream changes — 26 October 2026

- [x] Keep Stop clickable while channel/source reconfiguration or metadata lookup
      is pending, so it can cancel automatic restart. Explicitly enable Stop on
      each replacement receiver; the old path left it disabled after reconnect.
- [x] Verify display-count changes do not restart acquisition or disable other
      modalities. Native Windows test against all three running synthetic streams
      passed Stop during pending EEG changes, after automatic reconnect, and for
      PPG/SC after EEG display-count changes.
- [x] Add button-click regressions for pending cancellation, post-reconnect Stop,
      metadata-wait cancellation and independent stream Stop controls.
- Validation: complete GUI/LSL suite 95 tests, 93 passed and two native
      OpenGL checks skipped in offscreen mode; native three-stream checks passed.


## Raw Data workspace arrangement — 26 October 2026

- [x] Wide windows show EEG on the left and PPG/SC stacked on the right.
      Narrow viewports switch to a vertical stack; dividers remain adjustable.
      The nested splitters and grouped headers are defined in Qt Designer.
- [x] Keep plot title/Expand and gain/Autoscale controls together, removing the
      large gap between the gain label and its buttons. Group the shared toolbar
      in a compact card; preserve Play/Pause and all named controls.
- Native check with all three synthetic streams: 32 EEG channels processed,
      eight displayed; Expand/Restore for EEG/PPG/SC passed, all receivers stayed
      active, no maximized horizontal or vertical scrolling. Captured wide and
      1024×700 live previews. GUI smoke/flow checks passed.


## Rearrange Raw Data panes — 26 October 2026

- [x] Add Designer-owned Move buttons beside each signal title. Swap a signal
      with either other pane or restore the default EEG/PPG/SC arrangement.
      Arrangement is session-local; moving panels does not change acquisition,
      signal history, gain, processing or renderer ownership.
- [x] Keep Expand/Restore and narrow-window stacking correct after a swap.
- Validation: all six arrangements checked with native OpenGL and three live
      synthetic streams, including EEG upper-right / PPG main. Fifty affected
      GUI checks passed; live receivers and renderer objects were preserved.


## Affect and Metrics arrangements — 26 October 2026

- [x] Give Affect a Designer-owned splitter workspace with Move menus on
      Affect landscape and Emotional Index; swap or restore the default order.
      Narrow windows stack the panes; Expand/Restore and source availability
      remain correct, preserving trails, manual range and pause state.
- [x] Give Metrics movable trend/value panes and Move menus on each metric
      summary card. Keep the combined trend chart; reorder cards without
      replacing curves, histories, normalization or acquisition state.
- [x] Scroll the metric-value pane when its cards cannot fit. All arrangements
      are session-local and can be reset through Restore default layout.
- Validation: full GUI suite 100 tests, 98 passed and two offscreen OpenGL
      skips. Native previews with synthetic demonstration trajectories verified
      swaps, retained canvas/manual range/pause, zero maximized scroll range and
      access to metric cards through the inner scrollbar in short panes.


## Calibration dialog contrast — 26 October 2026

- [x] Explicit light surfaces and dark text for calibration instruction/result
      dialogs, progress dialogs and read-only BSL statistics under Windows dark
      palettes. Give EYC PSD plots a white background and dark title/axes.
- [x] Move the shared EYC/BSL inspection layout into
      designer/CalibrationInspection.ui. Preserve calibration calculations and
      the recording screens' readable white-on-black instructions/fixation.
- Native dark-palette previews checked: EYC PSD, BSL statistics, instruction
      message box and both EYC/BSL recording screens.


## Persistent metric marker cleanup — 26 October 2026

- [x] Fix ghost measured-point squares in the incremental GPU Metrics sweep.
      Sparse, jittered measurements can land in different 20 Hz slots each cycle;
      expire old marker slots by timestamp rather than relying on overwrites.
      The shared latest-measurement cursor also expires stopped-series markers.
- [x] Regression reproduces jittered sparse measurements over five sweeps and
      compares visible GPU updates with the timestamp-based reference. Preserve
      prior-cycle points ahead of the cursor and existing incremental Raw lines.


## Cross-tab action and style coherence — 26 October 2026

- [x] Standardize Expand/Restore, Move and Play/Pause captions, icons, tooltips
      and header order across Raw Data, Metrics and Affect. Add Expand/Restore
      to both Metrics panes. Align pane headings, spacing and card styling.
- [x] Give calibration controls mode-specific Record/Load/Clear actions and
      symbols; use recording symbols for ASR training, and the follow-live symbol
      for following the sweep. Clarify Processed (black) and Measured points.
- [x] Add Metrics vertical zoom out/Fit/zoom in and Auto range in both renderers.
      Manual zoom/Fit hold the chosen range; re-enable Auto range to follow values.
      Fit uses visible finite samples; presentation changes preserve observations.
- [x] Correct time zoom signs in Raw Data/Metrics (+ zooms in, − zooms out) and
      show custom time-window values rather than leaving the selector blank.
- Native review: all four tabs at 1024×700 / 1280×720 and small 150% viewports
      (853×480 / 900×560), without horizontal overflow. Native synthetic previews
      checked Metrics vertical controls, expansion and swapping.
- Validation: full GUI suite 108 tests, 106 passed and two offscreen OpenGL
      skips. Cross-tab tests compare actual icon images and button states. Native
      checks exercised Metrics vertical zoom/Fit and preserved manual view state.


## Sources trailing space — 26 October 2026

- [x] Remove the expanding empty grid row below Refresh. Extra viewport height
      now goes to occupied source-card rows; Baselines and Refresh remain at the
      bottom. Keep cards in one/two/three columns and retain small-window scrolling.
- [x] Encode the wide default row stretch in Qt Designer and use the same policy
      in the responsive controller. Regression checks footer position and absence
      of trailing expanding rows. Native maximized and small 150% previews passed.


## Compact vertical controls — 26 October 2026

- [x] Remove editable vertical-gain values from Raw Data plot headers. Keep
      minus/Fit/plus buttons and bounded internal gain state; source-conversion
      gain/offset controls remain acquisition settings, independent of this view.
