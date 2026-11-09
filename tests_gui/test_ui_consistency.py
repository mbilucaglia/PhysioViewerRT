"""Shared controls retain identical semantics and symbols across tabs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton,QToolButton,QComboBox
from physiolab.gui import MainWindow
from physiolab.ui_icons import action_icon


class UiConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(MainWindow,'refresh',lambda self:None):
            self.window=MainWindow()
        # Exercise controls without requiring real EYC/BSL recording in this UI test.
        for page in (self.window.metrics_page,self.window.affect_page):
            self.window.tabs.setTabEnabled(self.window.tabs.indexOf(page),True)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def assertIcon(self,button,name):
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.icon().pixmap(16,16).toImage(),action_icon(name).pixmap(16,16).toImage())

    def test_expand_restore_icons_and_accessible_names_match_across_views(self):
        buttons=[self.window.raw_focus_buttons['EEG'],
                 self.window.affect_view.findChild(QPushButton,'circumplexExpand'),
                 self.window.findChild(QToolButton,'metricsTrendExpand'),
                 self.window.topography.expand]
        for button in buttons:
            self.assertEqual(button.text(),'')
            self.assertEqual(button.accessibleName(),'Expand')
            self.assertIcon(button,'expand')
            button.click()
            self.assertEqual(button.text(),'')
            self.assertEqual(button.accessibleName(),'Restore')
            self.assertIcon(button,'collapse')
            button.click()
            self.assertEqual(button.text(),'')
            self.assertEqual(button.accessibleName(),'Expand')
        self.assertFalse(self.window.metric_arrangement.panels['values'].isHidden())

    def test_move_and_center_actions_are_icon_only(self):
        moves = [self.window.findChild(QToolButton, name) for name in (
            'EEGMove', 'PPGMove', 'EDAMove', 'metricsTrendMove', 'metricsValuesMove',
            'circumplexMove', 'eiMove')]
        moves += [self.window.findChild(QToolButton, f'{kind}MetricMove')
                  for kind in ('EEG', 'EDA', 'PPG', 'EI')]
        moves.append(self.window.topography.move)
        for button in moves:
            self.assertEqual(button.text(), '')
            self.assertEqual(button.accessibleName(), 'Move')
            self.assertIcon(button, 'move')
        centers = [*self.window.raw_center_buttons.values(),
                   self.window.findChild(QToolButton, 'metricsYCenter')]
        for button in centers:
            self.assertEqual(button.text(), '')
            self.assertEqual(button.accessibleName(), 'Center')
            self.assertIcon(button, 'center')

    def test_play_pause_symbols_and_captions_match_across_views(self):
        for button in [self.window.findChild(QPushButton,'rawPlotPause'),
                       self.window.findChild(QPushButton,'metricsPlotPause'),
                       self.window.affect_view.pause]:
            self.assertEqual(button.text(),'Pause')
            self.assertIcon(button,'pause')
            button.click()
            self.assertEqual(button.text(),'Play')
            self.assertIcon(button,'play')
            button.click()
            self.assertEqual(button.text(),'Pause')

    def test_calibration_action_matches_mode_and_has_distinct_symbols(self):
        for kind in ('EYC','BSL'):
            mode=self.window.findChild(QComboBox,kind+'Mode')
            button=self.window.findChild(QPushButton,kind+'Execute')
            for index,(caption,icon) in enumerate([('Record','record'),('Load','open'),('Clear','clear')]):
                mode.setCurrentIndex(index)
                self.assertEqual(button.text(),caption)
                self.assertIcon(button,icon)
        self.assertIcon(self.window.affect_view.clear,'clear')
        self.assertIcon(self.window.affect_view.fit_range,'autoscale')

    def test_metric_move_restores_both_expanded_panes(self):
        button=self.window.findChild(QToolButton,'metricsTrendExpand')
        button.click()
        self.assertTrue(self.window.metric_arrangement.panels['values'].isHidden())
        self.window.metric_arrangement.swap('trends','values')
        self.assertIsNone(self.window.metric_panel_focus)
        self.assertTrue(all(not pane.isHidden() for pane in self.window.metric_arrangement.panels.values()))
        self.assertEqual(button.text(),'')
        self.assertEqual(button.accessibleName(),'Expand')


    def test_metrics_vertical_controls_fit_and_zoom_without_changing_history(self):
        import numpy as np
        window=self.window
        history=window.metric_state.history
        key=('EEG','AWI')
        window.metric_renderer_choice.setCurrentIndex(0)
        origin=window.metric_plot_origin
        window.metric_state.history[key].extend([(origin,0.),(origin+1.,5.),(origin+2.,10.)])
        window.metric_controller.follow_live=False
        window.metric_controller.manual_view(0.,2.)
        window.refresh_metric_plot()
        window.findChild(QToolButton,'metricsYFit').click()
        bounds=window.metric_plot.viewRange()[1]
        self.assertLess(bounds[0],0.)
        self.assertGreater(bounds[1],10.)
        self.assertFalse(window.metric_y_auto.isChecked())
        window.findChild(QToolButton,'metricsYIn').click()
        zoomed=window.metric_plot.viewRange()[1]
        self.assertAlmostEqual(zoomed[1]-zoomed[0],.8*(bounds[1]-bounds[0]))
        window.metric_controller.set_y_range(20., 24.)
        center = window.findChild(QToolButton, 'metricsYCenter')
        center.click()
        self.assertIcon(center, 'center')
        zoomed = window.metric_plot.viewRange()[1]
        np.testing.assert_allclose(zoomed, (3., 7.))
        self.assertIs(window.metric_state.history,history)
        self.assertIcon(window.findChild(QToolButton,'metricsYFit'),'autoscale')
        window.metric_renderer_choice.setCurrentIndex(1)
        np.testing.assert_allclose(window.vispy_metric_plot.y_range,zoomed)
        window.metric_renderer_choice.setCurrentIndex(0)
        np.testing.assert_allclose(window.metric_plot.viewRange()[1],zoomed)

    def test_time_zoom_plus_means_more_detail_in_both_tabs(self):
        window=self.window
        for scope,combo,before,getter in [
            ('raw',window.raw_time_window,window.raw_display.view_seconds,lambda:window.raw_display.view_seconds),
            ('metrics',window.metric_time_window,window.metric_view_seconds,lambda:window.metric_view_seconds)]:
            window.findChild(QPushButton,scope+'ZoomPlus').click()
            self.assertLess(getter(),before)
            self.assertAlmostEqual(float(combo.currentData()),getter())
            window.findChild(QPushButton,scope+'ZoomMinus').click()
            self.assertAlmostEqual(getter(),before)
