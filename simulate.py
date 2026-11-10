"""Publish synthetic EEG/EDA/PPG and three associated ACC references via LSL.

Run: python simulate.py --artifacts none --motion strong
Synthetic data exercise UI/processing and are not a physiological validation.
"""
import argparse
import math
import time
from pylsl import StreamInfo, StreamOutlet, local_clock
from physiolab.synthetic import SPECS, SyntheticPhysiology
from physiolab.synthetic_motion import ACC_SPECS, LEVELS


def stream_specs():
    # Reference chunks precede primary chunks within a common time slice.
    return {**{kind+'_ACC': spec for kind, spec in ACC_SPECS.items()}, **SPECS}


def stream_infos(source_prefix='physiolab_sim_'):
    infos = {}
    for key, (fs, names) in stream_specs().items():
        acc = key.endswith('_ACC')
        kind = key[:-4] if acc else key
        info = StreamInfo('Simulated'+key, 'Accelerometer' if acc else kind,
                          len(names), fs, 'float32', source_prefix+key)
        desc = info.desc()
        desc.append_child_value('manufacturer', 'PhysioViewerRT synthetic generator')
        desc.append_child_value('associated_modality', kind)
        desc.append_child_value('simulation', 'true')
        desc.append_child_value('associated_source_id' if acc else 'motion_reference_source_id',
                                source_prefix+(kind if acc else kind+'_ACC'))
        channel_list = desc.append_child('channels')
        for label in names:
            channel = channel_list.append_child('channel')
            channel.append_child_value('label', label)
            channel.append_child_value(
                'unit', 'm/s^2' if acc else 'microvolts' if kind == 'EEG'
                else 'microsiemens' if kind == 'EDA' else 'a.u.'
            )
            channel.append_child_value('type', 'Accelerometer' if acc else kind)
        infos[key] = info
    return infos


def start_outlets(source_prefix='physiolab_sim_'):
    return {key: StreamOutlet(info) for key, info in stream_infos(source_prefix).items()}


def publish_until(model, outlets, ticks, origin, elapsed):
    """Advance all six streams on one source clock at their respective rates."""
    for key, (fs, _) in stream_specs().items():
        target = int(elapsed*fs)
        count = target-ticks[key]
        if count <= 0:
            continue
        data = (model.generate_acc(key[:-4], ticks[key], count) if key.endswith('_ACC')
                else model.generate(key, ticks[key], count))
        # pylsl backdates preceding samples from this LAST-sample timestamp.
        outlets[key].push_chunk(data.tolist(), origin+(target-1)/fs)
        ticks[key] = target


def run(seed=2026, artifacts='moderate', motion='moderate', seconds=None):
    if seconds is not None and (not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('seconds must be finite and positive')
    model = SyntheticPhysiology(seed=seed, artifact_level=artifacts, motion_level=motion)
    outlets = start_outlets()
    ticks = dict.fromkeys(stream_specs(), 0)
    origin = local_clock()
    print('Simulated EEG (32 ch, 256 Hz), EDA (32 Hz), PPG (128 Hz).', flush=True)
    print('ACC: SimulatedEEG_ACC (64 Hz), SimulatedPPG_ACC (64 Hz), '
          'SimulatedEDA_ACC (32 Hz); X/Y/Z in m/s^2.', flush=True)
    print(f'Other artifacts: {artifacts}. Coherent motion: {motion}. '
          'Motion starts at 8/11/14 s for EEG/PPG/EDA. Ctrl+C to stop.', flush=True)
    try:
        while True:
            elapsed = local_clock()-origin
            publish_until(model, outlets, ticks, origin,
                          min(elapsed, seconds) if seconds is not None else elapsed)
            if seconds is not None and elapsed >= seconds:
                break
            time.sleep(.02)
    except KeyboardInterrupt:
        pass
    finally:
        outlets.clear()
        print('Stopped synthetic LSL streams.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Synthetic LSL physiology and coherent ACC motion')
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--artifacts', choices=tuple(LEVELS), default='moderate',
                        help='Other artifacts: blinks, EMG and contact disturbances')
    parser.add_argument('--motion', choices=tuple(LEVELS), default='moderate',
                        help='ACC motion and coherent contamination (default: moderate)')
    parser.add_argument('--seconds', type=float, help='Stop automatically after this duration')
    args = parser.parse_args()
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error('--seconds must be finite and positive')
    run(seed=args.seed, artifacts=args.artifacts, motion=args.motion, seconds=args.seconds)


if __name__ == '__main__':
    main()

