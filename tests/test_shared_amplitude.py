import unittest
import numpy as np
from physiolab.display_units import eeg_display_scale, source_display_unit
from physiolab.raw_render import prepare_raw_window


class SharedAmplitudeTests(unittest.TestCase):
    def test_voltage_units_convert_to_one_physical_scale(self):
        scales, unit = eeg_display_scale(['V', 'mV', 'µV', 'microvolts'])
        np.testing.assert_allclose(scales, [20e-6, .02, 20., 20.])
        self.assertEqual(unit, 'µV')
        _, unit = eeg_display_scale(['', 'uV'])
        self.assertEqual(unit, 'a.u.')

    def test_source_units_are_preserved_and_missing_units_use_arbitrary_units(self):
        for units, expected in ((['microsiemens'], 'µS'), (['µS', 'uS'], 'µS'),
                                (['mV'], 'mV'), (['counts'], 'counts'),
                                ([''], 'a.u.'), ([None], 'a.u.'), ([], 'a.u.'),
                                (['µS', ''], 'a.u.')):
            self.assertEqual(source_display_unit(units), expected)

    def test_amplitude_ratios_survive_rendering_and_channel_count_changes(self):
        t = np.arange(256) / 256.
        wave = np.sin(2*np.pi*10*t)
        x = wave[:, None] * np.array([10., 40., 80.])
        chunk = (t, x, x*.5, ['F3', 'F4', 'Cz'], 256.)
        frame = prepare_raw_window([chunk], 0, 1, 0, max_channels=3, shared_scale=20.)
        ranges = np.ptp(frame[1], axis=0)
        np.testing.assert_allclose(ranges / ranges[0], [1., 4., 8.])
        smaller = prepare_raw_window([chunk], 0, 1, 0, max_channels=1, shared_scale=20.)
        np.testing.assert_allclose(frame[1][:, 0], smaller[1][:, 0])
        np.testing.assert_array_equal(chunk[1], x)

    def test_equal_voltage_in_different_source_units_has_equal_display_size(self):
        t = np.arange(256) / 256.
        wave = np.sin(2*np.pi*10*t)
        x = wave[:, None] * [20e-6, .02, 20.]
        scales, _ = eeg_display_scale(['V', 'mV', 'uV'])
        frame = prepare_raw_window([(t, x, x, ['a', 'b', 'c'], 256.)],
                                   0, 1, 0, max_channels=3, shared_scale=scales)
        np.testing.assert_allclose(np.ptp(frame[1], axis=0), [2., 2., 2.])
