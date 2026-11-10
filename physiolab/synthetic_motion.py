"""Deterministic ACC references and causal biosignal contamination for tests.

This controllable linear coupling is not a biomechanical model. Physiology
never feeds the ACC; all motion components are functions of time and seed.
"""
import numpy as np

LEVELS = {'none': 0., 'mild': .45, 'moderate': 1., 'strong': 1.8}
GRAVITY = 9.80665
ACC_SPECS = {
    'EEG': (64, ('AccX', 'AccY', 'AccZ')),
    'EDA': (32, ('AccX', 'AccY', 'AccZ')),
    'PPG': (64, ('AccX', 'AccY', 'AccZ')),
}
MOTION_ONSETS = {'EEG': 8., 'PPG': 11., 'EDA': 14.}


class SyntheticMotion:
    """Seeded analytic trajectories, independent of chunk size and call order."""
    def __init__(self, seed=2026, level='moderate'):
        if level not in LEVELS:
            raise ValueError('motion_level must be none, mild, moderate or strong')
        self.level, self.scale = level, LEVELS[level]
        rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(391,)))
        self.phases = {kind: rng.uniform(-np.pi, np.pi, (3, 2)) for kind in ACC_SPECS}

    @staticmethod
    def envelope(t, onset):
        age = np.asarray(t)-onset
        phase = np.mod(age, 36.)
        attack = .5-.5*np.cos(np.pi*np.clip(phase/2., 0., 1.))
        release = .5-.5*np.cos(np.pi*np.clip((18.-phase)/2., 0., 1.))
        return np.where(age >= 0., attack*release, 0.)

    def acceleration(self, kind, timestamps):
        """Three sensor axes in m/s², including static gravity on Z."""
        if kind not in ACC_SPECS:
            raise ValueError(f'Unknown synthetic ACC modality: {kind}')
        t = np.asarray(timestamps, dtype=float).reshape(-1)
        if not np.isfinite(t).all():
            raise ValueError('Synthetic ACC timestamps must be finite')
        p = self.phases[kind]
        body = np.column_stack((np.sin(2*np.pi*.83*t),
                                .7*np.cos(2*np.pi*1.13*t+.4),
                                .5*np.sin(2*np.pi*1.91*t+.2)))
        local = np.column_stack([
            np.sin(2*np.pi*f*t+p[axis, 0]) + .3*np.sin(2*np.pi*(f+1.37)*t+p[axis, 1])
            for axis, f in enumerate((1.67, 2.23, 2.81))])
        envelope = self.envelope(t, MOTION_ONSETS[kind])[:, None]
        dynamic = self.scale*envelope*(.65*body+.85*local)
        return dynamic + np.array([0., 0., GRAVITY])

    def sampled_reference(self, kind, timestamps, delay_samples=0):
        """Use only current/past samples of the same emitted ACC sequence."""
        rate = ACC_SPECS[kind][0]
        ticks = np.floor(np.asarray(timestamps)*rate)-delay_samples
        sampled = self.acceleration(kind, ticks/rate).astype(np.float32).astype(float)
        return sampled - np.array([0., 0., float(np.float32(GRAVITY))])

    def contamination(self, kind, timestamps, channels):
        """Causal FIR coupling; µV for EEG, µS for SC, a.u. for PPG.

        Delays of 0, 1 and 3 ACC samples and a slow gain variation exercise
        adaptive tracking. The publisher and this model share one time origin.
        """
        t = np.asarray(timestamps, dtype=float).reshape(-1)
        component = (.7*self.sampled_reference(kind, t)
                     + .22*self.sampled_reference(kind, t, 1)
                     - .12*self.sampled_reference(kind, t, 3))
        if kind == 'EEG':
            position = np.linspace(0., 2*np.pi, channels, endpoint=False)
            weights = np.vstack((14.+5*np.cos(position), 8*np.sin(position+.3),
                                 6*np.cos(position-.8)))
        elif kind == 'PPG':
            weights = np.array([[.65], [-.32], [.18]])
        elif kind == 'EDA':
            weights = np.array([[.22], [.12], [-.09]])
        else:
            raise ValueError(f'Unknown synthetic modality: {kind}')
        if weights.shape[1] != channels:
            raise ValueError('Motion contamination channel count does not match modality')
        gain = 1.+.12*np.sin(2*np.pi*t/61.+self.phases[kind][0, 0])
        return (component @ weights)*gain[:, None]
