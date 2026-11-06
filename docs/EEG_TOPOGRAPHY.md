# EEG topoplot in Raw Data

Raw Data has four movable, expandable panels: EEG, PPG, SC and EEG topoplot.
The default wide layout is a conceptual 3×3 grid: EEG spans the first two columns
and all three rows; topoplot, PPG and SC occupy the three rows in the final column.
The initial width ratio is 2:1 and the three side rows have equal stretch. Drag
the splitters to adjust these proportions. Move can swap any two panels,
including which panel occupies the large area; Restore default layout restores
EEG on the left and topoplot/PPG/SC on the right. The narrow layout stacks the
panels and permits vertical scrolling when
needed. Expanding a panel does not stop acquisition.

Choose the topoplot mode directly above the map. Open **… (Topoplot settings)** to adjust:

| Control | Meaning |
| --- | --- |
| Unfiltered | Signed raw voltage in source-reference space; always uses raw input. |
| Delta / Theta / Alpha / Beta / Gamma | Absolute band power, respectively 1–4 / 4–8 / 8–13 / 13–30 / 30–45 Hz. |
| Band-power input | Processed EEG (including active preprocessing/ASR) or raw EEG. |
| Use calibrated IAF | Alpha becomes IAF ±2 Hz when a valid EYC calibration is loaded. Without calibration, Alpha stays 8–13 Hz; a default 10 Hz value is not treated as calibration. Other bands remain fixed. |
| Analysis window | 0.25–10 seconds of continuous EEG, independent of waveform sweep duration. |
| Window overlap | 0–95%; step = window × (1 − overlap). Rendering is capped at 20 maps/s and skips obsolete updates if computation is slower. |
| Unfiltered persistence | 0–2 second exponential time constant τ. Zero shows the latest sample; positive values average recent signed voltages. This is temporal smoothing, so opposing polarities can cancel. |

The **Full scalp** checkbox below the map is
enabled by default. It extends the estimated field to the head boundary. The
status identifies extrapolation; hatching and permanent channel labels are
removed for a clean map. Small circles mark only available valid electrodes;
hover a circle to see its channel name. Uncheck Full scalp
to show only the area enclosed by available electrodes. This checkbox is defined
in the Qt Designer project as `topographyExtrapolate`, inside `TOPOPlotPanel`.

The same footer contains Designer-owned **Colour − / Fit / + / Auto** controls:

- **+** narrows the colour range by the waveform gain step (default 1.2), increasing contrast.
- **−** widens the range by that step, reducing contrast.
- **Fit** fits the currently displayed map once, then holds those limits.
- **Auto** continuously fits every map; unchecking it freezes the current limits.

Minus, plus and Fit turn Auto off. They recolour the existing map immediately,
including while RAW is paused, without recomputing or modifying EEG data. Power
scales stay anchored at zero; signed voltage keeps symmetric negative/positive
limits. Values outside a narrowed manual range saturate visually at the palette
ends; the map data are unchanged. The numerical colour bar shows the active limits.
Manual limits survive new frames, pause, history navigation, window/overlap and
extrapolation changes. A new source/generation, units, band/IAF limits or raw versus
processed input seeds the range from its first new map; the Auto choice is retained.

For a responsive unfiltered map, try a 0.5 s window, 90% overlap, and 0.15 s
persistence. For band power, the initial 2 s window and 50% overlap provide a
one-second update step. Longer windows give finer frequency resolution.
Auto colour scaling is initially enabled. Disable it to compare successive maps
against fixed limits. The numerical color bar and units are always displayed.

All selected EEG channels are considered, independently of the number of visible
waveform traces. Known voltage units are converted to µV; power is in µV².
Missing units remain a.u./a.u.². The source's existing reference is preserved;
the topoplot does not add an average reference or change physiological metrics.

## Locations and interpolation

Positions use the full **standard 10-5 template (343 channel labels)** bundled
from MNE-Python v1.10.2, including 10-10/10-20 sites and intermediate `h` labels
such as `FFC3h` and `CCP2h`. Original 3D coordinates are projected with the nose
up and the subject's left on the left. They are standard template coordinates,
not digitized subject positions. Case-insensitive labels, optional `EEG ` prefixes, reference suffixes
`-REF`, `-LE`, `-RE`, `-AVG` (or underscore), and T3/T4/T5/T6 aliases are supported.
Bipolar labels, unknown names, duplicate positions and nonfinite channels are
excluded and listed in the status tooltip. At least three non-collinear recognized
positions are required. Channel index never determines electrode position.
The same fixed full-template projection is used for every channel subset;
changing selection never shifts an electrode. The three fiducials are excluded
from channel lookup. Only available electrodes receive circle markers.
See [dataset provenance, license and projection details](../assets/montages/README.md).

The 128×128 map uses **regularized Perrin spherical splines**, evaluated on 3D
unit vectors about one sphere fitted to the complete template. Sources and map
pixels share exactly the same sphere origin and inverse projection. The kernel
uses stiffness 4, 50 Legendre terms, a constant-preserving constraint, and diagonal
regularization 1e-5. This follows the method of
[Perrin et al. (1989)](https://doi.org/10.1016/0013-4694(89)90180-6) with the parameter
convention used by [MNE-Python](https://github.com/mne-tools/mne-python/blob/v1.10.2/mne/channels/interpolation.py).

Signed voltage is splined directly. Band-power maps spline **log power**, then
exponentiate back to the original squared units, avoiding negative power and
hard zero clipping. The log floor is 1e-12 times the largest channel power
(bounded below by the smallest normal float); an all-zero field stays zero.
This is a spatial display transform, not a change to measured channel power.
Splines may overshoot electrode extrema, especially with sparse coverage; color
limits include the displayed field so overshoot is not silently color-clipped.

Full-scalp mode extends the same smooth field beyond the sensor convex hull to
the head circle. Without it, values outside the hull remain blank. Both modes
leave everything outside the head circle blank and require three non-collinear
valid electrodes. No virtual channels or recorded samples are created. The
raster uses smooth Qt image scaling, a sequential power palette and a symmetric
diverging voltage palette. This is a sensor-space visualization, not source
localization. Sparse coverage gives less support to extrapolated areas.
For background on the distinction between idealized
montages and measured sensor positions, see the
[MNE sensor-location documentation](https://mne.tools/stable/auto_tutorials/intro/40_sensor_locations.html).
The implementation uses existing NumPy/SciPy/pyqtgraph dependencies. The versioned
coordinate file and license are bundled; the MNE package and network access are
not required at runtime. The outline encloses the full projected template,
including inferior sites, rather than representing an anatomical equator.

## Calculation and lifecycle

Band power uses a full-window Hann Welch periodogram, constant detrending, and
PSD-bin integration over [low, high). Bands above Nyquist and windows containing
fewer than two selected frequency bins show an explanatory message. At least a
complete analysis window is required. Timestamp gaps larger than 2.5 nominal
sample intervals restart the continuous window; gaps are never filled for PSD.

Unfiltered persistence uses source-time exponential weights over the recent
history (at least five time constants), normalized to preserve constant voltage.
It is independent of acquisition packet boundaries. No persistence is carried
across source changes or gaps. The window controls warmup and update cadence;
persistence controls temporal averaging separately.

The map follows the EEG waveform's presentation time, RAW pause, and historical
navigation. While paused, mode/settings changes recompute only from frozen
history. Source resets clear both the image and obsolete pending results.
Hidden maps do not schedule work. One worker performs numerical preparation,
with no pending queue; only the GUI thread updates Qt objects. Each request shares
immutable history blocks for at most ten seconds, and interpolation caches have
a fixed maximum size (two float32 interpolation tables, under 48 MiB combined
for the complete template). Target batches bound temporary spline memory. Electrode graphics are
reused between frames for dense caps. Closing the app joins the worker. No acquisition or metric
processing settings are changed by this view.

## Validation

`tests/test_topography.py` checks synthetic frequency/amplitude/units, IAF/source
selection, signed persistence, packet invariance, future-sample exclusion, unknown
labels, degenerate layouts, gaps and insufficient sampling/window configuration.
It also checks full-head coverage, extrapolation masks, unchanged values inside
the hull, positive/unit-invariant log-power maps, constant fields and unchanged source samples.
`tests_gui/test_topography.py` checks background results, pause/resume, history
navigation, controls, source-generation reset, the Designer-owned extrapolation
control, frozen-map recomputation, circle markers, absence of text labels, manual
colour-range persistence, Fit/Auto, voltage symmetry and source resets. The GUI smoke suite covers
all 24 panel permutations, move/restore and focus behavior.
`tests/test_eeg_montage.py` checks the bundled file checksum, complete label
coverage, fiducial exclusion, orientation, projection bounds, alias duplicates
and dense-cap channel reordering, including exact projection/inverse consistency.
`tests/test_spherical_spline.py` checks exact sensor reproduction without
regularization, constant preservation, an independent analytic spherical field,
rotation/order invariance and invalid coordinate handling.

These checks use synthetic EEG and offscreen Qt; real-device montage labels,
native window rendering and sustained live acquisition still require validation
on the intended workstation.
