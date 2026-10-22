import unittest
from unittest.mock import patch

import numpy as np

from physiolab.physiological_metrics import MetricCalculator, METRIC_CALCULATORS
from physiolab.processing import Processor


class MetricCalculatorTests(unittest.TestCase):
    def test_registered_long_window_is_retained_and_supplied(self):
        calculator = MetricCalculator(30., lambda window, *_: {'count': len(window)})
        with patch.dict(METRIC_CALCULATORS, {'EDA': calculator}):
            processor = Processor('EDA', 10., 1, ['EDA'])
            processor.push(np.ones((400, 1)))
            self.assertEqual(processor.metrics()['count'], 300)
            self.assertEqual(len(processor.filtered), 300)

    def test_invalid_calculator_declarations_fail_immediately(self):
        for duration in (0., -1., float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                MetricCalculator(duration, lambda *_: {})
        with self.assertRaises(ValueError):
            MetricCalculator(1., None)
