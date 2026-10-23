# Editing the desktop interface

Open `PhysioViewerRT_ClinicalLayout.ui` in Qt Designer. Static Sources, Raw Data
and Metrics controls, including EEG ASR, Expand, Autoscale, and their icons, are
defined here. Preserve their object names when moving or styling controls.

SVG icons are ordinary files in `../assets/icons/`; the `.ui` references them
directly, so Designer can show them without running Python. Window branding uses
`../assets/brainlab-logo.png`. Runtime action states use these same SVG files via
`physiolab/ui_icons.py`. That module loads QtSvg explicitly for Windows deployments.

Metrics cards and control styling live in the form's stylesheet. Runtime metrics
come from the metric catalog, so additional metrics receive selectors/readouts
without separate layout code. Plot canvases and the Affect visualization are
inserted into the named hosts at runtime.

EEG ASR exposes an enable checkbox, Train button, threshold and status. Train
records independent EEG; BSL/EYC never fit the model. All channels are kept and
corrected. Threshold edits are debounced and reuse the training recording. See
`../docs/EEG_ASR.md` for processing behavior.
