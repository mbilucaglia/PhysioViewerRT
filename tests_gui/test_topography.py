import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QHBoxLayout

from physiolab.gui import MainWindow
from physiolab.eeg_montage import COORDINATES_MM


class TopographyGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            self.window = MainWindow()
        self.window.timer.stop()
        self.window.show()
        self.window.tabs.setCurrentWidget(self.window.raw_page)
        self.window.set_raw_focus('TOPO', True)
        self.app.processEvents()
        self.view = self.window.topography
        self.state = self.window.raw_display
        self.samples(0., 4.)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def samples(self, start, duration):
        t = 100. + start + np.arange(int(duration*256)) / 256.
        x = np.sin(2*np.pi*10*t[:, None])*np.arange(1, 6)[None, :]
        self.window.append_raw_chunk('EEG', x, 2*x, ['F3','F4','P3','P4','Cz'], 256., t)
        if not self.state.paused:
            self.state.source_bounds['EEG'] = (t[-1]-100.-5., t[-1]-100.)

    def wait_map(self, predicate=lambda result: result is not None):
        deadline = time.monotonic() + 5.
        while time.monotonic() < deadline:
            self.view.tick(self.state)
            self.app.processEvents()
            if predicate(self.view.result):
                return self.view.result
            time.sleep(.01)
        self.fail(self.view.status.text())

    def test_map_pause_controls_resume_and_reset(self):
        result = self.wait_map()
        self.assertEqual(len(result['values']), 5)
        self.assertEqual(self.window.eeg_display_count.value(), 1)
        self.window.set_plot_paused('raw', True)
        frozen = self.wait_map()
        self.samples(4., 3.)
        self.view.tick(self.state)
        self.assertEqual(self.view.result['end'], frozen['end'])
        self.view.band.setCurrentText('Unfiltered')
        self.view.persistence.setValue(.3)
        raw = self.wait_map()
        self.assertEqual(raw['end'], frozen['end'])
        self.assertFalse(self.view.source.isEnabled())
        self.assertTrue(self.view.persistence.isEnabled())
        self.window.set_plot_paused('raw', False)
        self.state.source_bounds['EEG'] = (2., 6.99)
        resumed = self.wait_map(lambda r: r is not None and r['end'] > frozen['end'])
        self.assertGreater(resumed['end'], frozen['end'])
        self.window.reset_stream_display('EEG')
        self.assertIsNone(self.view.result)
        self.assertIn('Waiting', self.view.status.text())

    def test_inflight_result_is_discarded_after_source_reset(self):
        self.view.tick(self.state)
        self.assertIsNotNone(self.view._future)
        self.window.reset_stream_display('EEG')
        self.samples(20., 4.)
        result = self.wait_map()
        self.assertGreater(result['end'], 120.)

    def test_dense_cap_keeps_available_circles_without_text_labels(self):
        self.window.reset_stream_display('EEG')
        names = tuple(COORDINATES_MM)
        t = 100. + np.arange(1024)/256.
        x = np.sin(2*np.pi*10*t[:, None])*np.arange(1, 344)[None, :]
        self.window.append_raw_chunk('EEG', x, x, names, 256., t)
        self.state.source_bounds['EEG'] = (-1., t[-1]-100.)
        result = self.wait_map()
        self.assertEqual(len(result['labels']), 339)
        self.assertIn('FFC3h', result['labels'])
        circles = self.view.sensors
        self.view.present(result, self.view.settings(), self.state.origin, False)
        self.assertIs(self.view.sensors, circles)
        self.assertEqual(len(circles.points()), 339)
        self.assertEqual({point.data() for point in circles.points()}, set(result['labels']))
        self.assertFalse(any(isinstance(item, pg.TextItem) for item in self.view.plot.getPlotItem().items))
        self.assertIn('Standard 10-5', self.view.status.toolTip())

    def test_designer_extrapolation_toggle_recomputes_frozen_map_and_clears_circles(self):
        checkbox = self.window._required_ui('topographyExtrapolate', QCheckBox)
        self.assertIs(checkbox, self.view.extrapolate)
        self.assertTrue(checkbox.isChecked())
        self.window.set_plot_paused('raw', True)
        full = self.wait_map()
        self.assertTrue(full['extrapolated'].any())
        self.assertEqual(len(self.view.sensors.points()), 5)
        self.assertFalse(self.view.status.isVisible())
        checkbox.setChecked(False)
        local = self.wait_map()
        self.assertFalse(local['extrapolated'].any())
        self.assertFalse(self.view.status.isVisible())
        self.assertEqual(local['end'], full['end'])
        np.testing.assert_array_equal(local['values'], full['values'])
        self.assertLess(np.isfinite(local['grid']).sum(), np.isfinite(full['grid']).sum())
        checkbox.setChecked(True)
        self.wait_map()
        self.assertEqual(len(self.view.sensors.points()), 5)
        self.window.reset_stream_display('EEG')
        self.assertEqual(len(self.view.sensors.points()), 0)
        self.assertIsNone(self.view.result)

    def test_manual_history_position_and_band_controls(self):
        result = self.wait_map()
        self.state.follow_live = False
        self.state.source_bounds['EEG'] = (-2.5, 2.5)
        old = self.wait_map(lambda r: r is not None and r['end'] < result['end'])
        self.assertLessEqual(old['end'], 102.5)
        self.view.band.setCurrentText('Beta')
        beta = self.wait_map()
        self.assertLess(beta['values'].max(), .002)
        self.assertTrue(self.view.persistence.isEnabled())
        self.assertEqual(self.view.settings().window, 1.)
        self.assertEqual(self.view.settings().overlap, .5)
        self.assertAlmostEqual(self.view.settings().hop, .5)

    def test_every_map_is_minmax_normalized_with_matching_colourbar(self):
        self.assertIsNone(self.view.findChild(QCheckBox, 'topographyNormalize'))
        self.assertIsNone(self.view.findChild(QComboBox, 'topographyNormalizationMode'))
        header = self.view.designer_ui.findChild(QHBoxLayout, 'topographyHeaderLayout')
        ordered = [self.view.move, self.view.expand, self.view.colour_minus,
                   self.view.colour_fit, self.view.colour_plus, self.view.colour_auto]
        self.assertEqual([header.indexOf(widget) for widget in ordered],
                         sorted(header.indexOf(widget) for widget in ordered))
        self.window.set_plot_paused('raw', True)
        for band in ('Alpha', 'Unfiltered'):
            self.view.band.setCurrentText(band)
            result = self.wait_map()
            self.assertEqual(result['normalization'], 'minmax')
            self.assertEqual(result['levels'], (0., 1.))
            self.assertAlmostEqual(float(result['values'].min()), 0.)
            self.assertAlmostEqual(float(result['values'].max()), 1.)
            self.assertEqual(self.view.colorbar.levels(), (0., 1.))
            np.testing.assert_allclose(self.view.image.getLevels(), (0., 1.))
            color_map = self.view.image.getColorMap()
            self.assertIsNotNone(color_map)
            lut = color_map.getLookupTable(nPts=2)
            self.assertFalse(np.array_equal(lut[0], lut[-1]))
            finite = result['grid'][np.isfinite(result['grid'])]
            self.assertGreaterEqual(float(finite.min()), 0.)
            self.assertLessEqual(float(finite.max()), 1.)

        self.assertEqual(self.view.colour_minus.text(), '')
        self.assertFalse(self.view.colour_minus.icon().isNull())
        self.assertEqual(self.view.move.text(), '')
        self.assertEqual(self.view.move.accessibleName(), 'Move')
        self.assertEqual(self.view.expand.text(), '')
        self.assertEqual(self.view.expand.accessibleName(), 'Expand')
        self.assertEqual(self.view.colour_fit.text(), '')
        self.assertFalse(self.view.colour_fit.icon().isNull())
        self.assertEqual(self.view.colour_plus.text(), '')
        self.assertFalse(self.view.colour_plus.icon().isNull())
        self.view.colour_auto.setChecked(False)
        self.view.colour_plus.click()
        np.testing.assert_allclose(self.view.colorbar.levels(), (0., 1./self.window.settings.gain_step))
        np.testing.assert_allclose(self.view.image.getLevels(), self.view.colorbar.levels())
        self.view.colour_fit.click()
        np.testing.assert_allclose(self.view.colorbar.levels(), (0., 1.))
        self.view.colour_auto.setChecked(True)


if __name__ == '__main__':
    unittest.main()
