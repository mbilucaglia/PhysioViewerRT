import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock

specs = [
    ('EEG', 256, ['F3', 'F4', 'C3', 'C4', 'O1', 'O2']),
    ('EDA', 32, ['EDA']),
    ('PPG', 128, ['PPG']),
]
outlets = []
for kind, fs, names in specs:
    info = StreamInfo('Simulated' + kind, kind, len(names), fs, 'float32',
                      'physiolab_sim_' + kind)
    channels = info.desc().append_child('channels')
    for name in names:
        channels.append_child('channel').append_child_value('label', name)
    outlets.append((kind, fs, StreamOutlet(info), names))

print('Publishing simulated EEG, EDA, PPG. Ctrl+C to stop.')
t0 = local_clock()
ticks = {kind: 0 for kind, _, _, _ in outlets}
try:
    while True:
        elapsed = local_clock() - t0
        for kind, fs, outlet, names in outlets:
            target = int(elapsed * fs)
            count = target - ticks[kind]
            if count <= 0:
                continue
            t = np.arange(ticks[kind], target) / fs
            if kind == 'EEG':
                x = np.stack([
                    20 * np.sin(2 * np.pi * 10 * t + i * .3)
                    + 3 * np.sin(2 * np.pi * 3 * t)
                    for i in range(len(names))
                ], axis=1)
            elif kind == 'EDA':
                x = (4 + .3 * np.sin(2 * np.pi * .07 * t))[:, None]
            else:
                phase = (t * 1.2) % 1
                x = (np.exp(-((phase - .17) / .07) ** 2)
                     + .2 * np.exp(-((phase - .4) / .1) ** 2))[:, None]
            outlet.push_chunk(x.astype('float32').tolist(), t0 + ticks[kind] / fs)
            ticks[kind] = target
        time.sleep(.02)
except KeyboardInterrupt:
    pass
