# Peripheral artifact reduction: research and implementation status

## Current user requirements — 26 October 2026

- Reduce artifacts in the actual PPG and SC waveforms. Do not substitute signal
  quality scores, classification badges or rejection of metric windows.
- Offer selectable alternatives for brief spikes and broader motion artifacts,
  with one method active at a time per modality; Off preserves current behavior.
- Use published research. Identify the exact algorithm, source, parameters and
  implementation provenance. A generic wavelet transform is not enough to claim
  a particular published artifact-removal method has been implemented.
- Preserve original samples and apply identical selected processing to baseline
  analysis and live downstream HR/SCL, EI and Affect calculations.

## Important status

No new peripheral artifact reducer is implemented or enabled in the application.
An unpublished causal Haar/robust-clipping draft was removed before committing.
It was not equivalent to the published SWT methods below. The existing filters
and cvxEDA decomposition remain unchanged.

## Research candidates, not yet selected implementations

| Signal | Published method | Relevance and outstanding checks |
| --- | --- | --- |
| SC | Shukla, Barreda-Ángeles, Oliver & Puig (2018), *Efficient wavelet-based artifact removal for electrodermal activity in real-world applications*, Biomedical Signal Processing and Control 42:45–52. [Publisher/DOI](https://doi.org/10.1016/j.bspc.2018.01.009) | SWT reconstruction with a Laplace model of detail coefficients; the publication reports online testing. Obtain and verify the complete algorithm, threshold formula, windows, padding and output delay before implementation. |
| SC | Chen et al. (2015), *Wavelet-Based Motion Artifact Removal for Electrodermal Activity*. [Full paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5413204/), [DOI](https://doi.org/10.1109/EMBC.2015.7319814) | SWT with a two-Gaussian coefficient model and tail thresholds, followed by waveform reconstruction. Its reported experiment used 8 Hz SC, Haar, eight levels, artifact proportion 0.01 and a 400-second estimation window. Do not silently substitute a short causal window and describe it as the same validated procedure. |
| PPG | Biswas, Singha Roy & Gupta (2019), *Motion Artifact Reduction from Finger Photoplethysmogram Using Discrete Wavelet Transform*, pp. 89–98. [Publisher/DOI](https://doi.org/10.1007/978-981-10-8863-6_10) | A modality-specific DWT/thresholding study; an author-uploaded text reports comparisons including db6 and SURE soft thresholding. Verify the full decomposition depth, sampling/window assumptions, boundary handling and exact threshold definition against the paper before choosing it. |
| PPG | Peng, Liu & Wang (2015), *A comb filter based signal processing method to effectively reduce motion artifacts from photoplethysmographic signals*. [PubMed](https://pubmed.ncbi.nlm.nih.gov/26334000/), [DOI](https://doi.org/10.1088/0967-3334/36/10/2159) | Wavelet preprocessing followed by period estimation and a period-dependent comb filter. Do not implement just a generic wavelet stage and label it as the full published method. Correct period estimation is a material dependency. |

Hampel/median despiking remains a candidate for the spike alternative, not an
approved shared PPG/SC recipe. Confirm signal-specific supporting research and
parameters. HeartPy's documented Hampel corrector subtracts a one-second median
and can shift peaks; that should not be silently applied to tonic SC or described
as a validated universal waveform repair. [Author documentation](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/algorithmfunctioning.html)

## Required implementation evidence

1. Obtain the complete publication/reference implementation and select a
   reproducible method separately for each modality and artifact type.
2. Map every numerical stage and default to the source. Record any departures,
   including reduced windows, downsampling, causal operation and edge handling.
3. Reproduce reference outputs before introducing a streaming adapter. Specify
   buffering delay and finalized samples; no hidden timestamp shifts or padding
   presented as acquired data.
4. Test artifact attenuation and preservation of clean PPG beats, tonic SC and
   genuine SCRs on matched recordings. Synthetic tests do not establish real-data
   efficacy. Record any real-time adaptation as an adaptation requiring validation.
5. Only then wire the selected tools into Designer Processing panels and the
   shared live/baseline pipeline. Keep quality assessment outside this scope.
