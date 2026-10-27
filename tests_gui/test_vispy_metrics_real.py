"""Construct the real VisPy Metrics canvas in offscreen Qt.

Unlike the mock backend-switch tests, this catches API mismatches in
AxisWidget, ViewBox, GridLines, Line and Markers at initialization time.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_metrics import VisPyMetricPlot
from physiolab.vispy_raw import VisPyRawPlot
from physiolab.vispy_plot_engine import VisPyPlotEngine


class RealVisPyMetricsConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reserved_channels_commit_without_progressive_frame_roundtrips(self):
        from unittest.mock import patch
        plot = VisPyRawPlot('EEG')
        self.addCleanup(plot.close)
        # Native driver linking is exercised by the transition benchmark;
        # this lifecycle check also runs on CI without an OpenGL context.
        with patch.object(plot.canvas, 'render') as render:
            for count in range(1, 9):
                self.assertTrue(plot.warm_channels(8, 5., 64.))
                self.assertEqual(plot.reserved_channel_count, count)
                self.assertFalse(plot.configured)
            self.assertFalse(plot.warm_channels(8, 5., 64.))
            self.assertEqual(render.call_count, 8)
        programs = tuple(layer.visual.shared_program for layer in plot._layer_pool['raw'])
        times = np.arange(64) / 64.
        values = np.ones((64, 8)) + 6*np.arange(8)
        frame = (times, values, values, None, None, tuple(map(str, range(8))))
        plot.set_frame(frame, 0., 5., nominal_fs=64.)
        self.assertEqual(plot.channel_count, 8)
        self.assertIsNone(plot._pending_layers)
        plot.reset()
        self.assertFalse(plot.configured)
        self.assertEqual(plot.reserved_channel_count, 8)
        self.assertTrue(all(not layer.visual.visible for layer in plot._layer_pool['raw']))
        self.assertFalse(np.isfinite(plot.latest_sample_time))
        plot.set_frame(frame, 0., 5., nominal_fs=64.)
        self.assertEqual(programs, tuple(layer.visual.shared_program
                                        for layer in plot.layers['raw']))

    def test_warming_spare_channel_does_not_change_live_history_or_visibility(self):
        from unittest.mock import patch
        plot = VisPyRawPlot('EEG')
        self.addCleanup(plot.close)
        times = np.array([0., .1, .2])
        values = np.array([[0.], [1.], [0.]])
        plot.set_frame((times, values, values, None, None, ('F3',)), 0., 5.)
        layer = plot.layers['raw'][0]
        positions = layer.ring.positions.copy()
        with patch.object(plot.canvas, 'render'):
            self.assertTrue(plot.warm_channels(2, 5., 64.))
        self.assertIs(layer, plot.layers['raw'][0])
        self.assertTrue(layer.visual.visible)
        self.assertFalse(plot._layer_pool['raw'][1].visual.visible)
        np.testing.assert_array_equal(layer.ring.positions, positions)
        self.assertEqual(plot.channel_count, 1)

    def test_partial_upload_groups_unsorted_adjacent_slots_without_changing_endpoints(self):
        from unittest.mock import Mock
        plot = VisPyRawPlot('EEG')
        self.addCleanup(plot.close)
        times = np.array([0., .1])
        values = np.zeros((2, 1))
        plot.set_frame((times, values, values, None, None, ('F3',)), 0., 5.)
        visual = plot.layers['raw'][0].visual
        buffer = visual._buffer
        visual._buffer = Mock()
        try:
            updates = [(i, np.full((2, 2), i, dtype=np.float32)) for i in (5, 1, 2, 4)]
            visual.patch(updates)
            calls = visual._buffer.set_subdata.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual([call.kwargs['offset'] for call in calls], [2, 8])
            np.testing.assert_array_equal(calls[0].args[0][:, 0], [1, 1, 2, 2])
            np.testing.assert_array_equal(calls[1].args[0][:, 0], [4, 4, 5, 5])
        finally:
            visual._buffer = buffer

    def test_create_real_canvas_axes_and_update_metric_series(self):
        keys = (('EEG', 'AWI'), ('EEG', 'BAR'), ('EDA', 'SCL'),
                ('PPG', 'HR'), ('EI', 'EI'))
        plot = VisPyMetricPlot(keys)
        try:
            self.assertIsNotNone(plot.widget)
            self.assertEqual(len(plot.lines), 5)
            self.assertEqual(len(plot.points), 5)
            self.assertIsInstance(plot.engine, VisPyPlotEngine)
            self.assertEqual(plot.engine.canvas.bgcolor.hex, '#ffffff')
            plot.set_xrange(0., 5.)
            plot.set_series(
                keys[0], np.array([0., 1., np.nan, 4.]),
                np.array([1., 2., np.nan, 3.]),
                np.array([0., 1., 4.]), np.array([1., 2., 3.]),
            )
            plot.refresh_axes()
            self.assertTrue(plot.lines[keys[0]].visible)
            self.assertTrue(plot.points[keys[0]].visible)
        finally:
            plot.close()

    def test_more_than_five_metrics_have_gpu_layers(self):
        keys = tuple(('EEG', f'metric_{i}') for i in range(9))
        plot = VisPyMetricPlot(keys)
        try:
            self.assertEqual(set(plot.lines), set(keys))
            plot.set_series(keys[-1], np.array([0., .5]), np.array([1., 2.]),
                            np.array([0., .5]), np.array([1., 2.]))
            self.assertTrue(plot.lines[keys[-1]].visible)
        finally:
            plot.close()

    def test_raw_cursor_stops_at_its_drawn_samples_without_retiming_them(self):
        plot = VisPyRawPlot('EEG')
        try:
            samples = np.array([5., 5.1, 5.2, 5.3])
            data = np.sin(samples)[:, None]
            frame = (samples, data, data, None, None, ('F3',))
            # Simulate viewport clock running 80 ms ahead of acquisition.
            plot.set_frame(frame, 0., 5., sweep_head=5.38)
            np.testing.assert_allclose(
                plot.engine.sweep_cursor._pos[:, 0], [.06, .06], atol=1e-5
            )
            self.assertAlmostEqual(plot._latest, 5.3)
        finally:
            plot.close()

    def test_raw_timebase_and_channel_count_reuse_gpu_programs(self):
        plot = VisPyRawPlot('EEG')
        times = np.arange(0., 4., 1./64)
        def frame(count, duration):
            values = np.sin(times[:, None]) + 6.*np.arange(count)
            plot.set_frame((times, values, values, None, None,
                            tuple(f'Ch{i}' for i in range(count))),
                           0., duration, nominal_fs=64.)
        try:
            frame(4, 5.)
            visuals = tuple(layer.visual for layer in plot.layers['raw'])
            programs = tuple(visual.shared_program for visual in visuals)
            frame(4, 10.)
            self.assertTrue(set(visuals).isdisjoint(layer.visual for layer in plot.layers['raw']))
            frame(2, 10.)
            self.assertEqual(visuals[:2], tuple(layer.visual for layer in plot.layers['raw']))
            frame(4, 5.)
            self.assertTrue(all(program in [layer.visual.shared_program for layer in plot._layer_pool['raw']]
                                for program in programs))
            self.assertEqual(plot.reserved_channel_count,8)
            self.assertTrue(all(layer.ring.last_time == times[-1]
                                for layer in plot.layers['raw']))
        finally:
            plot.close()

    def test_each_stream_cursor_follows_its_own_drawn_tip(self):
        plots=[]
        try:
            for kind,end in (('EEG',.6),('PPG',.5),('EDA',.3)):
                plot=VisPyRawPlot(kind);plots.append(plot)
                times=np.arange(0.,end+.001,.1)
                values=np.zeros((len(times),1))
                plot.set_frame((times,values,values,None,None,('signal',)),0.,5.,sweep_head=.8,nominal_fs=10.)
                np.testing.assert_allclose(plot.engine.sweep_cursor._pos[:,0],[end/5.,end/5.])
                original=plot.layers['raw'][0].ring.positions.copy()
                plot.set_sweep_head(1.2)
                np.testing.assert_allclose(plot.engine.sweep_cursor._pos[:,0],[end/5.,end/5.])
                np.testing.assert_array_equal(plot.layers['raw'][0].ring.positions,original)
        finally:
            for plot in plots:plot.close()

    def test_raw_uses_same_engine_with_labels_and_gain(self):
        plot = VisPyRawPlot('EEG')
        try:
            self.assertIsInstance(plot.engine, VisPyPlotEngine)
            self.assertEqual(plot.engine.canvas.bgcolor.hex, '#ffffff')
            plot.set_vertical_gain(2.)
            self.assertEqual(plot.vertical_gain, 2.)
            samples = np.array([0., .1, .2, .3])
            data = np.column_stack((np.sin(samples), 6.+np.cos(samples)))
            frame = (samples, data, data*.5, None, None, ('F3', 'F4'))
            plot.set_frame(frame, 0., 5., sweep_head=.3)
            self.assertTrue(plot.raw_line.visible)
            self.assertEqual(
                plot.engine.channel_names[:2],
                ('F3', 'F4')
            )
            self.assertTrue(plot.engine.widget.isAncestorOf(plot.engine.canvas.native))
            self.assertEqual(plot.engine.time_duration, 5.)
        finally:
            plot.close()


    def test_both_adapters_preserve_historical_gpu_segments(self):
        """Appending a sample must not rewrite previous sweep positions."""
        raw = VisPyRawPlot('EEG')
        metrics = VisPyMetricPlot((('EEG', 'AWI'),))
        try:
            times = np.arange(.05, 1.05, .05)
            data = np.sin(times)[:, None]
            raw.set_frame((times, data, data*.5, None, None, ('F3',)),
                          0., 5.)
            layer = raw.layers['raw'][0]
            old = layer.ring.positions.copy()
            old_visual = raw.raw_line
            more = np.append(times, [1.05, 1.10])
            new_data = np.sin(more)[:, None]
            raw.set_frame((more, new_data, new_data*.5, None, None, ('F3',)),
                          0., 5.)
            self.assertIs(raw.raw_line, old_visual)
            np.testing.assert_array_equal(
                old[2:18], layer.ring.positions[2:18])
            key = ('EEG', 'AWI')
            metrics.set_xrange(0., 5.)
            metrics.set_series(key, times, np.sin(times),
                               times[::10], np.sin(times[::10]))
            metric_layer = metrics._layers[key][0]
            previous = metric_layer.ring.positions.copy()
            metric_visual = metrics.lines[key]
            metrics.set_series(key, more, np.sin(more),
                               more[::10], np.sin(more[::10]))
            self.assertIs(metrics.lines[key], metric_visual)
            np.testing.assert_array_equal(
                previous[2:18], metric_layer.ring.positions[2:18])
        finally:
            raw.close()
            metrics.close()

    def test_metrics_cursor_uses_real_measured_sample(self):
        key = ('EEG', 'AWI')
        plot = VisPyMetricPlot((key,))
        try:
            plot.set_xrange(0., 5.)
            timestamps = np.array([0., .5, 1.])
            plot.set_series(key, timestamps, [1., 2., 3.],
                            timestamps, [1., 2., 3.])
            plot.set_xrange(-3., 2.)
            # Viewport clock is 2s; real metrics end at 1s.
            np.testing.assert_allclose(
                plot.engine.sweep_cursor._pos[:, 0], [.2, .2], atol=1e-6)
        finally:
            plot.close()


if __name__ == '__main__':
    unittest.main()
