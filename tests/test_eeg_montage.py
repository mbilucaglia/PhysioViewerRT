import hashlib
import unittest
import numpy as np

from physiolab.eeg_montage import (MONTAGE_PATH, COORDINATES_MM, FIDUCIALS_MM,
                                   POSITIONS, project_montage, SPHERE_DIRECTIONS,
                                   unproject_positions)
from physiolab.topography import (electrode_key, calculate_topography,
                                  TopographySettings, interpolation_weights)


class StandardMontageTests(unittest.TestCase):
    def test_pinned_complete_data_and_fiducials(self):
        self.assertEqual(hashlib.sha256(MONTAGE_PATH.read_bytes()).hexdigest(),
                         '1ee59197946d62de872db2ac7f2243a596662c231427366f6dc5d84ed237f853')
        self.assertEqual(len(COORDINATES_MM), 343)
        self.assertEqual(len(POSITIONS), 343)
        self.assertEqual(set(FIDUCIALS_MM), {'LPA', 'RPA', 'Nz'})
        self.assertTrue(set(FIDUCIALS_MM).isdisjoint(COORDINATES_MM))
        np.testing.assert_allclose(COORDINATES_MM['Cz'], (.4009, -9.167, 100.244))
        for name in ('Fp1','Fp2','AF5','AF6','FC1','FC2','CP5','CP6','PO1','PO2',
                     'AFp1h','AFF3h','FFC3h','FCC1h','CCP2h','CPP4h','PPO5h',
                     'POO8h','OI1h','OIz','I1','I2','AF9','PO10','T10'):
            with self.subTest(name=name):
                self.assertIn(name.lower(), POSITIONS)
                self.assertIn(electrode_key('EEG '+name+'-REF'), POSITIONS)
        self.assertNotIn(electrode_key('LPA'), POSITIONS)
        self.assertNotIn(electrode_key('C3-C4'), POSITIONS)

    def test_projection_orientation_and_bounds(self):
        xy = np.asarray(list(POSITIONS.values()))
        self.assertTrue(np.isfinite(xy).all())
        self.assertAlmostEqual(np.linalg.norm(xy, axis=1).max(), .98)
        for left, right in (('fp1','fp2'), ('c3','c4'), ('po7','po8'),
                            ('ffc3h','ffc4h'), ('oi1h','oi2h')):
            self.assertLess(POSITIONS[left][0], 0.)
            self.assertGreater(POSITIONS[right][0], 0.)
        self.assertGreater(POSITIONS['fpz'][1], POSITIONS['cz'][1])
        self.assertGreater(POSITIONS['cz'][1], POSITIONS['oz'][1])
        self.assertLess(np.linalg.norm(POSITIONS['cz']), .1)
        # Inferior sites remain outward from their corresponding superior site.
        self.assertGreater(np.linalg.norm(POSITIONS['t9']), np.linalg.norm(POSITIONS['t7']))
        reordered = project_montage(dict(reversed(list(COORDINATES_MM.items()))), FIDUCIALS_MM)
        for name, position in POSITIONS.items():
            np.testing.assert_allclose(reordered[name], position)

    def test_dense_montage_and_channel_reordering_preserve_values_and_positions(self):
        names = tuple(COORDINATES_MM)
        t = np.arange(512)/256.
        signal = np.sin(2*np.pi*10*t[:, None])*np.arange(1, 344)[None, :]
        config = TopographySettings(source='raw')
        result = calculate_topography(((t, signal, signal, names, 256.),), t[-1], config)
        self.assertEqual(set(result['excluded']), {'T3', 'T4', 'T5', 'T6'})
        self.assertEqual(len(result['labels']), 339)
        self.assertTrue(np.isfinite(result['grid']).any())
        subset = ['FFC3h', 'CCP2h', 'AFp1h', 'POO8h', 'Cz']
        indices = [names.index(n) for n in subset]
        x = signal[:, indices]
        small = calculate_topography(((t, x, x, tuple(subset), 256.),), t[-1], config)
        for index, name in enumerate(subset):
            original = result['labels'].index(name)
            self.assertEqual(small['positions'][index], result['positions'][original])
            # Min-max display values depend on the available electrode set;
            # measured power and coordinates must survive subset/reordering.
            self.assertAlmostEqual(small['absolute_values'][index], result['absolute_values'][original])
        reverse = calculate_topography(((t, x[:, ::-1], x[:, ::-1], tuple(subset[::-1]), 256.),), t[-1], config)
        np.testing.assert_allclose(reverse['values'][::-1], small['values'])
        np.testing.assert_allclose(reverse['absolute_values'][::-1], small['absolute_values'])
        np.testing.assert_allclose(reverse['grid'], small['grid'], rtol=1e-6, equal_nan=True)

    def test_dense_interpolation_cache_is_bounded(self):
        positions = tuple(dict.fromkeys(POSITIONS.values()))
        weights, mask = interpolation_weights(positions)
        self.assertEqual(weights.dtype, np.float32)
        self.assertLess(weights.nbytes, 24*1024*1024)
        self.assertEqual(interpolation_weights.cache_info().maxsize, 2)
        np.testing.assert_allclose(weights.sum(axis=1), 1., atol=3e-6)
        self.assertTrue(mask.any())

    def test_map_inverse_uses_same_3d_sphere_as_electrodes(self):
        names = tuple(POSITIONS)
        reconstructed = unproject_positions([POSITIONS[name] for name in names])
        np.testing.assert_allclose(reconstructed, [SPHERE_DIRECTIONS[name] for name in names], atol=1e-12)


if __name__ == '__main__':
    unittest.main()
