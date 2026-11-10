"""Portable NPZ persistence; schema 2 adds captured input-stage NLMS output."""
import json
import os
import tempfile
from datetime import datetime, timezone

import numpy as np
from .calibration_validation import DURATION_SECONDS, validate_calibration
from .motion_recording import recorded_input, motion_configuration

def save_calibration(path, kind, streams, analysis):
    """Persist NPZ data, replacing the destination only after writing.

    A same-directory temporary file protects an existing calibration against
    write failures. Replacement is the commit point; this is not a guarantee
    of power-loss durability or equivalent behavior on network filesystems.
    """
    if kind not in ('EYC', 'BSL'):
        raise ValueError('Unknown calibration type.')
    meta = {
        'schema': 2 if any(item.get('motion_reference') for item in streams.values()) else 1,
        'type': kind, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'duration_requested_s': DURATION_SECONDS, 'streams': {},
        'analysis': analysis,
    }
    arrays = {}
    for modality, item in streams.items():
        if modality not in ('EEG', 'EDA', 'PPG'):
            continue
        data = np.asarray(item['data'], dtype=float)
        stamp = np.asarray(item['timestamps'], dtype=float)
        if data.ndim != 2 or len(data) != len(stamp) or not len(data) or not np.isfinite(data).all() or not np.isfinite(stamp).all():
            raise ValueError(f'Invalid capture for {modality}')
        arrays[f'{modality}_data'] = data
        arrays[f'{modality}_timestamps'] = stamp
        meta['streams'][modality] = {'fs': float(item['fs']), 'channels': list(item['channels']),
                                     'preprocessing': dict(item.get('preprocessing') or {}),
                                     'conversion': dict(item.get('conversion') or {}),
                                     'source_units': list(item.get('source_units') or []),
                                     'units': list(item.get('units') or []),
                                     'samples': int(len(data)),
                                     'recorded_span_s': float(stamp[-1]-stamp[0])}
        if item.get('motion_reference') is not None:
            arrays[f'{modality}_motion_cleaned'] = recorded_input(item)
            meta['streams'][modality]['motion_reference'] = motion_configuration(item['motion_reference'])
    if kind == 'EYC' and 'EEG' not in meta['streams']:
        raise ValueError('EYC EEG stream missing')
    if not meta['streams']:
        raise ValueError('No streams collected')
    arrays['metadata'] = np.array(json.dumps(meta))
    destination = os.path.abspath(os.fsdecode(path))
    temporary = None
    try:
        # Close before replace: Windows cannot replace an open temporary file.
        with tempfile.NamedTemporaryFile(mode='wb', dir=os.path.dirname(destination),
                                         prefix='.calibration-', suffix='.tmp',
                                         delete=False) as fh:
            temporary = fh.name
            np.savez_compressed(fh, **arrays)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, destination)
    except BaseException as exc:
        # Also clean up interrupted writes without masking the original error.
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                exc.add_note(f'Could not remove temporary calibration {temporary}: {cleanup_error}')
        raise


def load_calibration(path, expected_kind):
    with np.load(path, allow_pickle=False) as fh:
        if 'metadata' not in fh:
            raise ValueError('Calibration metadata is missing')
        meta = json.loads(str(fh['metadata'].item()))
        if (not isinstance(meta, dict) or meta.get('schema') not in (1, 2)
                or meta.get('type') != expected_kind):
            raise ValueError('Unexpected calibration type/schema')
        if not isinstance(meta.get('streams'), dict):
            raise ValueError('Calibration streams are missing')
        streams = {}
        for modality, descriptor in meta['streams'].items():
            if (modality not in ('EEG', 'EDA', 'PPG') or not isinstance(descriptor, dict)
                    or 'fs' not in descriptor or 'channels' not in descriptor):
                raise ValueError(f'Invalid stream descriptor: {modality}')
            if f'{modality}_data' not in fh or f'{modality}_timestamps' not in fh:
                raise ValueError(f'Missing signal arrays for {modality}')
            data = np.array(fh[f'{modality}_data'], dtype=float)
            stamps = np.array(fh[f'{modality}_timestamps'], dtype=float)
            streams[modality] = {'data': data, 'timestamps': stamps,
                                 'fs': descriptor['fs'], 'channels': descriptor['channels'],
                                 'preprocessing': descriptor.get('preprocessing', {}),
                                 'conversion': descriptor.get('conversion', {}),
                                 'source_units': descriptor.get('source_units', []),
                                 'units': descriptor.get('units', [])}
            if descriptor.get('motion_reference') is not None:
                key = f'{modality}_motion_cleaned'
                if key not in fh:
                    raise ValueError(f'{modality}: post-NLMS samples missing from calibration')
                streams[modality]['motion_reference'] = descriptor['motion_reference']
                streams[modality]['motion_cleaned'] = np.array(fh[key], dtype=float)
    validate_calibration(meta, streams, expected_kind)
    return meta, streams
