# Affect visualization

Implemented as the **Affect** tab. The original concept is now connected to real
LSL acquisition, calibrated metrics, and the live cvxEDA tonic SC pipeline.
Metrics and Affect remain visible but disabled until EYC and BSL references are
loaded. They enable together. The Peripheral response and Emotional Index card
require both active PPG and SC receivers; stopping either removes their visible
geometry immediately, including while the view is paused. Central EEG remains
independent.

## One circumplex, two responses

| Response | Valence | Arousal | Color |
| --- | --- | --- | --- |
| Central | AWI | BAR | Teal |
| Peripheral | HR | Decomposed tonic SCL (`SCL`) | Violet |

Each response has one current dot and a connected, age-fading trajectory. Retention
is selectable (5–120 seconds); pause freezes only presentation. Clear removes
trails without clearing physiological metrics. Either card can expand. Reference
normalization uses separate fixed BSL summaries for the four metrics: z-score,
robust MAD, robust IQR, or baseline min–max. The circle marks a one-unit reference;
it does not constrain the data. Outliers remain available through range/zoom.
Identity is deliberately absent because unlike physical units are not comparable
coordinates on one plane. Missing references, invalid samples, source changes,
and stale results suppress that response's current marker; no placeholder dot
is placed at the origin.

## Tonic SC decomposition

The author-maintained [cvxEDA](https://github.com/lciti/cvxEDA) library performs the
optimization; no decomposition algorithm is reimplemented here. Install via the
normal requirements, which include `requirements-affect.txt`. The adapter uses a
bounded context of up to 20 seconds, a one-second hop, and 8 Hz resampling with
SciPy. Processing starts on the first normal one-second update using the history
already available, growing the context as samples arrive. There is no newest-edge
exclusion or artificial 20-second startup wait. Each estimate averages the trailing
one-second tonic interval through the newest source sample and restores original
conductance units after standardization. The interval center is approximately
half a second before its end because it is a one-second aggregate. These are
development defaults, not a physiological validation of online decomposition.

Live decomposition runs on the SC receiver/processing thread; calibration analysis
runs in a separate Qt worker. Raw reception is not tied to the Affect tab or its
pause state. A missing backend or solver failure leaves raw SC available, with a
decomposition status and no fabricated SCL, EI, or peripheral point.

`SCL` is the single SC metric: tonic conductance after cvxEDA decomposition.
The earlier pre-decomposition median is not a metric or an EI fallback. EI uses
this same tonic SCL and its matching BSL reference statistics. Acquisition and calibration use the
same converted/prefiltered samples and rolling adapter. BSL summaries include the
backend version, parameters, pipeline/configuration identifiers, unit, source
conversion, and prefilter settings. Peripheral points require the live configuration
identifier to match that baseline. Source rate, selected channel labels, units,
conversion and prefilter metadata are checked independently for EEG, SC and PPG;
an incompatible modality suppresses only its corresponding response. A new IAF
requires compatible EEG baseline statistics. Loading an older BSL recording reanalyzes its
samples to create compatible tonic references; an old median SCL summary is never
silently reused as tonic SCL.

Metric dictionaries carry `_observations` with value, source-window bounds,
availability timestamp, unit and pipeline ID. The seven-field acquisition payload
remains compatible. Existing Metrics histories retain their availability-time
presentation; Affect pairs on LSL source time. Central AWI/BAR share an EEG result;
Peripheral selects the last HR at or before the tonic interval end within a
one-second tolerance. It never substitutes current HR for delayed tonic SC. The
model retains bounded raw pairs, so display ticks only reproject/fade them.

## Separate signed Emotional Index

The second card shows the **original signed EI**, a diverging negative/positive
gauge with a zero reference and recent history. It does not assign arousal or
valence to EI. Its sign is never changed by the circumplex normalization selector.
EI recomputes on every HR or decomposed SCL observation using the latest available
value of the other input. It has no timestamp-skew or age gate and remains visible
between updates. Explicit missing/invalid input or stopping either source clears
it. BSL replay follows the same latest-value update policy with fixed HR/SCL
references. An HR value at its baseline mean is evaluated with the angular
formula, rather than suppressed by the batch all-zero-epoch guard.

Both Metrics and Affect display the original signed EI; no additional EI display
reference is required and the Metrics normalization selector does not change it.
The shared Metrics ruler identifies mixed scales when normalized metrics and
original EI are shown together. Invalid history interrupts the line. Zero is a
numerical reference, not a separate emotion-neutrality calibration. Missing
inputs or unusable BSL HR/SCL statistics have explicit status messages.

## Ownership and verification

- `sc_decomposition.py`: existing-library adapter and backend/input provenance.
- `metric_observation.py`: source-window observation contract.
- `affect_state.py`: pure pairing, normalization, freshness, and bounded trails.
- `affect_widgets.py`: Qt controls, persistent VisPy geometry, and signed EI view.
- `gui.py`: composition, calibration/source lifecycle, and display scheduling.

Pure tests cover causal pairing/skew, missing/stale inputs, source resets,
normalization/outliers, backend/reference compatibility, physical-unit restoration,
streaming/batch consistency, and asynchronous provenance. GUI tests cover pause,
expansion, absent markers, persistent visuals, and real local LSL streams through
cvxEDA to both current dots. Synthetic-data checks validate the software path,
not the psychological interpretation of the coordinates.

## Dependency attribution

cvxEDA is by Luca Citi and collaborators and is licensed under GPL-3.0. See its
[license and citation instructions](https://github.com/lciti/cvxEDA/blob/main/README_PYTHON.md#license--citation).
Research publications should cite Greco et al., “cvxEDA: a Convex Optimization
Approach to Electrodermal Activity Processing”, DOI 10.1109/TBME.2015.2474131.
Distributions that include/link this dependency must satisfy its license terms.
