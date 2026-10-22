"""Presentation contracts remain usable as the metric count grows."""
import re
import unittest
from dataclasses import FrozenInstanceError

from physiolab.metric_catalog import (
    DEFAULT_METRICS, METRIC_PALETTE, MetricDefinition, metric_color,
    validate_metrics,
)


class MetricCatalogTests(unittest.TestCase):
    def test_defaults_have_unique_qualified_keys_and_exclude_calibration(self):
        definitions = validate_metrics(DEFAULT_METRICS)
        self.assertEqual(len({item.key for item in definitions}), len(definitions))
        self.assertNotIn(('EEG', 'IAF'), {item.key for item in definitions})

    def test_same_name_can_belong_to_different_modalities(self):
        definitions = [MetricDefinition('EEG', 'Quality'),
                       MetricDefinition('PPG', 'Quality')]
        self.assertEqual(validate_metrics(iter(definitions)), tuple(definitions))

    def test_duplicate_key_is_rejected_even_if_description_differs(self):
        with self.assertRaises(ValueError):
            validate_metrics([MetricDefinition('EEG', 'Quality', 'First'),
                              MetricDefinition('EEG', 'Quality', 'Second')])

    def test_invalid_modality_or_empty_name_is_rejected(self):
        for definition in (MetricDefinition('ECG', 'HR'), MetricDefinition('EEG', ''),
                           MetricDefinition('EEG', '  '), MetricDefinition('EEG', 2),
                           MetricDefinition([], 'HR'), {'modality': 'EEG', 'name': 'HR'}):
            with self.subTest(definition=definition), self.assertRaises(ValueError):
                validate_metrics([definition])

    def test_catalog_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_METRICS[0].name = 'Changed'

    def test_additional_metrics_have_stable_distinct_valid_colors(self):
        colors = [metric_color(index) for index in range(40)]
        self.assertEqual(colors[:len(METRIC_PALETTE)], list(METRIC_PALETTE))
        self.assertEqual(len(set(colors)), len(colors))
        self.assertTrue(all(re.fullmatch(r'#[0-9a-f]{6}', color) for color in colors))
        self.assertEqual(colors, [metric_color(index) for index in range(40)])

    def test_invalid_color_indices_fail_at_the_contract_boundary(self):
        for index in (-1, 1.5, True, '1'):
            with self.subTest(index=index), self.assertRaises(ValueError):
                metric_color(index)


if __name__ == '__main__':
    unittest.main()
