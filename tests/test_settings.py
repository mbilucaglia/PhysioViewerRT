"""Viewer policy is validated before it reaches timers and bounded histories."""
import unittest
from dataclasses import FrozenInstanceError, fields, replace

from physiolab.settings import DEFAULT_VIEWER_SETTINGS, ViewerSettings


class ViewerSettingsTests(unittest.TestCase):
    def test_defaults_are_valid_and_immutable(self):
        self.assertEqual(DEFAULT_VIEWER_SETTINGS, ViewerSettings())
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_VIEWER_SETTINGS.display_fps = 60

    def test_every_numeric_policy_rejects_nonpositive_and_nonfinite_values(self):
        for field in fields(ViewerSettings):
            for value in (0, -1, float('nan'), float('inf'), -float('inf')):
                with self.subTest(field=field.name, value=value):
                    with self.assertRaises(ValueError):
                        replace(DEFAULT_VIEWER_SETTINGS, **{field.name: value})

    def test_view_cannot_exceed_retained_history(self):
        with self.assertRaises(ValueError):
            ViewerSettings(history_seconds=4, default_view_seconds=5)
        self.assertEqual(ViewerSettings(history_seconds=5).default_view_seconds, 5)

    def test_asr_training_requires_at_least_sixty_accepted_seconds(self):
        self.assertEqual(DEFAULT_VIEWER_SETTINGS.asr_training_seconds, 60.)
        for seconds in (30., 45., 59.):
            with self.assertRaises(ValueError):
                ViewerSettings(asr_training_seconds=seconds)

    def test_gain_range_is_ordered(self):
        for minimum, maximum in ((1, 1), (2, 1)):
            with self.assertRaises(ValueError):
                ViewerSettings(gain_minimum=minimum, gain_maximum=maximum)

    def test_timer_rounding_and_minimum_interval(self):
        for fps, expected in ((25, 40), (30, 33), (60, 17), (2000, 1)):
            self.assertEqual(ViewerSettings(display_fps=fps).timer_interval_ms, expected)

    def test_custom_policy_does_not_mutate_defaults(self):
        custom = replace(DEFAULT_VIEWER_SETTINGS, display_fps=60,
                         metric_history_capacity=1800)
        self.assertEqual(custom.display_fps, 60)
        self.assertEqual(DEFAULT_VIEWER_SETTINGS.display_fps, 30)

    def test_count_policies_require_integers(self):
        for name in ('display_fps', 'default_eeg_display_channels', 'metric_history_capacity', 'ingress_chunks_per_tick'):
            for value in (1.5, True, '30'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    replace(DEFAULT_VIEWER_SETTINGS, **{name: value})

    def test_gain_step_must_increase_gain(self):
        for value in (.5, 1):
            with self.assertRaises(ValueError):
                ViewerSettings(gain_step=value)


if __name__ == '__main__':
    unittest.main()
