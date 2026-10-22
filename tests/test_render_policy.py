"""Shared geometry matches waveform normalization, labels and time budgets."""
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import Mock

import numpy as np
from physiolab.render_policy import RAW_DISPLAY_POLICY, RawDisplayPolicy
from physiolab.vispy_raw import VisPyRawPlot


class RawDisplayPolicyTests(unittest.TestCase):
    def test_policy_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            RAW_DISPLAY_POLICY.max_points = 100

    def test_channel_centers_and_label_geometry_agree(self):
        for count in (1, 8, 32, 128):
            with self.subTest(count=count):
                policy = RAW_DISPLAY_POLICY
                lower, upper = policy.bounds(count)
                np.testing.assert_array_equal(policy.offsets(count), 6.*np.arange(count))
                self.assertEqual((lower, upper), (-3., 6.*count))
                self.assertEqual(policy.span(count), 6.*count+3.)
                expected = (6.*np.arange(count)+3.)/(6.*count+3.)
                np.testing.assert_allclose(policy.normalized_centers(count), expected)
                np.testing.assert_allclose(
                    [policy.label_fraction(i, count) for i in range(count)], expected)

    def test_empty_geometry_is_finite(self):
        self.assertEqual(RAW_DISPLAY_POLICY.bounds(0), (-3., 3.))
        self.assertEqual(RAW_DISPLAY_POLICY.span(0), 6.)
        self.assertEqual(len(RAW_DISPLAY_POLICY.normalized_centers(0)), 0)

    def test_display_rate_matches_full_history_decimation(self):
        for fs, duration in ((250., 5.), (512., 5.), (2048., 30.), (10., .5)):
            with self.subTest(fs=fs, duration=duration):
                stride = max(1, int(np.ceil(fs*2.*duration/2500)))
                self.assertEqual(RAW_DISPLAY_POLICY.display_rate(fs, duration), fs/stride)

    def test_custom_budget_and_cycle_count_control_display_rate(self):
        policy = RawDisplayPolicy(history_cycles=3, max_points=1000)
        self.assertEqual(policy.display_rate(1000., 2.), 1000./6)
        self.assertEqual(policy.display_rate(1000., 2., max_points=2000), 1000./3)
        self.assertEqual(policy.decimation_stride(1000., 2., 2000), 1)

    def test_shared_active_pending_and_pooled_layers_close_once(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        shared, pending = Mock(), Mock()
        plot._layer_pool = {'raw': [shared], 'filtered': []}
        plot.layers = {'raw': [shared], 'filtered': []}
        plot._pending_layers = {'raw': [shared, pending], 'filtered': []}
        plot._drop_layers()
        shared.close.assert_called_once_with()
        pending.close.assert_called_once_with()
        self.assertFalse(plot.configured)
        self.assertEqual(plot.channel_count, 0)
        self.assertEqual(plot.latest_sample_time, -np.inf)

    def test_public_render_state_and_replay_contract(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot._configuration = (8, 5., 250.)
        plot._target_channels = 8
        plot._latest = 12.5
        plot._pending_layers = None
        self.assertTrue(plot.configured)
        self.assertEqual(plot.channel_count, 8)
        self.assertEqual(plot.latest_sample_time, 12.5)
        self.assertFalse(plot.history_needs_replay(8, 5.))
        self.assertTrue(plot.history_needs_replay(16, 5.))
        self.assertTrue(plot.history_needs_replay(8, 10.))
        plot._pending_layers = {'raw': [], 'filtered': []}
        self.assertTrue(plot.history_needs_replay(8, 5.))


if __name__ == '__main__':
    unittest.main()
