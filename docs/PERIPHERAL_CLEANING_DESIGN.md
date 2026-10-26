# PPG and SC cleaning without reference channels

Status: design proposal, 23 October 2026. No signal-processing behavior is changed by this document. SC is the interface name; the existing internal modality key remains `EDA`.

## Scope update — 26 October 2026

The user has selected waveform artifact reduction, not quality assessment or
metric-window rejection, as the next implementation scope. The quality-first
recommendation below is historical and superseded for this work. Both spike and
broader-motion reduction should be selectable, using published, reproducible
methods. See [current research and provenance requirements](PERIPHERAL_REDUCTION_EVIDENCE.md).
Off / Hampel / experimental wavelet reducers are now implemented in the common
live/baseline pipeline. See the linked evidence document for timing, scientific
departures, measured morphology distortion and remaining real-data validation.

## Earlier recommendation (superseded scope)

Start with explicit signal-quality assessment and rejection of unreliable metric windows, then offer conservative repair of isolated spikes. Keep waveform reconstruction as a separately selectable experimental stage. A plausible-looking repaired trace is not evidence that its HR, pulse morphology, SCL, or SCR measurements are reliable.

All methods below use the acquired PPG or SC channel itself. They require no accelerometer, ECG, external noise channel, or dedicated reference electrode. Without such references, motion and real physiology can overlap in both frequency and shape; the software must be able to say that an observation is uncertain or unavailable.

| Priority | Method | PPG | SC | First implementation decision |
| --- | --- | --- | --- | --- |
| 1 | Timestamp, missing-data, clipping and flatline checks | Detect acquisition faults before filtering | Detect acquisition faults before decomposition | Implement as shared quality infrastructure |
| 1 | Beat morphology and interval quality | Gate HR using accepted pulses and intervals | Not applicable | Use a NeuroKit adapter on bounded trailing history |
| 1 | Robust spike and step detection | Flag narrow impulses without deleting systolic peaks | Flag impulses/contact steps without deleting SCR rises | Detect first; optional limited repair after validation |
| 2 | SC artifact classifier | Not applicable | EDA Explorer SC-only classifier | Optional adapter after compatibility and sensor validation |
| 3 | Wavelet denoising | Can attenuate pulse detail and timing | Potential removal of abrupt motion artifacts | Experimental, disabled by default |

These priorities are engineering recommendations for this application, not a claim that one universal detector separates every physiological event from artifact.

## Current project integration points

`processing_filters.py` builds causal SOS filters; `processing.py:Processor` owns their state and bounded histories. PPG defaults to a 0.5–8 Hz bandpass. SC defaults to no bandpass, with optional low-pass smoothing. Keep these reusable filters rather than adding another library's default filter to the same path.

`physiological_metrics.py:ppg_metrics` currently detects peaks with SciPy, restricts pulse intervals, and returns median-interval HR. It does not assess clipping, waveform quality, or whether an interval crosses a dropout. `Processor.push` rejects non-finite input outright and does not receive timestamps; it cannot by itself distinguish a genuine contiguous sequence from concatenated samples across a gap. Quality processing therefore needs the timestamped worker input, upstream of this processor, and a validity mask alongside its filtered history.

`worker.py` supplies filtered SC to `TonicSCProcessor`; `sc_decomposition.py` already resets its history for invalid samples or timestamp discontinuities. cvxEDA starts from the first one-second hop, progressively growing its history, with no edge exclusion. Preserve that user-selected timing. `calibration.py:analyze_bsl` replays processing and computes baseline metric statistics; its replay must receive the same future cleaning settings and quality policy as live processing.

The catalog contains one canonical `SCL`: tonic SC after cvxEDA decomposition. EI uses that same measurement and its matching baseline statistics. Quality decisions must be attached to each observation and its actual input support; no pre-decomposition median is substituted when decomposition is unavailable.

## Stage 1: acquisition validity and conservative artifact detection

Run checks on original samples and timestamps before filtering. Filtering can hide rails, turn a spike into ringing, or obscure a contact step. Store the original waveform unchanged and publish a separate analysis waveform and quality mask.

- **Dropouts:** detect non-finite values, non-increasing timestamps, and missing sample intervals. Do not concatenate valid fragments into a fictitious continuous signal. Split filter/decomposition histories at hard breaks and expose a recovery state.
- **Clipping:** use hardware limits when known. Otherwise identify sustained extreme plateaus as suspected clipping; observed maxima alone do not prove saturation. Reject affected pulse intervals and SC estimates whose support contains the unrecoverable segment.
- **Flatline:** compare variation and repeated ADC values against duration and sensor resolution. A slowly varying, low-amplitude SC signal is not automatically a disconnected sensor. Use a questionable state when evidence is insufficient.
- **Isolated spikes:** use a robust local residual/derivative detector with median and MAD scale, a nonzero noise floor, and a maximum event duration. A large absolute amplitude alone must not trigger deletion. Start with annotation; enable replacement only for tightly bounded isolated events bracketed by trustworthy samples.
- **Contact steps:** flag abrupt SC level shifts separately from brief impulses. Do not automatically subtract the step or remove low-frequency drift: that would alter the tonic measurement being studied.

Represent limits in seconds and calibrated units where appropriate. Convert to samples at runtime. Physical SC limits are meaningful only when the conversion yields conductance units; an `a.u.` stream cannot inherit arbitrary µS thresholds. Expose sensor-specific settings in one typed configuration rather than scattered constants.

For robust rolling statistics use NumPy and existing SciPy primitives, with a small tested application adapter for masks, event duration and streaming boundaries. Avoid a second general DSP implementation. SciPy's median and SOS filtering primitives already cover these operations. [SciPy signal reference](https://docs.scipy.org/doc/scipy/reference/signal.html)

## Stage 2: PPG pulse quality before metric calculation

Reuse NeuroKit's `ppg_quality(..., method='templatematch')` for morphology assessment on the existing filtered PPG, paired with a supported pulse detector. Its template score measures similarity to the local average pulse, not an absolute probability of clean data. Its dissimilarity alternative also compares pulse shapes. These are quality estimators, not waveform repair. [NeuroKit PPG API](https://neuropsychology.github.io/NeuroKit/functions/ppg.html)

An adapter should operate on bounded trailing windows, finalize only complete pulses, and exclude boundary pulses and pulses intersecting hard invalid intervals. Accept an HR interval only when both endpoint pulses and the intervening samples are valid. Do not delete a bad pulse and calculate an interval spanning the missing beat: that can halve the apparent rate. Require a configurable amount of accepted evidence; retain existing HR history length initially.

Do not interpret template agreement alone as trustworthy: periodic motion can be consistent, and genuine morphology can change. Combine morphology, acquisition validity, pulse prominence, and interval plausibility. Treat unusual intervals as uncertainty rather than automatically repairing an arrhythmia into regular beats. Thresholds require representative data and should not be presented as diagnostic limits.

NeuroKit APIs are window-based; their interpolated per-sample quality arrays do not automatically provide a causal streaming guarantee. Evaluate only data available by each decision time, withhold incomplete boundary beats, and record the resulting decision delay. Pin and test a released version rather than depending on a development-only method name. [NeuroKit quality implementation](https://neuropsychology.github.io/NeuroKit/_modules/neurokit2/ppg/ppg_quality.html)

HeartPy is an alternative for peak rejection and HR analysis, but its Hampel correction is disabled by default and can shift peak positions; its clipping reconstruction is interpolation, not recovery of measured waveform morphology. Do not enable those repairs wholesale. Compare an adapter against NeuroKit before introducing a second PPG analysis dependency. [HeartPy algorithm documentation](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/algorithmfunctioning.html)

## Stage 3: SC quality before tonic/phasic decomposition

Protect slow tonic variation and the natural rise/recovery of SCRs. A real SCR may be a derivative outlier; require multiple indicators or an obvious brief discontinuity before considering repair. Keep sustained steps as separate uncertain segments. Generic detrending or high-pass filtering is unsuitable as a default when SCL is the target.

EDA Explorer's published classifier uses raw/filtered SC derivative and wavelet features in five-second epochs. It can provide artifact/questionable/clean labels from SC features without using its separately provided accelerometer script. Its repository targets older Python versions and assumes particular sampling conventions; integration requires a tested adapter, model provenance and validation on the actual sensor/site/units. A completed epoch incurs up to five seconds of decision latency; it should not become a mandatory five-second startup for all SC rendering. [Taylor et al., original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5413200/) · [Original implementation](https://github.com/MITMediaLabAffectiveComputing/eda-explorer)

A hard-invalid segment must break tonic history. For questionable samples, either withhold the affected observation or explicitly mark it degraded according to a configurable policy. A solver can fit artifacts as tonic or phasic components; successful optimization is not a quality certificate. Quality support for `SCL` includes its full fitting history, not just the final one-second aggregation interval. Expose contamination/recovery rather than claiming that an artifact immediately stops influencing later fits. Keep the current first-hop startup and zero edge exclusion while adding quality metadata. [cvxEDA original implementation](https://github.com/lciti/cvxEDA)

NeuroKit `eda_clean` mainly supplies filtering/smoothing and missing-value handling; it is not a substitute for an artifact detector. Avoid using implicit forward filling to make a dropout appear valid. [NeuroKit EDA cleaning source](https://neuropsychology.github.io/NeuroKit/_modules/neurokit2/eda/eda_clean.html)

## Optional reconstruction and its latency

For an isolated impulse, a bounded replacement using trusted samples on both sides may prevent filter ringing. Require a configured maximum duration, preserve the original mask, and label every replaced sample. Interpolation needs the right-hand endpoint, so it necessarily introduces a small explicit lookahead. A zero-lookahead mode must leave that event flagged rather than pretending to interpolate it causally. Never bridge saturated periods, missing pulses, or long gaps for scientific metrics.

Stationary-wavelet SC denoising is a credible later experiment. Chen et al. model wavelet coefficients to distinguish SC components from large motion coefficients; simply calling generic soft thresholding is not an implementation of that method. Evaluate preservation of tonic offset and SCR amplitude/onset/recovery before enabling it. [Chen et al., original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5413204/)

Use PyWavelets for SWT/inverse SWT and threshold primitives. Define window length, padding, coefficient support, overlap handling and finalized output region explicitly; standard block transforms are not automatically causal. Boundary output is provisional unless there is a declared delay. Do not add an undeclared long startup to the live plots. [PyWavelets SWT documentation](https://pywavelets.readthedocs.io/en/latest/ref/swt-stationary-wavelet-transform.html) · [Threshold functions](https://pywavelets.readthedocs.io/en/latest/ref/thresholding-functions.html)

For PPG, broad wavelet or median smoothing can change systolic timing, the dicrotic feature and pulse amplitude. Offer any future reconstruction separately from HR-quality gating, with retained unmodified data. ICA/ASR are not the preferred default for one PPG or SC channel; reference-based adaptive cancellation is outside this request. A learned denoiser would need independent validation and clear model provenance before use.

## Proposed modular contract

Add a small `peripheral_quality` layer independent of Qt. Keep filtering in `processing_filters`, SC decomposition in its existing module, and metric calculators in `physiological_metrics`. The acquisition worker orchestrates the stages; widgets only edit validated settings and display results.

Suggested contracts, to refine during implementation:

```python
QualitySettings  # per-modality detector parameters, policy, algorithm/version
QualityChunk     # timestamps, original/analysis samples, flags, repaired mask
QualitySummary   # valid fraction, reasons, decision_time, input support
MetricValidity   # valid/questionable/invalid, reasons, used/rejected evidence

quality_processor.push(samples, timestamps, fs) -> QualityChunk
quality_processor.reset(reason)
metric_adapter.calculate(filtered_history, quality_history) -> observations
```

Use reason flags such as `MISSING`, `TIMESTAMP_GAP`, `CLIPPED`, `FLATLINE`, `SPIKE`, `CONTACT_STEP`, `LOW_PULSE_QUALITY`, `REPAIRED`, and `RECOVERING`. A numeric SQI can accompany reasons but must not replace them. Keep signal quality, repaired status and metric validity separate: a sample repaired for display can still be excluded from pulse morphology or HRV.

Every metric observation needs its event time, complete input support, availability time, quality state and pipeline identifier. Baseline and live processing must share identical settings, source conversion, filtering, quality rules and library versions. Include these in source/pipeline metadata and invalidate incompatible baseline transformations. Save accepted/rejected counts and valid coverage with BSL statistics; if there is insufficient clean evidence, do not silently create a reference. Retaining raw calibration data enables later replay under a new pipeline.

On the UI, retain existing plots and palette. Add compact quality badges and unobtrusive invalid/repaired spans. An unavailable HR or tonic SC must propagate to EI and Peripheral affect instead of showing a fresh value calculated from bad inputs. A last valid value may remain visible only with its age/stale label; trails must not connect across invalid intervals. Hidden tabs should continue to skip repainting while quality processing remains active.

## Validation required before enabling cleaning

Use deterministic clean signals plus injected isolated spikes, timestamp gaps, clipping, quantization/flatlines and contact steps. Check no samples are silently fabricated, output times remain aligned, filters recover after resets, and results are invariant to chunk boundaries. Protect physiological cases: rapid HR change, irregular pulses, changing pulse amplitude, slow tonic drift, overlapping SCRs and strong legitimate SCR rises.

Measure both quality-detection errors and metric error; a visually smoother trace alone is insufficient. Compare accepted HR intervals to annotated pulses, and tonic/SCR estimates against uncontaminated reference copies of the same synthetic events. Replay representative manually annotated recordings from the intended sensors, report false rejection of clean physiology, and benchmark processing/decision latency outside the GUI thread. No performance or accuracy claim is made until those checks are performed.
