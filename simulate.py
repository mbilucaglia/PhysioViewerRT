"""Publish realistic-looking but synthetic 32-channel EEG, EDA and PPG via LSL.

Run: python simulate.py
Synthetic data exercise UI/processing and are not a physiological validation.
"""
import argparse
import time
from pylsl import StreamInfo, StreamOutlet, local_clock
from physiolab.synthetic import SPECS, SyntheticPhysiology


def start_outlets():
    outlets = {}
    for kind, (fs, names) in SPECS.items():
        info = StreamInfo(
            'Simulated' + kind, kind, len(names), fs,
            'float32', 'physiolab_sim_' + kind,
        )
        channel_list = info.desc().append_child('channels')
        for label in names:
            channel = channel_list.append_child('channel')
            channel.append_child_value('label', label)
            channel.append_child_value(
                'unit', 'microvolts' if kind == 'EEG'
                else 'microsiemens' if kind == 'EDA' else 'a.u.'
            )
            channel.append_child_value('type', kind)
        outlets[kind] = StreamOutlet(info)
    return outlets


def run(seed=2026, artifacts='moderate'):
    model = SyntheticPhysiology(seed=seed, artifact_level=artifacts)
    outlets = start_outlets()
    ticks = {kind: 0 for kind in SPECS}
    t0 = local_clock()
    print('Simulated 32-channel EEG (256 Hz), EDA (32 Hz) and PPG (128 Hz).')
    print('Signals have evolving EEG rhythms, skin conductance responses and')
    print(f'beat-to-beat heart-rate variation. Artifacts: {artifacts}. Ctrl+C to stop.')
    try:
        while True:
            elapsed = local_clock() - t0
            for kind, (fs, _) in SPECS.items():
                target = int(elapsed * fs)
                count = target - ticks[kind]
                if count <= 0:
                    continue
                data = model.generate(kind, ticks[kind], count)
                # pylsl's chunk timestamp denotes the LAST sample; preceding
                # samples are backdated by the nominal sampling interval.
                last_sample_time = t0 + (target - 1) / fs
                outlets[kind].push_chunk(data.tolist(), last_sample_time)
                ticks[kind] = target
            time.sleep(.02)
    except KeyboardInterrupt:
        print('Stopped synthetic LSL streams.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Synthetic LSL physiology')
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--artifacts',
                        choices=('none', 'mild', 'moderate', 'strong'),
                        default='moderate',
                        help='Intermittent artifact intensity')
    args = parser.parse_args()
    run(seed=args.seed, artifacts=args.artifacts)

