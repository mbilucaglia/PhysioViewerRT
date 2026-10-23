# EEG artifact subspace reconstruction

ASR lives under the EEG filter settings in Sources. **Train (45 s)** records a
fresh, independent EEG sample after the button is pressed, then fits the existing
meegkit model in a background task and enables correction. Neither BSL nor EYC
is needed to train ASR. Stay relaxed and still while recording; cancellation
keeps the previous model. Duration is shared in `ViewerSettings.asr_training_seconds`.

The library requires at least 30 seconds of retained clean EEG. The adapter
requires two or more distinct, linearly independent EEG channels, sampling above
82 Hz and a high-pass filter preset. If too little clean data remains, training
fails explicitly; it never removes channels to make training succeed.

1. Select the EEG stream, channels, conversion and filter settings; start EEG.
2. Press **Train** and wait for recording and model fitting to finish.
3. Record EYC and BSL using the cleaned EEG, then inspect Metrics and Affect.

The processing order is **raw → device preprocessing → cleaned data → baseline
analysis and live metrics**. ASR corrects artifacts after EEG filtering. All
selected channel names, order, count and sample count are preserved. There is no
channel deletion setting. The only exposed numerical parameter is threshold
(default 20 sigma). Threshold edits reuse the independent training sample to
update the model; active correction resumes when ready. The checkbox bypasses
correction. Inspect its effect in Raw Data; no separate ASR tab is needed.

Calibration files retain converted raw samples for reproducible analysis. Their
EYC PSD and EEG BSL metric statistics are computed downstream of the same filter
and optional ASR model as live metrics. When ASR or IAF changes, retained BSL EEG
is replayed in the background to obtain matching reference statistics, preserving
PPG/SC/EI references. BSL/EYC completion, loading or clearing never retrains or
removes the ASR model. Raw recording retention is separate from the data used to
calculate references.

Changing ordered channels, sampling rate, units, gain, offset or filter settings
bypasses incompatible models; restore the training settings or train again.
Source gaps reset streaming state. An ASR processing error bypasses correction
while acquisition continues with every channel intact. Baseline references must
match the processing mode; incompatible references are not silently substituted.

## Boundaries and dependencies

- `eeg_asr.py`: validates calibration and wraps the existing meegkit ASR library.
- `asr_session.py`: owns independent training/model and metric reference state.
- `asr_tasks.py`: background fit and matching EEG metric baseline replay.
- `asr_widgets.py`: binds the minimal Designer-owned Sources controls.
- `worker.py`: receiver integration; `gui.py`: lifecycle and composition.

No ASR reconstruction mathematics is implemented in this project. The
[BSD-licensed meegkit implementation](https://github.com/nbara/python-meegkit)
is pinned to revision `7f1b3e0cdce57d7e987106a42f505d13064c3339` in
`requirements-asr.txt`. That upstream revision fixes geometric-median
nonconvergence handling and calibration scalar returns in release 0.1.9.
Training-derived input scaling is fixed across fitting and streaming, and output
is restored to source units. Models carry coefficients, settings, channel/source
configuration, library version and an integrity identifier in plain JSON data;
the application currently fits a session model rather than offering separate
model-file import/export controls.

The streaming library retains bounded covariance and filter state and adds no
lookahead buffer. Covariance estimation and reconstruction blending depend on
transport chunk boundaries; exact equality across different packet partitions
is not claimed. Synthetic tests check artifact attenuation, clean-signal
preservation, sample counts, reset behavior, configuration gating, Qt timer
responsiveness, and real local LSL acquisition. Validate cutoff choices and
signal preservation with recordings from the intended EEG hardware.
