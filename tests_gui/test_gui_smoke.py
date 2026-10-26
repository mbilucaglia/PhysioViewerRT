"""Windows Qt smoke checks for stream selector and raw/metric UI boundaries.

Run with QT_QPA_PLATFORM=offscreen and the full requirements installed.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication

from physiolab.gui import MainWindow
from physiolab.ingress import ChunkMailbox
from physiolab.acquisition_contracts import AcquisitionChunk
from physiolab.render_contracts import RawFrameResult


class FakeInfo:
    def __init__(self, uid, channels=1):
        self.identifier, self.channels = uid, channels

    def uid(self):
        return self.identifier

    def channel_count(self):
        return self.channels

    def nominal_srate(self):
        return 32.

    def name(self):
        return 'Synthetic'

    def type(self):
        return 'EDA'


class FakeReceiver:
    def __init__(self, fs):
        self.mailbox = ChunkMailbox(fs)
        self.active = True

    def stop(self):
        self.active = False
        return True

    def isRunning(self):
        return True

    def request_stop(self):
        self.active = False


class GuiSmokeTests(unittest.TestCase):
    def test_hidden_metric_readouts_defer_updates_but_ingestion_continues(self):
        self.window.tabs.setCurrentWidget(self.window.sources_page)
        receiver = FakeReceiver(32.)
        self.window.workers['EEG'] = receiver
        raw = np.ones((16, 1))
        receiver.mailbox.put(AcquisitionChunk(raw, raw, ['F3'],
            {'AWI': 2., 'BAR': .5}, 32., np.arange(16)/32., time.monotonic()))
        with patch.object(self.window, 'refresh_metric_labels') as labels:
            self.window.poll_receivers()
            labels.assert_not_called()
        self.assertEqual(self.window.metric_state.latest['EEG']['AWI'], 2.)
        self.window.tabs.setTabVisible(self.window.tabs.indexOf(self.window.metrics_page), True)
        self.window.tabs.setCurrentWidget(self.window.metrics_page)
        self.assertIn('2.000', self.window.metric_labels['EEG', 'AWI'].text())

    def test_only_active_plot_view_is_rendered(self):
        with patch.object(self.window, 'draw') as raw, \
                patch.object(self.window, 'refresh_metric_plot') as metrics, \
                patch.object(self.window, 'refresh_affect_view') as affect:
            self.window.tabs.setCurrentWidget(self.window.sources_page)
            self.window.render_frame()
            raw.assert_not_called()
            metrics.assert_not_called()
            affect.assert_not_called()
            self.window.tabs.setCurrentWidget(self.window.affect_page)
            self.window.render_frame()
            affect.assert_called_once()
            raw.assert_not_called()
            metrics.assert_not_called()

    def test_metric_ruler_units_follow_visible_series_and_normalization(self):
        now = time.monotonic()
        hr = self.window.metric_state.history['PPG', 'HR']
        hr.extend([(now-.5, 70.), (now, 72.)])
        original = list(hr)
        self.window.refresh_metric_plot()
        self.assertEqual(self.window.metric_amplitude_ruler._unit, 'bpm')
        self.assertEqual(self.window.metric_time_ruler._unit, 's')
        for mode, unit in (('zscore', 'σ'), ('zmad', 'σ (MAD)'),
                           ('robust_iqr', 'σ (IQR)'), ('minmax', 'norm.')):
            self.window.normalization.setCurrentIndex(self.window.normalization.findData(mode))
            self.window.refresh_metric_plot()
            self.assertEqual(self.window.metric_amplitude_ruler._unit, unit)
        self.assertEqual(list(hr), original)
        self.window.normalization.setCurrentIndex(self.window.normalization.findData('identity'))
        self.window.raw_display.units['EDA'] = 'µS'
        self.window.metric_state.history['EDA', 'SCL'].extend([(now-.5, 1.), (now, 2.)])
        self.window.refresh_metric_plot()
        self.assertEqual(self.window.metric_amplitude_ruler._unit, 'mixed units')
        self.window.metric_checks['PPG', 'HR'].setChecked(False)
        self.assertEqual(self.window.metric_amplitude_ruler._unit, 'µS')

    def prepare_selected_receiver(self, kind, uid='old', channels=3):
        info = FakeInfo(uid, channels)
        names = [f'{uid}-{i}' for i in range(channels)]
        self.window.channel_metadata_cache[uid] = (names, '')
        self.window.selectors[kind].addItem(uid, info)
        worker = FakeReceiver(32.)
        worker.info = info
        worker.selected_indices = self.window.channel_selectors[kind].selected_indices()
        worker.selected_names = [names[i] for i in worker.selected_indices]
        self.window.workers[kind] = worker
        return worker

    def test_channel_changes_reconnect_once_using_latest_choice(self):
        old = self.prepare_selected_receiver('EEG')
        other = FakeReceiver(32.)
        self.window.workers['PPG'] = other
        samples = np.ones((2, 3))
        self.window.receive('EEG', samples, samples, old.selected_names, None, 32., [100., 100.03])
        picker = self.window.channel_selectors['EEG']
        picker.select(0, False)
        picker.select(1, False)
        self.assertFalse(old.active)
        self.assertFalse(self.window.raw_display.history['EEG'])
        self.assertEqual(picker.selected_indices(), [2])
        self.window.source_change_timers['EEG'].stop()
        with patch.object(self.window, 'connect_stream') as connect:
            self.window.receiver_finished('EEG', old)
            connect.assert_called_once_with('EEG')
        self.assertNotIn('EEG', self.window.pending_source_changes)
        self.assertIs(self.window.workers['PPG'], other)

    def test_stream_switch_waits_for_new_metadata_then_reconnects(self):
        old = self.prepare_selected_receiver('EDA')
        self.window.selectors['EDA'].addItem('new', FakeInfo('new', 2))
        with patch.object(self.window, 'queue_lsl_task', return_value=77):
            self.window.selectors['EDA'].setCurrentIndex(1)
        self.window.source_change_timers['EDA'].stop()
        with patch.object(self.window, 'connect_stream') as connect:
            self.window.receiver_finished('EDA', old)
            connect.assert_not_called()
            self.window.lsl_task_completed(77, (['new-a', 'new-b'], ''), None)
            connect.assert_called_once_with('EDA')
        self.assertEqual(self.window.channel_selectors['EDA'].names, ['new-a', 'new-b'])

    def test_stop_button_cancels_pending_automatic_reconnect(self):
        old = self.prepare_selected_receiver('EEG')
        self.window.channel_selectors['EEG'].select(1, False)
        button = self.window.stream_buttons['EEG']
        self.assertTrue(button.isEnabled(), 'Pending reconfiguration must remain cancellable')
        button.click()
        with patch.object(self.window, 'connect_stream') as connect:
            self.window.receiver_finished('EEG', old)
            self.window.apply_pending_source_change('EEG')
            connect.assert_not_called()
        self.assertFalse(self.window.pending_source_changes)

    def test_stop_button_enabled_after_automatic_reconnect(self):
        from unittest.mock import MagicMock
        old = self.prepare_selected_receiver('EEG')
        self.window.channel_selectors['EEG'].select(1, False)
        self.window.source_change_timers['EEG'].stop()
        new = MagicMock(active=True)
        new.isRunning.return_value = True
        with patch('physiolab.gui.Receiver', return_value=new):
            self.window.receiver_finished('EEG', old)
        self.assertIs(self.window.workers['EEG'], new)
        button = self.window.stream_buttons['EEG']
        self.assertTrue(button.isEnabled(), 'Replacement receiver must have a usable Stop button')
        self.assertEqual(button.text(), 'Stop')
        button.click()
        new.request_stop.assert_called_once()
        self.window.workers.pop('EEG')

    def test_display_count_and_channel_changes_leave_other_stop_buttons_usable(self):
        eeg = self.prepare_selected_receiver('EEG')
        others = {kind:self.prepare_selected_receiver(kind) for kind in ('PPG','EDA')}
        self.window.eeg_display_count.setValue(1)
        self.assertTrue(eeg.active)
        self.assertFalse(self.window.pending_source_changes)
        self.window.channel_selectors['EEG'].select(1, False)
        for kind, worker in others.items():
            self.assertTrue(self.window.stream_buttons[kind].isEnabled())
            self.window.stream_buttons[kind].click()
            self.assertFalse(worker.active, kind)

    def test_stop_while_waiting_for_metadata_cancels_reconnect(self):
        old = self.prepare_selected_receiver('EDA')
        self.window.selectors['EDA'].addItem('new', FakeInfo('pending-source', 2))
        with patch.object(self.window, 'queue_lsl_task', return_value=88):
            self.window.selectors['EDA'].setCurrentIndex(1)
        self.window.source_change_timers['EDA'].stop()
        self.window.receiver_finished('EDA', old)
        self.assertIn('EDA', self.window.pending_source_changes)
        button = self.window.stream_buttons['EDA']
        self.assertTrue(button.isEnabled())
        button.click()
        with patch.object(self.window, 'connect_stream') as connect:
            self.window.lsl_task_completed(88, (['one','two'], ''), None)
            self.window.apply_pending_source_change('EDA')
            connect.assert_not_called()
        self.assertNotIn('EDA', self.window.pending_source_changes)

    def test_source_change_is_deferred_during_calibration(self):
        old = self.prepare_selected_receiver('EEG')
        self.window.capture = object()
        self.window.channel_selectors['EEG'].select(1, False)
        self.assertTrue(old.active)
        self.assertIn('EEG', self.window.pending_source_changes)
        self.window.capture = None
        self.window.schedule_source_change('EEG')
        self.assertFalse(old.active)

    def test_ppg_and_eda_expand_and_restore_without_stopping_acquisition(self):
        from PySide6.QtWidgets import QWidget
        self.window.tabs.setCurrentWidget(self.window.raw_page)
        original = dict(self.window.workers)
        for kind in ('PPG', 'EDA'):
            button = self.window.raw_focus_buttons[kind]
            button.setChecked(True)
            self.assertEqual(self.window.focused_raw_kind, kind)
            for modality in ('EEG', 'PPG', 'EDA'):
                self.assertEqual(self.window.findChild(QWidget, f'{modality}PlotPanel').isHidden(),
                                 modality != kind)
            button.setChecked(False)
            self.assertIsNone(self.window.focused_raw_kind)
            for modality in ('EEG', 'PPG', 'EDA'):
                self.assertFalse(self.window.findChild(QWidget, f'{modality}PlotPanel').isHidden())
        self.assertEqual(self.window.workers, original)

    def test_conversion_editor_keeps_settings_per_source_and_compact_numbers(self):
        from physiolab.source_conversion_widgets import SourceConversionControls
        controls = SourceConversionControls()
        self.addCleanup(controls.close)
        controls.set_source('sensor-a')
        controls.gain.setValue(.001)
        controls.offset.setValue(2.)
        controls.output_unit.setText('µS')
        settings = controls.conversion()
        controls.set_source('sensor-b')
        self.assertEqual(controls.conversion().gain, 1.)
        self.assertEqual(controls.gain.text(), '1')
        self.assertEqual(controls.offset.text(), '0')
        self.assertEqual(controls.conversion().output_unit, '')
        controls.set_source('sensor-a')
        self.assertEqual(controls.conversion(), settings)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Startup discovery is asynchronous and tested independently.
        # Backend-switch tests start from the fallback on every Qt platform;
        # native startup and real GPU paths are covered by the LSL integration.
        with patch.object(MainWindow, 'refresh', lambda window: None), \
                patch('physiolab.gui.importlib.util.find_spec', return_value=None):
            self.window = MainWindow()
        self.window.resize(1100, 660)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_raw_ingress_and_metrics_can_update_together(self):
        n = 256
        stamps = 100. + np.arange(n) / 256.
        samples = np.column_stack([
            np.sin(2*np.pi*10*(stamps-100.) + i)
            for i in range(8)
        ])
        worker = FakeReceiver(256.)
        names = ['F3', 'F4', 'O1', 'O2', 'P3', 'P4', 'C3', 'C4']
        worker.mailbox.put(AcquisitionChunk(
            samples, samples*.8, names,
            {'IAF': 10., 'AWI': .2, 'BAR': 1.4},
            256., stamps, time.monotonic()
        ))
        self.window.workers['EEG'] = worker
        self.window.poll_receivers()
        self.assertEqual(len(self.window.raw_display.history['EEG']), 1)
        self.assertEqual(self.window.metric_state.latest['EEG']['BAR'], 1.4)
        self.window.render_frame()
        self.window.tabs.setTabVisible(self.window.tabs.indexOf(self.window.metrics_page), True)
        self.window.tabs.setCurrentWidget(self.window.metrics_page)
        self.assertIn('0.200', self.window.metric_labels[('EEG', 'AWI')].text())
        self.window.render_frame()
        self.assertEqual(self.window.metric_state.history[('EEG', 'AWI')][-1][1], .2)

    def test_changing_lsl_source_never_waits_for_metadata(self):
        def slow_lookup(info, timeout):
            time.sleep(.3)
            return ['EDA'], ''
        combo = self.window.selectors['EDA']
        with patch('physiolab.lsl_tasks.full_channel_labels', slow_lookup):
            started = time.perf_counter()
            combo.addItem('Synthetic EDA', FakeInfo('synthetic-eda'))
            elapsed = time.perf_counter()-started
            self.assertLess(elapsed, .15)
            self.assertFalse(self.window.stream_buttons['EDA'].isEnabled())
            deadline = time.monotonic()+2.
            while time.monotonic() < deadline:
                self.app.processEvents()
                if self.window.channel_selectors['EDA'].names == ['EDA']:
                    break
                time.sleep(.02)
            self.assertEqual(self.window.channel_selectors['EDA'].names, ['EDA'])
            self.assertTrue(self.window.stream_buttons['EDA'].isEnabled())

    def test_cached_source_reenables_play_after_pending_metadata(self):
        combo = self.window.selectors['EDA']
        cached = FakeInfo('cached')
        self.window.channel_metadata_cache['cached'] = (['EDA'], '')
        combo.addItem('Cached', cached)
        self.window.stream_buttons['EDA'].setEnabled(False)
        self.window.stream_selection_changed('EDA')
        self.assertTrue(self.window.stream_buttons['EDA'].isEnabled())
        combo.clear()
        self.assertFalse(self.window.stream_buttons['EDA'].isEnabled())

    def test_pyqtgraph_amplitude_scales_around_labeled_channel_offsets(self):
        self.window.tabs.setCurrentWidget(self.window.raw_page)
        self.window.raw_display.inflight_ticket = 42
        self.window.raw_vertical_gains['EEG'].setValue(2.)
        times = np.array([0., .1, .2])
        raw = np.array([[1., 7.], [0., 6.], [-1., 5.]])
        response = RawFrameResult(
            ticket=42, version=self.window.raw_display.epoch,
            frames={'EEG': (times, raw, raw * 1., np.zeros(2),
                            np.ones(2), ('F3', 'F4'))},
        )
        self.window.apply_raw_frame(response)
        np.testing.assert_allclose(self.window.curves['EEG'][0].getData()[1], [2, 0, -2])
        np.testing.assert_allclose(self.window.curves['EEG'][2].getData()[1], [8, 6, 4])
        self.assertEqual(self.window.plots['EEG'].getAxis('left')._tickLevels,
                         [[(0., 'F3'), (6., 'F4')]])

    def test_refresh_preserves_channel_selection_for_unchanged_source(self):
        info = FakeInfo('same-source', channels=4)
        self.window.channel_metadata_cache[info.uid()] = (['a', 'b', 'c', 'd'], '')
        self.window.selectors['EEG'].addItem('Source', info)
        channels = self.window.channel_selectors['EEG']
        for i, action in enumerate(channels.actions):
            action.setChecked(i == 2)
        self.window.discovery_serial = 123
        self.window.lsl_task_completed(123, [info], None)
        self.assertEqual(channels.selected_indices(), [2])

    def test_additional_metrics_build_controls_histories_and_readouts(self):
        from physiolab.metric_catalog import DEFAULT_METRICS, MetricDefinition
        extra = (MetricDefinition('EEG', 'THETA'), MetricDefinition('EDA', 'SCR'))
        with patch.object(MainWindow, 'refresh', lambda window: None):
            window = MainWindow(metric_definitions=DEFAULT_METRICS + extra)
        try:
            stamps = np.arange(32) / 32.
            raw = np.ones((32, 1))
            window.receive('EEG', raw, raw, ['F3'], {'THETA': 4.2}, 32., stamps)
            self.assertEqual(len(window.metric_checks), len(DEFAULT_METRICS) + len(extra))
            self.assertIn('4.200', window.metric_labels['EEG', 'THETA'].text())
            self.assertEqual(window.metric_state.history['EEG', 'THETA'][-1][1], 4.2)
            self.assertIn(('EDA', 'SCR'), window.metric_curves)
        finally:
            window.close()

    def test_metric_timebase_schedules_replay_without_new_measurement(self):
        key = ('EEG', 'AWI')
        history = [(time.monotonic(), .2)]
        self.window.metric_state.history[key].extend(history)
        self.window.metric_dirty = False
        self.window.metric_time_window.setCurrentIndex(1)
        self.assertTrue(self.window.metric_dirty)
        self.assertEqual(list(self.window.metric_state.history[key]), history)

    def test_timebase_change_rejects_inflight_frame_for_previous_view(self):
        previous_version = self.window.raw_display.epoch
        self.window.raw_display.inflight_ticket = 42
        self.window.raw_time_window.setCurrentIndex(1)
        self.window.apply_raw_frame(RawFrameResult(
            ticket=42, version=previous_version, frames={'EEG': object()}))
        self.assertIsNone(self.window.raw_display.inflight_ticket)
        self.assertTrue(self.window.raw_display.dirty)

    def test_stopped_source_does_not_freeze_shared_sweep_clock(self):
        from types import SimpleNamespace
        self.window.raw_display.origin = 100.
        self.window.raw_display.last_sample = {'EEG': 110., 'PPG': 110., 'EDA': 100.}
        self.window.raw_display.clock = SimpleNamespace(advance=lambda now: 109.75)
        self.window.update_raw_xranges()
        self.assertAlmostEqual(self.window.raw_display.bounds[1], 9.75)

    def test_sources_tab_keeps_later_started_and_restarted_streams_in_first_view(self):
        from physiolab.raw_snapshot import build_raw_source
        from physiolab.raw_render import prepare_raw_window
        self.window.timer.stop()
        self.window.tabs.setCurrentWidget(self.window.sources_page)
        state = self.window.raw_display
        # Five seconds in Sources: EEG starts first, singles join later,
        # then EEG is stopped and restarted without leaving Sources.
        for tick in range(151):
            now = tick / 30.
            if tick == 60:
                state.reset('EEG')
            for kind, starts in (('EEG', 0), ('PPG', 30), ('EDA', 45)):
                if tick < starts or (kind == 'EEG' and 60 <= tick < 90):
                    continue
                values = np.array([[np.sin(now)]])
                state.append(kind, values, values, [kind], 30., [100.+now], received_at=now)
            with patch('physiolab.gui.time.monotonic', return_value=now):
                self.window.render_frame()
        self.assertGreater(state.bounds[1], 4.6)
        for kind, chunks in state.history.items():
            source = build_raw_source(chunks, left=state.bounds[1]-10.,
                                      right=state.bounds[1], origin=state.origin,
                                      vispy=True, replay_history=True,
                                      fit_traces=kind != 'EEG')
            self.assertIsNotNone(source, f'{kind} is outside first visible frame')
            frame = prepare_raw_window(source.chunks, source.left, source.right,
                                       source.origin, fit_traces=source.fit_traces)
            self.assertGreater(len(frame[0]), 2, f'{kind} has no first-frame trace')

    def test_eeg_focus_preserves_acquisition_and_restores_other_panels(self):
        from PySide6.QtWidgets import QWidget
        self.window.tabs.setCurrentWidget(self.window.raw_page)
        worker = FakeReceiver(32.)
        self.window.workers['EDA'] = worker
        self.window.eeg_focus_button.setChecked(True)
        self.assertTrue(self.window.findChild(QWidget, 'PPGPlotPanel').isHidden())
        self.assertTrue(self.window.findChild(QWidget, 'EDAPlotPanel').isHidden())
        self.assertTrue(worker.active)
        self.window.eeg_focus_button.setChecked(False)
        self.assertFalse(self.window.findChild(QWidget, 'EDAPlotPanel').isHidden())
        self.assertIs(self.window.workers['EDA'], worker)

    def test_autoscale_sits_by_number_and_keeps_plus_minus_controls(self):
        from PySide6.QtWidgets import QHBoxLayout, QDoubleSpinBox, QPushButton
        for kind in ('EEG', 'PPG', 'EDA'):
            gain = self.window.raw_vertical_gains[kind]
            header = self.window.findChild(QHBoxLayout, f'{kind}PlotHeader')
            self.assertEqual(header.indexOf(self.window.raw_autoscale_buttons[kind]),
                             header.indexOf(gain)+1)
            self.assertIn('width: 0px', gain.styleSheet())
            self.assertGreater(gain.lineEdit().width(), 20)
            for suffix in ('Minus', 'Plus'):
                self.assertFalse(self.window.findChild(QPushButton, f'{kind}Amplitude{suffix}').isHidden())

    def test_autoscale_requests_full_window_then_applies_common_gain(self):
        frame = (np.array([0., 1.]), np.array([[-2., -2.], [2., 14.]]),
                 np.array([[-2., -2.], [2., 14.]]))
        self.window.raw_display.frames['EEG'] = frame
        self.window.autoscale_raw('EEG')
        self.assertIn('EEG', self.window.raw_display.autoscale_requests)
        self.window.raw_renderer_mode = 'vispy'
        self.window._apply_autoscale('EEG', frame)
        self.assertAlmostEqual(self.window.raw_vertical_gains['EEG'].value(), .3125, places=2)

    def test_switch_raw_renderer_without_changing_metrics_or_receivers(self):
        from PySide6.QtWidgets import QWidget

        class FakeGpuPlot:
            def __init__(self, kind):
                self.widget = QWidget()
                self.frames = []

            def set_frame(self, frame, left, right, **options):
                self.frames.append((left, right, options))

            def reset(self):
                pass

            def close(self):
                pass

        old_metrics = self.window.metric_state.history
        old_receivers = self.window.workers
        with patch('physiolab.gui.VisPyRawPlot', FakeGpuPlot):
            self.window.raw_renderer_choice.setCurrentIndex(1)
            self.assertEqual(self.window.raw_renderer_mode, 'vispy')
            self.assertEqual(len(self.window.raw_vispy_plots), 3)
            for stack in self.window.raw_plot_stacks.values():
                self.assertEqual(stack.currentIndex(), 1)
            self.window.raw_renderer_choice.setCurrentIndex(0)
            self.assertEqual(self.window.raw_renderer_mode, 'pyqtgraph')
            for stack in self.window.raw_plot_stacks.values():
                self.assertEqual(stack.currentIndex(), 0)
        self.assertIs(self.window.metric_state.history, old_metrics)
        self.assertIs(self.window.workers, old_receivers)

    def test_metric_gpu_backend_preserves_values_controls_and_fallback(self):
        from PySide6.QtWidgets import QWidget

        class FakeMetricGpu:
            def __init__(self, keys):
                self.widget = QWidget()
                self.data = {}
                self.bounds = None
                self.keys = keys

            def set_series(self, key, x, y, mx, my, **options):
                self.data[key] = (np.asarray(x), np.asarray(y),
                                  np.asarray(mx), np.asarray(my), options)

            def set_xrange(self, left, right):
                self.bounds = (left, right)

            def refresh_axes(self):
                pass

            def set_amplitude_units(self, unit, description=''):
                self.amplitude_unit = unit

            def close(self):
                pass

        original_history = self.window.metric_state.history
        key = ('EEG', 'AWI')
        current = time.monotonic()
        self.window.metric_state.history[key].extend([
            (current - 1., .2), (current - .5, .4), (current, .6)
        ])
        with patch('physiolab.gui.VisPyMetricPlot', FakeMetricGpu):
            self.window.metric_renderer_choice.setCurrentIndex(1)
            self.assertEqual(self.window.metric_renderer_mode, 'vispy')
            self.assertEqual(self.window.metric_plot_stack.currentIndex(), 1)
            self.window.refresh_metric_plot()
            gpu = self.window.vispy_metric_plot
            self.assertEqual(len(gpu.data[key][2]), 3)
            self.window.metric_checks[key].setChecked(False)
            self.assertFalse(gpu.data[key][4]['visible'])
            self.window.metric_checks[key].setChecked(True)
            self.window.zoom_metric_plot(.5)
            self.assertIsNotNone(gpu.bounds)
            self.window.metric_renderer_choice.setCurrentIndex(0)
            self.assertEqual(self.window.metric_plot_stack.currentIndex(), 0)
            self.assertIs(self.window.metric_state.history, original_history)
            self.assertAlmostEqual(self.window.metric_state.history[key][-1][1], .6)

    def test_mockup_tabs_sources_and_resizable_raw_panels(self):
        from PySide6.QtWidgets import QSplitter, QDoubleSpinBox
        self.assertEqual(
            [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())],
            ['Sources', 'Raw Data', 'Metrics', 'Affect']
        )
        self.assertIsInstance(self.window.raw_plot_splitter, QSplitter)
        self.assertEqual(self.window.raw_plot_splitter.count(), 3)
        self.assertEqual(
            self.window.raw_scroll.verticalScrollBarPolicy(),
            __import__('PySide6.QtCore', fromlist=['Qt']).Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.window.tabs.setCurrentIndex(0)
        self.assertTrue(self.window.selectors['EEG'].isVisible())
        original_workers = self.window.workers
        self.window.tabs.setCurrentIndex(1)
        gain = self.window.raw_vertical_gains['EEG']
        self.assertIsInstance(gain, QDoubleSpinBox)
        self.assertEqual(gain.value(), 1.)
        self.window.adjust_raw_vertical_gain('EEG', 1.2)
        self.assertAlmostEqual(gain.value(), 1.2)
        self.assertEqual(self.window.raw_vertical_gains['EDA'].value(), 1.)
        self.assertIs(self.window.workers, original_workers)
        self.window.raw_time_window.setCurrentIndex(
            self.window.raw_time_window.findData(8)
        )
        self.assertEqual(self.window.raw_display.view_seconds, 8.)

    def test_editable_designer_file_is_live_ui_with_real_controls(self):
        from PySide6.QtWidgets import QWidget, QPushButton
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / (
            'designer/PhysioViewerRT_ClinicalLayout.ui')
        self.assertTrue(path.exists())
        self.assertEqual(self.window.tabs.objectName(), 'mainTabs')
        self.assertIs(self.window.centralWidget().findChild(
            QWidget, 'sourcesTab'), self.window.tabs.widget(0))
        self.assertIs(self.window.centralWidget().findChild(
            QWidget, 'rawDataTab'), self.window.tabs.widget(1))
        self.assertIs(self.window.centralWidget().findChild(
            QWidget, 'metricsTab'), self.window.tabs.widget(2))
        self.assertEqual(self.window.raw_plot_splitter.objectName(),
                         'rawPlotSplitter')
        self.assertIs(self.window.selectors['EEG'],
                      self.window.centralWidget().findChild(
                          QWidget, 'EEGStreamSelector'))
        self.assertIs(self.window.raw_vertical_gains['PPG'],
                      self.window.centralWidget().findChild(
                          QWidget, 'PPGAmplitude'))
        self.assertIsInstance(self.window.centralWidget().findChild(
            QPushButton, 'rawPlotPause'), QPushButton)

    def test_metrics_requires_two_real_baselines(self):
        tabs = self.window.tabs
        def check(ready):
            for page in (self.window.metrics_page, self.window.affect_page):
                index = tabs.indexOf(page)
                self.assertTrue(tabs.isTabVisible(index))
                self.assertEqual(tabs.isTabEnabled(index), ready)
        check(False)
        self.window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.5}})
        check(False)
        self.window.apply_calibration('BSL', {'analysis': {
            'metrics': {'EEG': {'BAR': {'mu': 1., 'sigma': 1.}}}
        }})
        check(True)
        self.window.clear_calibration('EYC')
        check(False)
        self.window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.5}})
        check(True)
        self.window.clear_calibration('BSL')
        check(False)

    def test_peripheral_affect_needs_both_receivers(self):
        view = self.window.affect_view
        self.assertTrue(view.ei_card.isHidden())
        self.window.workers['PPG'] = FakeReceiver(128.)
        self.window.sync_affect_sources()
        self.assertTrue(view.ei_card.isHidden())
        self.window.workers['EDA'] = FakeReceiver(32.)
        self.window.sync_affect_sources()
        self.assertFalse(view.ei_card.isHidden())
        self.window.workers['PPG'].active = False
        self.window.sync_affect_sources()
        self.assertTrue(view.ei_card.isHidden())

    def test_ei_readout_remains_visible_without_additional_display_reference(self):
        self.window.metric_state.latest['EI'] = {'EI':.3, 'status':'Live EI'}
        self.window.normalization.setCurrentIndex(self.window.normalization.findData('zscore'))
        self.window.refresh_metric_labels()
        self.assertIn('0.300', self.window.metric_labels['EI','EI'].text())
        self.assertNotIn('Waiting', self.window.metric_status['EI'].text())

    def test_preprocessing_settings_and_display_count(self):
        self.assertEqual(self.window.filter_choices['EEG'].currentData(), 'default')
        self.assertTrue(self.window.filter_notches['EEG'].isChecked())
        self.window.filter_choices['EEG'].setCurrentIndex(1)
        self.assertEqual(self.window.filter_choices['EEG'].currentData(), 'wide')
        self.assertFalse(self.window.eeg_display_count.isEnabled())
        self.prepare_selected_receiver('EEG', channels=32)
        self.assertEqual(self.window.eeg_display_count.value(),
                         self.window.settings.default_eeg_display_channels)
        self.window.eeg_display_count.setValue(12)
        self.assertEqual(self.window.eeg_display_count.value(), 12)
        self.assertNotIn('EEG', self.window.raw_display.references)

    def test_eeg_display_count_follows_selected_source_and_channel_subset(self):
        self.prepare_selected_receiver('EEG', uid='eeg', channels=32)
        count = self.window.eeg_display_count
        self.assertEqual(count.maximum(), 32)
        count.setValue(12)
        self.window.workers.pop('EEG')
        for uid in ('SC', 'PPG'):
            self.window.channel_metadata_cache[uid] = ([uid], '')
            self.window.selectors['EEG'].addItem(uid, FakeInfo(uid, 1))
            self.window.selectors['EEG'].setCurrentIndex(self.window.selectors['EEG'].count()-1)
            self.assertEqual(count.value(), 1)
            self.assertEqual(count.maximum(), 1)
            count.setValue(8)
            self.assertEqual(count.value(), 1)
        self.window.selectors['EEG'].setCurrentIndex(0)
        self.assertEqual(count.value(), self.window.settings.default_eeg_display_channels)
        picker = self.window.channel_selectors['EEG']
        for index in range(4, 32):
            picker.select(index, False)
        self.assertEqual(count.value(), 4)
        self.assertEqual(count.maximum(), 4)
        for index in range(4):
            picker.select(index, False)
        self.assertFalse(count.isEnabled())
        picker.select(0, True)
        self.assertTrue(count.isEnabled())
        self.assertEqual(count.value(), 1)

    def test_eeg_display_count_uses_source_size_before_channel_metadata_arrives(self):
        with patch.object(self.window, 'queue_lsl_task', return_value=77):
            self.window.selectors['EEG'].addItem('SC', FakeInfo('SC', 1))
        self.assertEqual(self.window.eeg_display_count.value(), 1)
        self.assertEqual(self.window.eeg_display_count.maximum(), 1)

    def test_designer_tab_reordering_keeps_correct_display_handlers(self):
        tabs = self.window.tabs
        original = tabs.indexOf(self.window.raw_page)
        self.assertEqual(original, 1)
        tabs.tabBar().moveTab(original, 0)
        self.assertEqual(tabs.indexOf(self.window.raw_page), 0)
        tabs.setCurrentWidget(self.window.raw_page)
        self.assertTrue(self.window.raw_plot_visible('EEG'))
        self.window.raw_display.dirty = False
        self.window.tab_changed(tabs.currentIndex())
        self.assertTrue(self.window.raw_display.dirty)
        self.window.loaded_eyc = {'analysis': {'iaf_hz': 10.}}
        self.window.loaded_bsl = {'analysis': {'metrics': {'EEG': {'AWI': {'mu': 0.}}}}}
        self.window.update_metrics_availability()
        tabs.setCurrentWidget(self.window.metrics_page)
        self.window.metric_dirty = False
        self.window.tab_changed(tabs.currentIndex())
        # Tab switching schedules rendering on the next GUI tick.
        self.assertTrue(self.window.metric_dirty)
        self.window.render_frame()
        self.assertFalse(self.window.metric_dirty)

    def test_plot_pause_does_not_stop_lsl_ingress(self):
        from PySide6.QtWidgets import QPushButton
        self.window.tabs.setCurrentIndex(1)
        button = self.window.centralWidget().findChild(QPushButton, 'rawPlotPause')
        self.assertEqual(button.text(), 'Pause')
        button.click()
        self.assertTrue(self.window.raw_display.paused)
        self.assertEqual(button.text(), 'Play')
        n = 256
        stamps = 100. + np.arange(n) / 256.
        wave = np.sin(np.arange(n)/25.)[:, None]
        worker = FakeReceiver(256.)
        self.window.workers['EEG'] = worker
        self.window.receive('EEG', wave, wave, ['F3'], None, 256., stamps)
        self.assertTrue(self.window.raw_display.dirty)
        self.assertEqual(len(self.window.raw_display.history['EEG']), 1)
        self.window.render_frame()
        self.assertIsNone(self.window.raw_display.inflight_ticket)
        self.assertTrue(worker.active)
        button.click()
        self.assertFalse(self.window.raw_display.paused)
        self.assertEqual(button.text(), 'Pause')

    def test_raw_scroll_event_does_not_force_synchronous_plotting(self):
        self.window.raw_view_scrolled()
        self.assertGreater(self.window.raw_display.interacting_until, time.monotonic())
        self.window.render_frame()
        self.assertTrue(self.window.raw_display.dirty)
        bar = self.window.raw_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
