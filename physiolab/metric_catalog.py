"""Metric presentation contract, independent of Qt and signal algorithms.

Add a definition here and return its name in the modality's Processor output.
Histories, selectors, readouts, normalization and GPU layers follow the catalog.
IAF is a calibration parameter, not a plotted physiological metric.
"""
from dataclasses import dataclass
from colorsys import hsv_to_rgb
from numbers import Integral


@dataclass(frozen=True)
class MetricDefinition:
    modality: str
    name: str
    description: str = ''
    unit: str = ''
    asynchronous: bool = False

    @property
    def key(self):
        return self.modality, self.name


DEFAULT_METRICS = (
    MetricDefinition('EEG', 'AWI', 'Frontal alpha asymmetry'),
    MetricDefinition('EEG', 'BAR', 'Beta / alpha power ratio'),
    MetricDefinition('EDA', 'SCL', 'Tonic skin conductance from cvxEDA decomposition',
                     'source units', asynchronous=True),
    MetricDefinition('PPG', 'HR', 'Heart rate', 'bpm'),
    MetricDefinition('EI', 'EI', 'Baseline referenced emotional index'),
)
METRIC_PALETTE = ('#e69f00', '#56b4e9', '#009e73', '#cc79a7', '#d55e00')


def validate_metrics(definitions):
    definitions = tuple(definitions)
    for item in definitions:
        if not isinstance(item, MetricDefinition):
            raise ValueError('Metrics must be MetricDefinition instances')
        if (not isinstance(item.modality, str)
                or item.modality not in ('EEG', 'EDA', 'PPG', 'EI')
                or not isinstance(item.name, str) or not item.name.strip()):
            raise ValueError('Metrics need a supported modality and a nonempty name')
    keys = [item.key for item in definitions]
    if len(keys) != len(set(keys)):
        raise ValueError('Metric keys must be unique within each modality')
    return definitions


def metric_color(index):
    """Stable shared colors, extended deterministically beyond the base palette."""
    if isinstance(index, bool) or not isinstance(index, Integral) or index < 0:
        raise ValueError('Metric color index must be a nonnegative integer')
    if index < len(METRIC_PALETTE):
        return METRIC_PALETTE[index]
    rgb = hsv_to_rgb((index * .61803398875) % 1., .65, .75)
    return '#' + ''.join(f'{round(value * 255):02x}' for value in rgb)
