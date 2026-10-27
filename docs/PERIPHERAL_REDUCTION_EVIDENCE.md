# Peripheral waveform artifact reduction — 26 October 2026

## Status and scope

Sources > PPG/SC > Processing now offers Off, Spike reduction (Hampel), and
Wavelet (8 s · experimental), independently per modality. Off is the default.
One method is active at a time, upstream of the existing filters and downstream
metrics. Original acquired samples are retained. This adds waveform reduction,
not quality scores or additional quality-based metric-window rejection.

These are research-based streaming adaptations, not numerical reproductions of
the published experiments or established real-hardware efficacy. No original
reference output dataset was available for an output-for-output comparison.
The earlier unpublished causal Haar/clipping draft was removed before shipping.

## Sources, parameters and departures

### PPG wavelet

Biswas, Singha Roy & Gupta (2019), *Motion Artifact Reduction from Finger
Photoplethysmogram Using Discrete Wavelet Transform*, pp. 89–98.
[DOI](https://doi.org/10.1007/978-981-10-8863-6_10),
[author-uploaded paper](https://www.researchgate.net/publication/325067603_Motion_Artifact_Reduction_from_Finger_Photoplethysmogram_Using_Discrete_Wavelet_Transform).

The study used 60 Hz, 30-second recordings and compared wavelet/threshold
choices. The selected implementation uses db6, five decomposition levels,
SURE/rigrsure soft thresholds, including approximation A5 and details D5–D1,
then inverse DWT. SURE minimizes the unit-noise soft-estimator risk and scales
the threshold back to the coefficient units; it is not a universal threshold.
[Threshold definition](https://www.mathworks.com/help/wavelet/ref/thselect.html).

Explicit application conventions: eight-second trailing windows, one-second
updates; polyphase resampling to/from 60 Hz; symmetric DWT extension; a single
noise scale median(abs(D1))/0.6744897501960817. These noise/boundary conventions
are not fully specified in the paper. The shorter streaming window is a
departure from its recording protocol and requires validation.

### SC wavelet

Shukla, Barreda-Ángeles, Oliver & Puig (2018), *Efficient wavelet-based artifact
removal for electrodermal activity in real-world applications*.
[DOI](https://doi.org/10.1016/j.bspc.2018.01.009).
The publisher abstract/partial Methods describes SWT/Laplace reconstruction and
online testing. Full numerical steps were cross-checked against the authors'
[companion technical disclosure EP3466322A1](https://patents.google.com/patent/EP3466322A1/en),
rather than inventing parameters absent from the accessible article text.

Eight-second windows, one-second updates; power-of-two analysis rate; Haar SWT
with J=log2(fs)+2; zero detail bands at/above 0.5 Hz. For lower bands, fit a
zero-location Laplace scale b=mean(abs(detail)), zero coefficients whose
absolute value exceeds T=-b*log(0.10), retain approximation, then inverse SWT.
This is a two-sided tail proportion of 0.10. The rendered disclosure's quantile
equation has a sign/order inconsistency when log(delta)<0; the implementation
uses ordered negative/positive quantiles and tests their tail probability.

Explicit adapter conventions: nearest power-of-two analysis rate with polyphase
resampling; four seconds of reflection at each edge plus divisibility padding;
estimate b on the transformed original eight-second core, excluding padding.
The disclosure permits padding but does not specify this extent/mode or this
core-only estimator. PyWavelets SWT/ISWT uses norm=False and coefficient order
AJ,DJ … A1,D1. [Backend documentation](https://pywavelets.readthedocs.io/en/latest/ref/swt-stationary-wavelet-transform.html).

This is not Chen et al.'s Gaussian-mixture SWT method, which used a 400-second
estimation window. [Chen full paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5413204/).

### Spike reduction for PPG and SC

Standard centered seven-sample Hampel replacement: local median, scale
1.4826*median(abs(x-median)), replace samples beyond three scales by the median.
Three future samples are required. Endpoint reflection is internal. A zero
local MAD replaces values different from the local median.

[HeartPy author documentation](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/algorithmfunctioning.html)
documents Hampel filtering and separately warns about its one-second
median-subtraction corrector. We implement replacement, without that detrending
step. SC use is a general robust-filter application, not a claim that HeartPy
validated these SC parameters. It targets narrow impulses; it does not promise
to reconstruct prolonged contact loss or separate motion from physiology.

## Timing and common baseline/live processing

- Hampel emits only points with three real future samples: about 23.4 ms at
  128 Hz PPG or 93.8 ms at 32 Hz SC, plus transport and rendering time. The first
  output waits for seven samples. The last three remain pending for future data.
- Wavelet initially buffers eight seconds, emits that reconstructed window,
  then finalizes the latest one-second interval from each trailing window.
  Unfinished hops wait for more input. Startup backfill therefore contains
  samples up to eight seconds old; steady-state delivery occurs in one-second
  batches, not with zero latency. Emitted samples are never revised.
- Original and processed waveforms are emitted together at identical original
  acquisition timestamps. Padding is never displayed as acquired data. Both
  traces wait for the reducer; time labels are not shifted to hide the delay.
- Metrics use each observation's source window end, converted from LSL to the
  GUI's monotonic clock. Availability time is retained separately. EI uses the
  latest of its two input times; Affect retains source timing. Existing metric
  analysis windows and cvxEDA computation add their own availability delay.
  This alignment does not remove filter phase effects or imply synchronized
  HR/SCL analysis windows.
- BSL replay uses the same Processor and selected reduction/filter settings as
  live analysis. Only emitted SC samples/timestamps reach cvxEDA. Pending tail
  samples remain in the saved original recording. Mode/version are recorded in
  source preprocessing metadata; changing mode invalidates incompatible BSL
  references. Record or load a matching baseline after choosing processing.
- A source gap resets reducer and filter history; no interpolation across gaps.
  PyWavelets is pinned to 1.10.0. Rerun setup after pulling this dependency.

## Verification and limits

Independent SURE-risk and Laplace-tail checks; bulk versus 17-sample chunk
invariance; exact original samples/timestamps; warmup/tail handling; bounded
context; gap reset; baseline waveform/time parity; Designer controls; delayed
metric history; actual simultaneous PPG/SC LSL acquisition are covered by tests.

Matched 16-second synthetic noise-plus-two-sample-spike fixture (seed 2):

| Signal / tool | Input RMSE | Output RMSE |
| --- | ---: | ---: |
| PPG Hampel | 0.1519 | 0.1165 |
| PPG wavelet | 0.1520 | 0.0828 |
| SC Hampel | 0.1879 | 0.0192 |
| SC wavelet | 0.1874 | 0.0266 |

These synthetic units/fixtures establish neither clinical nor real-motion
efficacy. Artifact attenuation is incomplete. On a clean 24-second synthetic
PPG, Hampel left the waveform unchanged; wavelet RMSE was 0.0252, preserved all
29 detected beats and changed peak timing by at most one sample (128 Hz).
Constant SC was preserved to numerical precision. A genuine synthetic SCR
(0.7-second rise, 3-second decay) was attenuated: wavelet peak above 3 µS fell
from 0.5178 to 0.4315 µS, about 16.7%; whole-signal RMSE was 0.0503 µS.
Hampel left this SCR unchanged. This is why wavelet remains optional and marked
experimental; it can alter genuine physiological morphology.

On this PC, 25 eight-second block repetitions measured median/p95 runtimes
of 0.64/0.71 ms for PPG at 128 Hz and 8.36/8.57 ms for SC at 32 Hz, below the
one-second update interval. These are local processing benchmarks, not a
guarantee of latency on another PC or with other concurrent workloads.

Remaining: compare against reference implementations/data where available;
validate on matched real clean/artifact recordings and target hardware, assess
SCR morphology and HR/SCL/EI bias, and review boundary/window sensitivity.
No automatic claim of signal quality or successful artifact removal is made.

## Compact per-signal processing feedback — 26 October 2026

Raw Data has one small dot beside each signal title: EEG ASR, PPG reduction and
SC reduction. They move with their panels when swapped or expanded. There is
no additional status row or global ASR indicator. Hover for the exact state;
the same text is exposed as the accessible name.

Gray means idle, Off, or monitoring without a recent modification; amber means
updating, buffering or waiting. Green pulses for 0.5 seconds after actual sample
modification. ASR retains its red bypass/error state. Display pause does not stop
these acquisition/processing indicators.

PPG/SC feedback compares emitted reduced samples against matching original
samples **before ordinary filters**, using rtol=1e-9 and atol=1e-12 to disregard
numerical roundoff. A green dot indicates that at least one emitted sample
changed, not that a physiological artifact was identified or successfully
removed. The pulse follows processing delivery; buffered data retain their
earlier acquisition timestamps. A source gap restarts buffering. No fresh
processed output for two seconds changes the state to waiting.

Hampel checks its three-local-scale outlier threshold; wavelet processes every
window using coefficient thresholds and can modify clean physiology on every
update. Therefore a frequently green wavelet indicator is possible without a
large artifact. This is not the same trigger mechanism as trained EEG ASR.

## Missing Wavelet dependency recovery — 27 October 2026

The affected remote PC confirmed `ModuleNotFoundError: No module named 'pywt'`.
Previously the first eight-second Wavelet window triggered this import inside
the receiver, terminating acquisition. Receiver completion then replaced the
useful error with a generic message. `requirements.txt` already pins
`PyWavelets==1.10.0`; pulling Git changes does not install dependencies.

Processing now owns a dependency check used both by reducer construction and
the GUI before requesting a source replacement. An unavailable selection
preserves the running receiver and restores its processing selection. A new
start is rejected before creating a receiver, with setup instructions. The
receiver retains its terminal error for the completion handler. Numerical
algorithms, eight-second startup, one-second updates and the 250 ms presentation
buffer are unchanged.

Five new regression tests failed before this fix and passed afterward (0.552 s).
The full core suite passed 230 tests in 17.998 s. The GUI suite ran 141 tests in
146.485 s, with three skips and no failures.

`tools/validate_wavelet_switches.py` exercises native Qt/VisPy using its own
independent LSL producer: 32 EEG channels acquired, eight displayed, ASR off;
PPG 128 Hz and SC 32 Hz. It selects both Wavelet modes at four seconds, then
returns PPG to Off at 22 seconds and SC at 25 seconds. The 29-second local run
reported no receiver errors. Between 15 and 21 seconds each canvas recorded
181 draw events; data-tip spans were EEG 5.9766 s, PPG 5.8906 s and SC 6.0313 s.
After returning to Off, PPG/SC tips advanced 2.9844/3.1563 s in the 26–29 s
observation interval. All Stop command calls together took 0.7823 ms; this is
command dispatch time, not receiver shutdown latency.

An independent review requested explicit assertions for recovery to Off and
continued EEG progression. The final probe includes both and passed a second
native run with no receiver errors and 0.7969 ms Stop command dispatch.

Hardware was the same Windows 11 / Ryzen Threadripper PRO 5975WX / GeForce
GT 730 / Python 3.12.10 host recorded in `RENDERING_REFACTOR_RESULTS.json`.
Suites and the native probe ran concurrently: this is behavioral evidence,
not an isolated latency benchmark or a new p95/p99 baseline comparison.
Missing-package coverage used an unavailable-module fixture; the native run
used installed PyWavelets. The other PC still needs dependency installation,
application restart and retesting. Real-device smoothness and the remaining
rendering performance acceptance gates remain unverified.
