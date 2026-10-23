"""Presentation contracts for affect gaps, missing markers and view freezing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from physiolab.affect_state import AffectPoint, AffectResponse, AffectSnapshot
from physiolab.affect_widgets import AffectView, trajectory_geometry


def response(points=(), current=None, key='central'):
    return AffectResponse(key, key.title(), '#138d90', tuple(points), current, 'Awaiting data')


class AffectWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = AffectView()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_gaps_break_trajectories_and_fading_does_not_add_samples(self):
        first = AffectPoint(8., -1., 0., (8., 8.))
        after_gap = AffectPoint(9., 0., 1., (9., 9.), False)
        newest = AffectPoint(10., 1., 0., (10., 10.), True)
        series = response((first, after_gap, newest), newest)
        positions, colors = trajectory_geometry(series, 10., 60., True)
        self.assertEqual(positions.tolist(), [[0., 1.], [1., 0.]])
        later, faded = trajectory_geometry(series, 11., 60., True)
        self.assertEqual(later.tolist(), positions.tolist())
        self.assertLess(float(faded[-1, 3]), float(colors[-1, 3]))

    def test_pause_freezes_age_and_geometry_but_resume_uses_latest_snapshot(self):
        first = AffectPoint(10., 1., 0., (10., 10.))
        self.view.update_snapshot(AffectSnapshot((response((first,), first),)), [(10., .2)], 10.)
        self.view.pause.setChecked(True)
        next_point = AffectPoint(11., 2., 1., (11., 11.), True)
        self.view.update_snapshot(AffectSnapshot((response((first, next_point), next_point),)), [(11., -.3)], 11.)
        self.assertIs(self.view.plane.responses[0].current, first)
        self.assertEqual(self.view.ei_plot.current, .2)
        self.view.pause.setChecked(False)
        self.assertIs(self.view.plane.responses[0].current, next_point)
        self.assertEqual(self.view.ei_plot.current, -.3)

    def test_missing_response_has_no_marker_but_available_ei_is_held(self):
        self.view.update_snapshot(AffectSnapshot((response(),)), [(1., .4)], 10.)
        self.assertIsNone(self.view.plane.responses[0].current)
        self.assertEqual(self.view.ei_plot.current, .4)
        self.view.update_snapshot(AffectSnapshot((response(),)), [(1.,.4)], 100.)
        self.assertEqual(self.view.ei_plot.current, .4)
        self.view.update_snapshot(AffectSnapshot((response(),)), [(1.,.4),(2.,float('nan'))], 100.)
        self.assertIsNone(self.view.ei_plot.current)

        self.assertIn('Awaiting', self.view.readouts['central'].text())

    def test_missing_peripheral_source_hides_ei_and_clears_paused_peripheral_only(self):
        central = AffectPoint(10., 1., 0., (10.,10.))
        peripheral = AffectPoint(10., -.5, .2, (10.,10.))
        snapshot = AffectSnapshot((response((central,),central),
                                   response((peripheral,),peripheral,key='peripheral')))
        self.view.update_snapshot(snapshot, [(10.,.3)], 10.)
        self.view._expand('ei')
        self.view.pause.setChecked(True)
        self.view.set_peripheral_available(False)
        self.assertTrue(self.view.ei_card.isHidden())
        self.assertFalse(self.view.circumplex_card.isHidden())
        self.assertIsNone(self.view.ei_plot.current)
        self.assertFalse(self.view.ei_plot.points)
        self.assertEqual([r.key for r in self.view.plane.responses], ['central'])
        self.assertIs(self.view.plane.responses[0].current, central)
        self.view.update_snapshot(snapshot, [(10.,.3)], 10.)
        self.view.pause.setChecked(False)
        self.assertEqual([r.key for r in self.view.plane.responses], ['central'])
        self.view.set_peripheral_available(True)
        self.assertFalse(self.view.ei_card.isHidden())
        self.view.update_snapshot(snapshot, [(10.,.3)], 10.)
        self.assertEqual(len(self.view.plane.responses), 2)
        self.assertEqual(self.view.ei_plot.current, .3)

    def test_clear_immediately_removes_paused_geometry_and_preserves_pause(self):
        point = AffectPoint(10., 1., 0., (10., 10.))
        self.view.update_snapshot(AffectSnapshot((response((point,), point),)), [(10., .2)], 10.)
        self.view.pause.setChecked(True)
        clears = []
        self.view.clear_requested.connect(lambda: clears.append(True))
        self.view.clear.click()
        self.assertTrue(self.view.pause.isChecked())
        self.assertEqual(self.view.plane.responses, ())
        self.assertEqual(self.view.ei_plot.points, ())
        self.assertIsNone(self.view.ei_plot.current)
        self.assertEqual(clears, [True])
        self.view.pause.setChecked(False)
        self.assertEqual(self.view.plane.responses, ())

    def test_manual_range_survives_ticks_and_fit_retains_manual_mode(self):
        point = AffectPoint(10., 1., 0., (10., 10.))
        self.view.update_snapshot(AffectSnapshot((response((point,), point),)), (), 10.)
        self.view.zoom_in.click()
        manual = self.view.plane.extent
        self.assertFalse(self.view.auto_range.isChecked())
        outlier = AffectPoint(11., 10., 8., (11., 11.), True)
        self.view.update_snapshot(AffectSnapshot((response((point, outlier), outlier),)), (), 11.)
        self.assertEqual(self.view.plane.extent, manual)
        self.view.fit_range.click()
        self.assertGreater(self.view.plane.extent, 10.)
        self.assertFalse(self.view.auto_range.isChecked())
        self.view.auto_range.setChecked(True)
        self.assertTrue(self.view.plane.auto_range)

    def test_native_scene_keeps_visuals_on_updates_and_expand(self):
        if QApplication.platformName() in ('offscreen', 'minimal'):
            self.skipTest('Native OpenGL smoke check requires QT_QPA_PLATFORM=windows')
        self.view.resize(1100, 650)
        self.view.show()
        self.app.processEvents()
        self.assertIsNotNone(self.view.plane.canvas)
        identities = {key: tuple(id(node) for node in value)
                      for key, value in self.view.plane.layers.items()}
        point = AffectPoint(10., 3.5, -2., (10., 10.))
        self.view.update_snapshot(AffectSnapshot((response((point,), point),)), [(10., .2)], 10.)
        self.view._expand('circumplex')
        self.app.processEvents()
        self.view._expand('circumplex')
        self.app.processEvents()
        self.assertGreater(self.view.plane.extent, 3.5)
        self.assertTrue(self.view.plane.layers['central'][1].visible)
        self.assertFalse(self.view.plane.layers['peripheral'][1].visible)
        self.assertEqual(identities, {key: tuple(id(node) for node in value)
                                      for key, value in self.view.plane.layers.items()})

    def test_native_mouse_camera_zoom_stays_manual_and_clear_hides_all_nodes(self):
        if QApplication.platformName() in ('offscreen', 'minimal'):
            self.skipTest('Native camera check requires QT_QPA_PLATFORM=windows')
        self.view.resize(1100, 650)
        self.view.show()
        self.app.processEvents()
        plane = self.view.plane
        point = AffectPoint(10., 1., 0., (10., 10.))
        snapshot = AffectSnapshot((response((point,), point),))
        self.view.update_snapshot(snapshot, [(10., .2)], 10.)
        plane.view.camera.zoom(.5)
        plane.view.camera.pan(.3, -.2)
        self.app.processEvents()
        manual = plane.view.camera.get_state()
        self.assertFalse(self.view.auto_range.isChecked())
        self.view.update_snapshot(snapshot, [(10., .2)], 10.5)
        self.assertEqual(plane.view.camera.get_state(), manual)
        left, right, bottom, top = plane.display_bounds
        self.assertIn(f'{left:+.1f}…{right:+.1f}', self.view.range_label.text())
        self.assertIn(f'{bottom:+.1f}…{top:+.1f}', self.view.range_label.text())
        self.view.pause.setChecked(True)
        self.view.clear.click()
        self.assertTrue(self.view.pause.isChecked())
        self.assertTrue(all(not node.visible for pair in plane.layers.values() for node in pair))


if __name__ == '__main__':
    unittest.main()
