"""Integration checks against the installed cvxEDA optimizer."""
from dataclasses import replace
from importlib.metadata import version
import unittest
from unittest.mock import patch

import numpy as np

from physiolab.sc_decomposition import (
    SCDecompositionSettings, TonicSCProcessor, decompose_baseline,
)


class TonicSCProcessorTests(unittest.TestCase):
    def test_first_normal_update_uses_available_history_without_excluding_latest_edge(self):
        processor = TonicSCProcessor()
        # A 20-second maximum context must not impose a 20-second startup.
        self.assertEqual(processor.push(self.values[:31], self.times[:31], self.fs), [])
        observations = processor.push(self.values[31:32], self.times[31:32], self.fs)
        self.assertEqual(len(observations), 1)
        first = observations[0]
        self.assertEqual(first.window_end, self.times[31])
        self.assertEqual(first.available_time, first.window_end)
        self.assertGreater(first.window_end, first.window_start)
        self.assertEqual(processor.settings.edge_seconds, 0.)
        self.assertIn('ready', processor.status)

    def setUp(self):
        self.fs = 32.
        self.times = np.arange(int(26 * self.fs)) / self.fs
        self.values = 4 + .002 * self.times + .15 * np.maximum(0, np.sin(self.times * .5)) ** 6
        if not TonicSCProcessor().available:
            self.skipTest('Install requirements-affect.txt for optimizer integration tests')

    def test_restores_physical_units_under_affine_conversion(self):
        original = decompose_baseline(self.values, self.times, self.fs, unit='uS')
        converted = decompose_baseline(self.values * 3 + 7, self.times, self.fs, unit='mS')
        self.assertEqual(len(original), 26)
        np.testing.assert_allclose([o.value * 3 + 7 for o in original],
                                   [o.value for o in converted], rtol=1e-6)
        self.assertTrue(all(o.unit == 'mS' for o in converted))

    def test_streaming_and_baseline_use_identical_windows_and_settings(self):
        expected = decompose_baseline(self.values, self.times, self.fs)
        processor = TonicSCProcessor()
        actual = []
        for start in range(0, len(self.times), 13):
            actual.extend(processor.push(self.values[start:start + 13], self.times[start:start + 13], self.fs))
        self.assertEqual(expected, actual)
        self.assertLessEqual(len(processor._times), int(21 * self.fs))
        self.assertTrue(all(o.window_end == o.available_time for o in actual))
        self.assertTrue(all(o.available_time - o.timestamp <= .5 for o in actual))

    def test_constant_source_preserves_absolute_level(self):
        output = decompose_baseline(np.full(len(self.times), 8.), self.times, self.fs)
        np.testing.assert_allclose([o.value for o in output], 8., atol=1e-12)

    def test_gap_restarts_history_instead_of_bridging_dropouts(self):
        processor = TonicSCProcessor()
        self.assertEqual(len(processor.push(self.values, self.times, self.fs)), 26)
        self.assertEqual(len(processor.push(self.values[:32], self.times[:32] + 100, self.fs)), 1)
        self.assertEqual(len(processor.push(self.values[32:64], self.times[32:64] + 100, self.fs)), 1)
        self.assertEqual(processor._next_end, 102.96875)

    def test_invalid_values_and_backwards_time_restart_history(self):
        processor = TonicSCProcessor()
        processor.push(self.values, self.times, self.fs)
        self.assertEqual(processor.push([np.nan, 3., 3.], [26., 26.1, 26.2], self.fs), [])
        self.assertTrue(np.isfinite(processor._values).all())
        self.assertEqual(processor.push([3., 3.], [1., 1.03125], self.fs), [])

    def test_metadata_stable_and_changes_with_processing_settings(self):
        first, second = TonicSCProcessor(), TonicSCProcessor()
        self.assertEqual(first.metadata(), second.metadata())
        changed = TonicSCProcessor(replace(first.settings, edge_seconds=3.))
        self.assertNotEqual(first.pipeline_id, changed.pipeline_id)
        self.assertEqual(first.metadata()['library_version'], version('cvxeda'))

    def test_solver_failure_is_reported_without_interrupting_acquisition(self):
        processor = TonicSCProcessor()
        import cvxopt
        before = cvxopt.solvers.options.copy()
        def broken_backend(*args, **kwargs):
            cvxopt.solvers.options['show_progress'] = True
            raise RuntimeError('simulated optimizer failure')
        processor._backend = broken_backend
        self.assertEqual(processor.push(self.values, self.times, self.fs), [])
        self.assertIn('simulated optimizer failure', processor.status)
        self.assertEqual(cvxopt.solvers.options, before)

    def test_missing_optional_backend_keeps_stream_operational(self):
        real_import = __import__
        def importing(name, *args, **kwargs):
            if name == 'cvxeda':
                raise ImportError('missing dependency')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=importing):
            processor = TonicSCProcessor()
        self.assertFalse(processor.available)
        self.assertEqual(processor.push(self.values, self.times, self.fs), [])
        self.assertIn('unavailable', processor.status)

    def test_settings_validate_model_and_window(self):
        for settings in ({'window_seconds': .5}, {'edge_seconds': -1.}, {'analysis_hz': 1.},
                         {'tau0': .7}, {'hop_seconds': float('nan')}):
            with self.assertRaises(ValueError):
                SCDecompositionSettings(**settings)


if __name__ == '__main__':
    unittest.main()
