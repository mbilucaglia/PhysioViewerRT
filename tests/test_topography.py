import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np

from physiolab.topography import (TopographySettings, calculate_topography,
                                  band_limits, electrode_key, SCALP_MASK, GRID_SIZE)


class TopographyTests(unittest.TestCase):
    def setUp(self):
        self.fs = 256.
        self.t = np.arange(1024) / self.fs
        self.names = ('F3', 'F4', 'P3', 'P4', 'Cz')
        self.config = TopographySettings(source='raw', window=2.)

    def chunks(self, data, processed=None, split=512, times=None, names=None):
        processed = data if processed is None else processed
        times = self.t if times is None else times
        return tuple((times[i:i+split], data[i:i+split], processed[i:i+split],
                      names or self.names, self.fs) for i in range(0, len(times), split))

    def test_band_power_preserves_spatial_amplitude_and_units(self):
        amplitudes = np.arange(1., 6.)
        x = np.sin(2*np.pi*10*self.t[:, None])*amplitudes
        result = calculate_topography(self.chunks(x), self.t[-1], self.config, scales=1e6, unit='µV')
        np.testing.assert_allclose(result['absolute_values'], amplitudes**2/2 * 1e12, rtol=.015)
        np.testing.assert_allclose(result['values'], [0., .125, 1/3, .625, 1.], rtol=.015)
        self.assertEqual(result['levels'], (0., 1.))
        self.assertTrue(np.isnan(result['grid'][0, 0]))
        self.assertIn('min–max normalized', result['quantity'])
        beta = calculate_topography(self.chunks(x), self.t[-1], replace(self.config, band='Beta'))
        self.assertLess(beta['absolute_values'].max(), .001)

    def test_iaf_and_source_selection(self):
        self.assertEqual(band_limits('Alpha', 9.), (7., 11.))
        self.assertEqual(band_limits('Alpha'), (8., 13.))
        self.assertEqual(band_limits('Theta', 9.), (3., 7.))
        self.assertEqual(band_limits('Theta', 9., use_iaf=False), (4., 8.))
        x = np.tile(np.sin(2*np.pi*12*self.t)[:, None], (1, 5))
        chunks = self.chunks(x, 2*x)
        canonical = calculate_topography(chunks, self.t[-1], self.config)
        shifted = calculate_topography(chunks, self.t[-1], self.config, iaf=9.)
        processed = calculate_topography(chunks, self.t[-1], replace(self.config, source='processed'))
        self.assertLess(shifted['absolute_values'].max(), .001)
        np.testing.assert_allclose(processed['absolute_values'], 4*canonical['absolute_values'])
        np.testing.assert_allclose(processed['values'], canonical['values'])
        fixed = calculate_topography(chunks, self.t[-1], replace(self.config, use_iaf=False), iaf=9.)
        np.testing.assert_allclose(fixed['values'], canonical['values'])
        np.testing.assert_allclose(fixed['absolute_values'], canonical['absolute_values'])

    def test_full_scalp_fills_only_head_and_marks_extrapolated_area(self):
        x = np.sin(2*np.pi*10*self.t[:, None])*np.arange(1., 6.)
        chunks = self.chunks(x)
        original = x.copy()
        full = calculate_topography(chunks, self.t[-1], self.config)
        local = calculate_topography(chunks, self.t[-1], replace(self.config, extrapolate=False))
        scalp = SCALP_MASK.reshape(GRID_SIZE, GRID_SIZE)
        covered = np.isfinite(local['grid'])
        np.testing.assert_array_equal(np.isfinite(full['grid']), scalp)
        np.testing.assert_array_equal(full['extrapolated'], scalp & ~covered)
        self.assertTrue(full['extrapolated'].any())
        self.assertFalse(local['extrapolated'].any())
        np.testing.assert_allclose(full['grid'][covered], local['grid'][covered])
        np.testing.assert_array_equal(full['values'], local['values'])
        np.testing.assert_array_equal(x, original)
        self.assertEqual(full['labels'], list(self.names))
        self.assertGreaterEqual(np.nanmin(full['grid']), 0.)
        self.assertLessEqual(np.nanmax(full['grid']), full['levels'][1])

    def test_full_scalp_constant_and_signed_voltage_have_finite_correct_scale(self):
        config = replace(self.config, band='Unfiltered', persistence=0.)
        for vector in (np.full(5, 3.5), np.array([-4., 2., -1., 5., 0.])):
            x = np.tile(vector, (len(self.t), 1))
            result = calculate_topography(self.chunks(x), self.t[-1], config)
            finite = result['grid'][np.isfinite(result['grid'])]
            self.assertTrue(np.isfinite(finite).all())
            self.assertGreaterEqual(finite.min(), result['levels'][0])
            self.assertLessEqual(finite.max(), result['levels'][1])
            np.testing.assert_array_equal(result['absolute_values'], vector)
            if np.ptp(vector) == 0:
                np.testing.assert_allclose(result['values'], .5)
                np.testing.assert_allclose(finite, .5)
            else:
                np.testing.assert_allclose(result['values'], [0., 2/3, 1/3, 1., 4/9])

    def test_normalized_power_map_is_bounded_unit_invariant_and_zero_safe(self):
        x = np.sin(2*np.pi*10*self.t[:, None])*np.arange(1., 6.)
        normal = calculate_topography(self.chunks(x), self.t[-1], self.config)
        converted = calculate_topography(self.chunks(x), self.t[-1], self.config, scales=1e6)
        np.testing.assert_allclose(converted['absolute_values'], normal['absolute_values']*1e12)
        np.testing.assert_allclose(converted['grid'], normal['grid'], rtol=1e-6, atol=1e-7, equal_nan=True)
        self.assertGreaterEqual(np.nanmin(normal['grid']), 0.)
        self.assertLessEqual(np.nanmax(normal['grid']), 1.)
        zero = calculate_topography(self.chunks(np.zeros_like(x)), self.t[-1], self.config)
        np.testing.assert_array_equal(zero['absolute_values'], 0.)
        np.testing.assert_array_equal(zero['grid'][np.isfinite(zero['grid'])], .5)

    def test_unfiltered_persistence_is_packet_independent_and_signed(self):
        x = np.zeros((1024, 5))
        x[-1] = [-1, -2, 0, 2, 1]
        config = replace(self.config, band='Unfiltered', persistence=0., source='processed')
        instant = calculate_topography(self.chunks(x, 100*x), self.t[-1], config)
        np.testing.assert_array_equal(instant['absolute_values'], x[-1])
        np.testing.assert_array_equal(instant['values'], [.25, 0., .5, 1., .75])
        config = replace(config, persistence=.2)
        a = calculate_topography(self.chunks(x, split=13), self.t[-1], config)
        b = calculate_topography(self.chunks(x, split=512), self.t[-1], config)
        np.testing.assert_allclose(a['values'], b['values'])
        np.testing.assert_allclose(a['absolute_values'], b['absolute_values'])
        self.assertLess(abs(a['absolute_values'][0]), .03)
        self.assertLess(a['absolute_values'][0], 0.)
        self.assertEqual(a['levels'], (0., 1.))
        # No future samples can leak into a historical map.
        earlier = calculate_topography(self.chunks(x), self.t[-2], config)
        np.testing.assert_array_equal(earlier['absolute_values'], 0.)
        np.testing.assert_array_equal(earlier['values'], .5)

    def test_channel_mapping_exclusions_and_degenerate_montage(self):
        self.assertEqual(electrode_key('EEG T3-REF'), 't7')
        x = np.ones((1024, 5))
        names = ('F3', 'F4', 'P3', 'F3-F4', 'Ch5')
        result = calculate_topography(self.chunks(x, names=names), self.t[-1], self.config)
        self.assertEqual(result['excluded'], ['F3-F4', 'Ch5'])
        x[:, 0] = np.nan
        with self.assertRaisesRegex(ValueError, 'recognized labels'):
            calculate_topography(self.chunks(x, names=names), self.t[-1], self.config)
        with patch('physiolab.topography.POSITIONS', dict(zip(
                ('c1','c2','c3','c4','cz'), ((-.5,0.),(.5,0.),(-1.,0.),(1.,0.),(0.,0.))))), \
                self.assertRaisesRegex(ValueError, 'non-collinear'):
            calculate_topography(self.chunks(np.ones((1024, 5)), names=('C1','C2','C3','C4','Cz')),
                                  self.t[-1], self.config)

    def test_gap_warmup_nyquist_and_settings_validation(self):
        x = np.ones((1024, 5))
        with self.assertRaisesRegex(ValueError, 'continuous EEG'):
            calculate_topography(self.chunks(x), .5, self.config)
        t = self.t.copy()
        t[800:] += 1.
        with self.assertRaisesRegex(ValueError, 'continuous EEG'):
            calculate_topography(self.chunks(x, times=t), t[-1], self.config)
        chunks = tuple((*c[:4], 64.) for c in self.chunks(x))
        with self.assertRaisesRegex(ValueError, 'sampling'):
            calculate_topography(chunks, self.t[-1], replace(self.config, band='Gamma'))
        with self.assertRaises(ValueError):
            TopographySettings(overlap=1.)
        self.assertAlmostEqual(replace(self.config, overlap=.75).hop, .5)


if __name__ == '__main__':
    unittest.main()
