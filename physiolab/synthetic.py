"""Reproducible, time-varying synthetic EEG, skin conductance and PPG.

Signals are useful for exercising the app; they are not recordings of people
and must not be used to validate physiological accuracy.
"""
import numpy as np
from scipy.signal import lfilter

EEG_LABELS = (
    'Fp1', 'Fp2', 'AF3', 'AF4', 'F7', 'F3', 'Fz', 'F4',
    'F8', 'FC5', 'FC1', 'FC2', 'FC6', 'T7', 'C3', 'Cz',
    'C4', 'T8', 'CP5', 'CP1', 'CP2', 'CP6', 'P7', 'P3',
    'Pz', 'P4', 'P8', 'PO3', 'PO4', 'O1', 'Oz', 'O2',
)

SPECS = {
    'EEG': (256, EEG_LABELS),
    'EDA': (32, ('SCL',)),
    'PPG': (128, ('PPG',)),
}


class SyntheticPhysiology:
    """Maintain independent stochastic processes for each source.

    The signal envelopes and events are functions of time. Each modality
    draws noise from its own seeded RNG, so requesting a different chunk
    size does not change the generated sample sequence.
    """

    def __init__(self, seed=2026, artifact_level='moderate'):
        if artifact_level not in ('none', 'mild', 'moderate', 'strong'):
            raise ValueError('artifact_level must be none, mild, moderate or strong')
        self.artifact_level = artifact_level
        self.artifact_scale = {'none': 0., 'mild': .45, 'moderate': 1., 'strong': 1.8}[artifact_level]
        streams = np.random.SeedSequence(seed).spawn(3)
        self.rng = {kind: np.random.default_rng(state)
                    for kind, state in zip(SPECS, streams)}
        self.eeg_noise_state = np.zeros((1, 33), dtype=float)
        self.last_end = {kind: 0 for kind in SPECS}
        self.eeg_alpha_gain = np.array(
            [0.75, 0.75, 0.85, 0.85, 0.75, 0.9, 0.8, 0.9,
             0.75, 0.85, 0.9, 0.9, 0.85, 0.8, 0.85, 0.85,
             0.85, 0.8, 0.95, 0.9, 0.9, 0.95, 1.65, 1.8,
             2.0, 1.8, 1.65, 2.0, 2.0, 2.5, 2.7, 2.5]
        )
        self.eeg_phase = np.linspace(0, 3.6, len(EEG_LABELS))

    @staticmethod
    def heart_rate(t):
        """Intended instantaneous BPM: varying autonomic + respiratory terms."""
        t = np.asarray(t)
        return (73. + 9. * np.sin(2*np.pi*t/47.)
                + 4. * np.sin(2*np.pi*t/113.)
                + 1.8 * np.sin(2*np.pi*t/5.5))

    def generate(self, kind, start, count):
        if kind not in SPECS:
            raise ValueError(f'Unknown synthetic modality: {kind}')
        if count < 0 or start != self.last_end[kind]:
            raise ValueError('Each synthetic stream must advance in time order')
        self.last_end[kind] += count
        fs, names = SPECS[kind]
        if count == 0:
            return np.empty((0, len(names)), dtype=np.float32)
        t = (start + np.arange(count, dtype=float)) / fs
        if kind == 'EEG':
            return self._eeg(t).astype(np.float32)
        if kind == 'EDA':
            return self._eda(t).astype(np.float32)[:, None]
        return self._ppg(t).astype(np.float32)[:, None]

    def _eeg(self, t):
        n = len(EEG_LABELS)
        p = self.eeg_phase[None, :]
        # Posterior alpha dominates the eyes-closed EYC spectrum. Frontal
        # hemispheric alpha amplitude varies slowly, so AWI is nonconstant.
        envelope = 10. * (1. + .24*np.sin(2*np.pi*t/29.))[:, None]
        gain = self.eeg_alpha_gain[None, :].copy()
        gain = np.broadcast_to(gain, (len(t), n)).copy()
        left, right = EEG_LABELS.index('F3'), EEG_LABELS.index('F4')
        gain[:, left] *= 1. + .28*np.sin(2*np.pi*t/34.)
        gain[:, right] *= 1. - .24*np.sin(2*np.pi*t/41.)
        alpha = envelope*gain*np.sin(
            2*np.pi*(10.1*t + .12*np.sin(2*np.pi*t/71.))[:, None] + p
        )
        beta_gain = (2.9 + 1.3*np.sin(2*np.pi*t/23. + .4))[:, None]
        beta = beta_gain*(1. + .18*np.cos(p))*np.sin(
            2*np.pi*20.3*t[:, None] + 1.7*p
        )
        theta = 3.5*np.sin(2*np.pi*5.7*t[:, None] + .6*p)
        slow = 1.8*np.sin(2*np.pi*1.8*t[:, None] + 1.3*p)
        mains = .9*np.sin(2*np.pi*50*t[:, None] + .2*p)

        # Continuously colored channel-specific noise plus a shared component.
        innovation = self.rng['EEG'].normal(size=(len(t), n+1))
        colored, self.eeg_noise_state = lfilter(
            [1.], [1., -.91], innovation, axis=0, zi=self.eeg_noise_state
        )
        noise = 1.1*colored[:, :n] + .6*colored[:, -1, None]
        # Smooth blink artifacts, strongest at frontopolar electrodes.
        blink_phase = np.mod(t - 8., 19.)
        blink = 35.*np.exp(-.5*((blink_phase - .25)/.17)**2)
        frontal_weights = np.array(
            [1.0 if name.startswith('Fp') else
             .55 if name.startswith(('AF', 'F')) else .08
             for name in EEG_LABELS]
        )
        # Broad-band jaw/forehead EMG: intermittent 30–90 Hz muscle bursts.
        # EEG channel offsets are smooth due to motion/electrode impedance.
        burst_times = np.mod(t - 12., 37.)
        emg_window = np.exp(-.5*((burst_times - .65)/.55)**2)
        emg_carrier = (8*np.sin(2*np.pi*36.7*t[:, None] + 2.1*p)
                       + 5*np.sin(2*np.pi*73.2*t[:, None] + .8*p))
        emg_weights = np.asarray([
            1.0 if label in ('F7', 'F8', 'T7', 'T8') else
            .7 if label.startswith(('Fp', 'AF', 'F')) else .18
            for label in EEG_LABELS
        ])
        # Electrode pops followed by decay, and slow contact drift on Fp1.
        pop_age = np.mod(t - 21., 83.)
        pop = np.where(pop_age < 4., 65*np.exp(-pop_age/1.2), 0.)
        drift = 14*np.sin(2*np.pi*t/48.) + .07*t/(1.+t/180.)
        artifacts = (blink[:, None]*frontal_weights[None, :]
                     + emg_window[:, None]*emg_carrier*emg_weights[None, :])
        artifacts[:, EEG_LABELS.index('Fp1')] += pop + drift
        artifacts[:, EEG_LABELS.index('T8')] += .65*pop
        return alpha + beta + theta + slow + mains + noise + (
            self.artifact_scale*artifacts
        )

    def _eda(self, t):
        # SCL in microsiemens: slow tonic drift, gradual session trends.
        baseline = 3.4 + .28*np.sin(2*np.pi*t/85.) + .004*t/(1.+t/300.)
        breathing = .027*np.sin(2*np.pi*t/5.4)
        # Sudomotor responses: rise ~1 s, recovery ~4 s; pulse amplitudes
        # and inter-response intervals vary instead of repeating identically.
        phasic = np.zeros(len(t), dtype=float)
        for idx in range(max(0, int((t[0]-15.)//12.)-2),
                         int((t[-1]-10.)//12.)+3):
            onset = 11. + 12.5*idx + 2.3*np.sin(1.31*idx)
            amp = .23 + .38*(.5+.5*np.sin(1.73*idx))
            delta = t - onset
            positive = np.maximum(delta, 0.)
            response = amp*(np.exp(-positive/4.5)
                            - np.exp(-positive/.65))
            phasic += np.where(delta >= 0, response, 0.)
        noise = self.rng['EDA'].normal(0, .006, len(t))
        # Contact changes produce abrupt downward steps and a slow recovery.
        # Short movement scratches add faster oscillations to the electrodes.
        contact_age = np.mod(t - 34., 78.)
        contact_dip = np.where(
            contact_age < 5., -.42*np.exp(-contact_age/2.5), 0.
        )
        scratch_age = np.mod(t - 27., 53.)
        scratch_window = np.exp(-.5*((scratch_age - .4)/.22)**2)
        scratch = .14*scratch_window*np.sin(2*np.pi*7.3*t)
        return np.maximum(
            .1, baseline + breathing + phasic + noise
            + self.artifact_scale*(contact_dip + scratch)
        )

    def _ppg(self, t):
        # Analytic integral of the time-varying heart rate, in cycles,
        # makes beat timing continuous even when chunks vary in size.
        phase = (
            73*t/60
            - (9*47/(120*np.pi))*np.cos(2*np.pi*t/47.)
            - (4*113/(120*np.pi))*np.cos(2*np.pi*t/113.)
            - (1.8*5.5/(120*np.pi))*np.cos(2*np.pi*t/5.5)
        ) % 1.
        # Sharp systolic pulse, smooth diastolic decay and dicrotic wave.
        # Circular phase distances avoid a discontinuity at each beat.
        def pulse(center, width):
            d = (phase - center + .5) % 1. - .5
            return np.exp(-.5*(d/width)**2)
        wave = (1.05*pulse(.16, .063)
                - .16*pulse(.31, .042)
                + .19*pulse(.42, .095))
        respiratory_amp = 1. + .13*np.sin(2*np.pi*t/4.9)
        slow_amp = 1. + .1*np.sin(2*np.pi*t/37.)
        baseline = .1 + .06*np.sin(2*np.pi*t/18.)
        noise = self.rng['PPG'].normal(0, .012, len(t))
        # Occasional gentle motion artifact with an independent time course.
        motion = .08*np.sin(2*np.pi*1.7*t)*np.maximum(
            0., np.sin(2*np.pi*t/57.)
        )**8
        # Sudden temporary poor optical contact attenuates pulses.
        # Hand/wrist movement induces large oscillatory baseline excursions.
        loss_age = np.mod(t - 39., 91.)
        loss_envelope = np.where(
            loss_age < 3.5, .22, 1.
        )
        movement_age = np.mod(t - 18., 43.)
        movement_window = np.exp(-.5*((movement_age - .65)/.9)**2)
        movement = movement_window * (
            .65*np.sin(2*np.pi*1.75*t) + .25*np.sin(2*np.pi*3.4*t)
        )
        loss_mix = 1. - self.artifact_scale*(1. - loss_envelope)
        loss_mix = np.clip(loss_mix, .03, 1.)
        return (baseline + respiratory_amp*slow_amp*wave*loss_mix
                + noise + self.artifact_scale*(motion + movement))
