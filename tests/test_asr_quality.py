import unittest
from types import SimpleNamespace
from physiolab.asr_quality import training_report


class TrainingReportTests(unittest.TestCase):
    def test_retention_uses_duration_not_channel_count_or_cutoff(self):
        model = SimpleNamespace(baseline_seconds=45., clean_seconds=36.,
            settings=SimpleNamespace(minimum_baseline_seconds=30., cutoff=20.),
            channels=('F3','F4','O1','O2'), fs=128.)
        report = training_report(model)
        self.assertEqual(report['retained'], '36.0 s (80.0%)')
        self.assertEqual(report['excluded'], '9.0 s (20.0%)')
        self.assertEqual(report['minimum'], '30 s required — met')
        model.settings.minimum_baseline_seconds = 40.
        self.assertEqual(training_report(model)['minimum'], '40 s required — not met')
        model.clean_seconds = 45.
        self.assertEqual(training_report(model)['excluded'], '0.0 s (0.0%)')
