"""Compact, per-source conversion editor; conversion math lives outside Qt."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QDoubleSpinBox, QLineEdit

from .source_conversion import SourceConversion


class ConversionNumber(QDoubleSpinBox):
    def textFromValue(self, value):
        return self.locale().toString(value, 'g', 12)


class SourceConversionControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._settings = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel('Conversion')
        label.setMinimumWidth(92)
        row.addWidget(label)
        self.gain = self._number(1., 'Gain', row)
        self.offset = self._number(0., 'Offset', row)
        row.addWidget(QLabel('Unit'))
        self.output_unit = QLineEdit()
        self.output_unit.setPlaceholderText('Source unit')
        self.output_unit.setMinimumWidth(75)
        self.output_unit.setToolTip('Converted output unit, e.g. µS. Blank keeps source metadata.')
        row.addWidget(self.output_unit, 1)
        self.setToolTip('Output = gain × source + offset. Applies before filtering, metrics and calibration. '
                        'Uses your sensor calibration; applies to all selected channels. Set before Play.')

    def _number(self, value, name, row):
        row.addWidget(QLabel(name))
        control = ConversionNumber()
        control.setRange(-1e12, 1e12)
        control.setDecimals(12)
        control.setValue(value)
        control.setMinimumWidth(90)
        control.setMaximumWidth(125)
        control.setAccessibleName(f'Source conversion {name.lower()}')
        row.addWidget(control)
        return control

    def conversion(self):
        return SourceConversion(self.gain.value(), self.offset.value(),
                                self.output_unit.text().strip())

    def set_source(self, identifier):
        if identifier == self._source:
            return
        if self._source is not None:
            self._settings[self._source] = self.conversion()
        self._source = identifier
        settings = self._settings.get(identifier, SourceConversion())
        self.gain.setValue(settings.gain)
        self.offset.setValue(settings.offset)
        self.output_unit.setText(settings.output_unit)
