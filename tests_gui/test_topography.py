import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QCheckBox, QToolButton

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
        self.assertIn('spline extrapolation', self.view.status.text())
        checkbox.setChecked(False)
        local = self.wait_map()
        self.assertFalse(local['extrapolated'].any())
        self.assertIn('spherical spline', self.view.status.text())
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
        self.assertFalse(self.view.persistence.isEnabled())
        self.assertAlmostEqual(self.view.settings().hop, 1.)
        self.view.overlap.setValue(75.)
        self.assertAlmostEqual(self.view.settings().hop, .5)

    def test_designer_colour_controls_adjust_paused_image_without_recomputing(self):
        for name, control in (('Minus', self.view.colour_minus),
                              ('Fit', self.view.colour_fit), ('Plus', self.view.colour_plus)):
            self.assertIs(control, self.window._required_ui('topographyColour'+name, QToolButton))
            self.assertFalse(control.isEnabled())
        self.assertIs(self.view.colour_auto, self.window._required_ui('topographyColourAuto', QCheckBox))
        self.window.set_plot_paused('raw', True)
        result = self.wait_map()
        grid = result['grid'].copy()
        initial = tuple(self.view.colorbar.levels())
        self.assertTrue(self.view.colour_auto.isChecked())
        revision = self.view._revision
        self.view.colour_plus.click()
        self.assertFalse(self.view.colour_auto.isChecked())
        np.testing.assert_allclose(self.view.colorbar.levels(), (0., initial[1]/self.window.settings.gain_step))
        np.testing.assert_allclose(self.view.image.getLevels(), self.view.colorbar.levels())
        self.view.colour_minus.click()
        np.testing.assert_allclose(self.view.colorbar.levels(), initial)
        self.assertIs(self.view.result, result)
        self.assertEqual(self.view._revision, revision)
        np.testing.assert_array_equal(result['grid'], grid)

    def test_manual_colour_range_survives_frames_and_pause_fit_and_auto_work(self):
        result = self.wait_map()
        self.view.colour_plus.click()
        frozen = tuple(self.view.colorbar.levels())
        changed = dict(result, grid=result['grid']*4., values=result['values']*4.,
                       levels=(0., result['levels'][1]*4.))
        self.view.present(changed, self.view.settings(), self.state.origin, False)
        np.testing.assert_allclose(self.view.colorbar.levels(), frozen)
        self.view.colour_fit.click()
        self.assertFalse(self.view.colour_auto.isChecked())
        np.testing.assert_allclose(self.view.colorbar.levels(), changed['levels'])
        self.view.present(result, self.view.settings(), self.state.origin, False)
        np.testing.assert_allclose(self.view.colorbar.levels(), changed['levels'])
        self.view.colour_auto.setChecked(True)
        np.testing.assert_allclose(self.view.colorbar.levels(), result['levels'])
        self.view.colour_auto.setChecked(False)
        held = tuple(self.view.colorbar.levels())
        self.window.set_plot_paused('raw', True)
        self.wait_map()
        np.testing.assert_allclose(self.view.colorbar.levels(), held)

    def test_colour_range_reseeds_on_quantity_and_source_change_and_voltage_is_symmetric(self):
        self.wait_map()
        self.view.colour_plus.click()
        self.view.band.setCurrentText('Unfiltered')
        voltage = self.wait_map()
        np.testing.assert_allclose(self.view.colorbar.levels(), voltage['levels'])
        self.view.colour_plus.click()
        low, high = self.view.colorbar.levels()
        self.assertEqual(low, -high)
        self.assertAlmostEqual(high, voltage['levels'][1]/self.window.settings.gain_step)
        self.window.reset_stream_display('EEG')
        self.assertFalse(self.view.colour_plus.isEnabled())
        self.samples(20., 4.)
        new_source = self.wait_map()
        np.testing.assert_allclose(self.view.colorbar.levels(), new_source['levels'])


if __name__ == '__main__':
    unittest.main()
