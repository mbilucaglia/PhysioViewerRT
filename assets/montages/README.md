# Standard 10-5 electrode template

`standard_1005.elc` is an unmodified copy of the ASA coordinate file distributed
by **MNE-Python v1.10.2**. It contains 343 channel labels plus three fiducials
(LPA, RPA, Nz). It includes the coarser 10-10/10-20 sites, intermediate 10-5
positions (including `h` suffixes), and legacy temporal/reference labels.

- Data: https://raw.githubusercontent.com/mne-tools/mne-python/v1.10.2/mne/channels/data/montages/standard_1005.elc
- Release documentation: https://mne.tools/1.10/generated/mne.channels.make_standard_montage.html
- SHA-256: `1ee59197946d62de872db2ac7f2243a596662c231427366f6dc5d84ed237f853`
- License: BSD-3-Clause; the unmodified upstream notice is in `MNE-LICENSE.txt`.
- License source: https://raw.githubusercontent.com/mne-tools/mne-python/v1.10.2/LICENSE.txt

These are standard template coordinates in millimetres, not digitized positions
from the current participant. The MNE package is not required at runtime.

## Projection used by PhysioViewerRT

`physiolab/eeg_montage.py` retains all original 3D coordinates. It builds a head
frame from the fiducials: right along LPA→RPA, anterior toward Nz, and superior
along the cross product. A single sphere center is fitted by linear least squares
to the complete scalp template in that frame, excluding duplicate temporal aliases
and M1/M2/A1/A2 reference sites from the fit. Those sites remain available for
plotting. Both source coordinates and map targets use this same fitted origin.
A top-down azimuthal equidistant projection uses polar angle
from the superior axis as radial distance, and head-frame azimuth as direction.
The subject's left is plot-left and the nose is up. Below-equator electrodes
remain distinct; a simple x/y projection would fold them toward upper sites.

A single scale computed from the **complete template** fits every projected
position inside radius 0.98. The circular outline encloses that full projected
extent, including inferior/reference sites; it is not an anatomical equator or
a measured head boundary. Selecting a subset never moves or rescales electrodes.
This projection is implemented locally and does not claim pixel equivalence to
MNE's `plot_topomap`.
The inverse projection maps every pixel back to the same 3D unit sphere for
spherical-spline evaluation; it round-trips all electrode directions.

T3/T4/T5/T6 resolve to T7/T8/P7/P8. If both names for one location are present,
the later channel is excluded and reported, preventing duplicate interpolation
nodes. Fiducials are never treated as EEG channels. Unknown labels and bipolar
derivations are never assigned guessed coordinates.
