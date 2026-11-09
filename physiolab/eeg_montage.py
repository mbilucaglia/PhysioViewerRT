"""Full standard 10-5 template and fixed sensor-independent scalp projection.

The bundled ASA file is from MNE-Python v1.10.2 (BSD-3-Clause); see
assets/montages/README.md for provenance, checksum and projection conventions.
No runtime MNE dependency or network access is required.
"""
from pathlib import Path
import re
from types import MappingProxyType

import numpy as np


MONTAGE_PATH = Path(__file__).resolve().parent.parent / 'assets' / 'montages' / 'standard_1005.elc'
MONTAGE_NAME = 'Standard 10-5 (343 labels)'
ALIASES = {'t3': 't7', 't4': 't8', 't5': 'p7', 't6': 'p8'}


def read_standard_montage(path=MONTAGE_PATH):
    """Read original millimetre coordinates, excluding the three fiducials."""
    lines = [line.strip() for line in Path(path).read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
    if 'UnitPosition\tmm' not in lines and 'UnitPosition mm' not in lines:
        raise ValueError('Standard montage coordinates must be in millimetres')
    count = int(next(line.split('=')[1] for line in lines if line.startswith('NumberPositions=')))
    start, stop = lines.index('Positions') + 1, lines.index('Labels')
    xyz = np.asarray([list(map(float, line.split())) for line in lines[start:stop]])
    labels = lines[stop + 1:]
    if (xyz.shape != (count, 3) or len(labels) != count or not np.isfinite(xyz).all()
            or len({name.lower() for name in labels}) != count):
        raise ValueError('Invalid standard montage coordinates or labels')
    coordinates = dict(zip(labels, map(tuple, xyz)))
    fiducials = {name: coordinates.pop(name) for name in ('LPA', 'RPA', 'Nz')}
    return coordinates, fiducials


def _sphere_geometry(coordinates, fiducials):
    """Fit one sphere to the full scalp template in fiducial-aligned axes."""
    left, right, nose = (np.asarray(fiducials[k], dtype=float) for k in ('LPA', 'RPA', 'Nz'))
    x_axis = right - left
    x_axis /= np.linalg.norm(x_axis)
    origin = left + np.dot(nose-left, x_axis)*x_axis
    y_axis = nose - origin
    y_axis /= np.linalg.norm(y_axis)
    z_axis = np.cross(x_axis, y_axis)
    xyz = (np.asarray(list(coordinates.values())) - origin) @ np.stack((x_axis, y_axis, z_axis), axis=1)
    scalp = np.asarray([name.lower() not in (*ALIASES, 'm1', 'm2', 'a1', 'a2')
                        for name in coordinates])
    fit = xyz[scalp]
    design = np.column_stack((2*fit, np.ones(len(fit))))
    center = np.linalg.lstsq(design, np.sum(fit**2, axis=1), rcond=None)[0][:3]
    xyz = xyz - center
    directions = xyz / np.linalg.norm(xyz, axis=1, keepdims=True)
    return directions


def project_montage(coordinates, fiducials):
    """Fixed azimuthal projection about the full-template fitted sphere center.

    +x is subject right, +y anterior, +z superior. Every selected subset shares
    the same origin/scale. Inferior sites remain distinct and inside radius .98.
    """
    xyz = _sphere_geometry(coordinates, fiducials)
    horizontal = np.linalg.norm(xyz[:, :2], axis=1)
    angle = np.arctan2(horizontal, xyz[:, 2])
    direction = np.divide(xyz[:, :2], horizontal[:, None],
                          out=np.zeros_like(xyz[:, :2]), where=horizontal[:, None] > 1e-12)
    projected = direction * (angle * (.98 / angle.max()))[:, None]
    return dict(zip((name.lower() for name in coordinates), map(tuple, projected)))


_coordinates, _fiducials = read_standard_montage()
COORDINATES_MM = MappingProxyType(_coordinates)
FIDUCIALS_MM = MappingProxyType(_fiducials)
POSITIONS = MappingProxyType(project_montage(COORDINATES_MM, FIDUCIALS_MM))
_directions = _sphere_geometry(COORDINATES_MM, FIDUCIALS_MM)
SPHERE_DIRECTIONS = MappingProxyType(dict(zip(
    (name.lower() for name in COORDINATES_MM), map(tuple, _directions))))
PROJECTION_SCALE = .98 / np.arctan2(np.linalg.norm(_directions[:, :2], axis=1),
                                   _directions[:, 2]).max()


def scalp_display_order(labels):
    """Return backend order so traces read top-down anterior-to-posterior.

    Trace index zero is drawn at the bottom, so backend order is posterior to
    anterior and right-to-left within each approximate scalp row. On screen,
    the visible order is therefore anterior-to-posterior and left-to-right.
    Unknown labels keep their input order at the bottom of the view. This only
    affects presentation; source data and processing channel indices are intact.
    """
    positioned, unpositioned = [], []
    for index, raw_label in enumerate(labels):
        label = re.sub(r'^eeg\s+', '', str(raw_label).strip(), flags=re.I).lower()
        label = re.sub(r'[-_](ref|le|re|avg)$', '', label)
        label = ALIASES.get(label, label)
        xy = POSITIONS.get(label)
        if xy is None:
            unpositioned.append(index)
        else:
            x, y = float(xy[0]), float(xy[1])
            # Fixed horizontal bands keep the order stable when the user
            # changes the selected subset of electrodes.
            row = int(round(y / .08))
            positioned.append((index, x, row))

    # Index zero is drawn at the bottom: posterior rows first; within each
    # row, right-to-left so the visible top-down order reads left-to-right.
    positioned.sort(key=lambda item: (item[2], -item[1], item[0]))
    ordered = [item[0] for item in positioned]
    return tuple((*unpositioned, *ordered))


def unproject_positions(xy):
    """Invert the displayed map into unit vectors on the SAME fitted sphere."""
    xy = np.asarray(xy, dtype=float)
    radius = np.linalg.norm(xy, axis=1)
    angle = radius / PROJECTION_SCALE
    direction = np.divide(xy, radius[:, None], out=np.zeros_like(xy),
                          where=radius[:, None] > 1e-12)
    return np.column_stack((direction * np.sin(angle)[:, None], np.cos(angle)))
