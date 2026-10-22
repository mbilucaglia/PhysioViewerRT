"""Exercise real local pylsl outlets through acquisition, metrics and Qt."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time
import unittest
import uuid

import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo, StreamOutlet, local_clock

from physiolab.gui import MainWindow
from physiolab.synthetic import SPECS, SyntheticPhysiology
from physiolab.calibration import analyze_eyc, analyze_bsl


class LocalLSLIntegrationTests(unittest.TestCase):
    def test_discover_receive_process_display_and_stop(self):
        app = QApplication.instance() or QApplication([])
        calibration_model = SyntheticPhysiology(seed=2026, artifact_level='none')
        calibration_streams = {}
        for kind, (fs, names) in SPECS.items():
            calibration_streams[kind] = {
                'data': calibration_model.generate(kind, 0, int(fs*60)),
                'timestamps': np.arange(int(fs*60)) / fs,
                'fs': fs, 'channels': list(names)}
        eyc = analyze_eyc(calibration_streams['EEG'])
        bsl = analyze_bsl(calibration_streams, iaf_hz=eyc['iaf_hz'])
        outlets = {}
        prefix = 'physioviewer-test-' + uuid.uuid4().hex
        for kind, (fs, names) in SPECS.items():
            info = StreamInfo(prefix + kind, kind, len(names), fs,
                              'float32', prefix + kind)
            channels = info.desc().append_child('channels')
            for name in names:
                channel = channels.append_child('channel')
                channel.append_child_value('label', name)
                channel.append_child_value('unit', 'microvolts' if kind == 'EEG'
                                            else 'microsiemens' if kind == 'EDA' else 'a.u.')
            outlets[kind] = StreamOutlet(info)
        window = MainWindow()
        window.show()

        def pump_until(predicate, seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return True
                time.sleep(.01)
            return False

        try:
            window.apply_calibration('EYC', {'analysis': eyc})
            window.apply_calibration('BSL', {'analysis': bsl})
            self.assertTrue(pump_until(lambda: not window.lsl_tasks, 10),
                            'LSL discovery did not complete')
            for kind in SPECS:
                combo = window.selectors[kind]
                index = next((i for i in range(combo.count())
                              if combo.itemData(i).name() == prefix + kind), None)
                self.assertIsNotNone(index, f'{kind} test outlet not discovered')
                combo.setCurrentIndex(index)
            self.assertTrue(pump_until(lambda: not window.lsl_tasks, 10),
                            'Channel metadata did not complete')
            for kind, (_, names) in SPECS.items():
                self.assertEqual(window.channel_selectors[kind].names, list(names))
                window.connect_stream(kind)
            window.tabs.setCurrentWidget(window.raw_page)
            window.eeg_display_count.setValue(32)

            model = SyntheticPhysiology(seed=42, artifact_level='none')
            ticks = dict.fromkeys(SPECS, 0)
            origin = local_clock()
            def publish_for(seconds):
                deadline = local_clock() + seconds
                while local_clock() < deadline:
                    for kind, (fs, _) in SPECS.items():
                        target = int((local_clock() - origin) * fs)
                        count = target - ticks[kind]
                        if count:
                            data = model.generate(kind, ticks[kind], count)
                            outlets[kind].push_chunk(data.tolist(), origin + (target - 1) / fs)
                            ticks[kind] = target
                    app.processEvents()
                    time.sleep(.01)
            publish_for(8)
            self.assertTrue(pump_until(
                lambda: all(kind in window.metric_state.latest for kind in SPECS), 3))
            for kind, key in [('EEG', 'BAR'), ('EDA', 'SCL'), ('PPG', 'HR')]:
                self.assertTrue(window.raw_display.history[kind], f'No {kind} waveforms')
                value = window.metric_state.latest[kind].get(key)
                self.assertIsNotNone(value, f'No {key} estimate')
                self.assertTrue(np.isfinite(value), f'Invalid {key} estimate')
            if window.raw_renderer_mode == 'vispy':
                self.assertTrue(pump_until(
                    lambda: all(plot._configuration is not None
                                for plot in window.raw_vispy_plots.values()), 5),
                    'GPU waveforms did not initialize')
                self.assertEqual(window.raw_vispy_plots['EEG']._configuration[0], 32)
                for kind in ('PPG', 'EDA'):
                    for group in window.raw_vispy_plots[kind].layers.values():
                        for layer in group:
                            displayed = layer.ring.values
                            displayed = displayed[np.isfinite(displayed)]
                            self.assertTrue(len(displayed), f'{kind} has no visible samples')
                            self.assertTrue(np.all((displayed >= 0.) & (displayed <= 1.)),
                                            f'{kind} is clipped at default gain')
                self.assertEqual(window.raw_display.units['EEG'], 'µV')
                self.assertEqual(window.raw_display.units['EDA'], 'µS')
                self.assertEqual(window.raw_display.units['PPG'], 'a.u.')
                for kind in ('EDA', 'PPG'):
                    label = window.raw_vispy_plots[kind].engine.amplitude_ruler.bar.label
                    self.assertTrue(label.endswith(window.raw_display.units[kind]))
                    self.assertTrue(any(character.isdigit() for character in label))
                np.testing.assert_allclose(window.raw_display.display_scales['EEG'], 20.)
                for kind in ('EEG', 'PPG', 'EDA'):
                    window.raw_autoscale_buttons[kind].click()
                publish_for(.5)
                self.assertFalse(window.raw_display.autoscale_requests,
                                 'Autoscale did not replay the full displayed window')
                cursors = [plot.engine.sweep_cursor._pos[:, 0]
                           for plot in window.raw_vispy_plots.values()]
                for cursor in cursors[1:]:
                    np.testing.assert_allclose(cursor, cursors[0], atol=1e-6)
                for kind, plot in window.raw_vispy_plots.items():
                    sample_period = 1./plot.layers['raw'][0].ring.rate
                    self.assertLessEqual(plot._sweep_head - plot._latest,
                                         sample_period + 1e-5,
                                         f'{kind} has a wide gap before the shared cursor')
                    self.assertGreaterEqual(plot._sweep_head - plot._latest, -1e-5,
                                            f'{kind} replaced samples ahead of the cursor')
                    ring = plot.layers['raw'][0].ring
                    successor = (ring.last_id+1) % ring.capacity
                    if successor and ring.last_id >= ring.capacity:
                        self.assertFalse(np.all(ring.positions[successor] == -10.),
                                         f'{kind} erased the old segment after the cursor')
                eeg = window.raw_vispy_plots['EEG']
                programs = tuple(layer.visual.shared_program for layer in eeg.layers['raw'])
                workers = dict(window.workers)
                for count, duration, gain in ((8, 10, 2.), (16, 30, .5), (32, 5, 1.)):
                    window.eeg_display_count.setValue(count)
                    window.raw_time_window.setCurrentIndex(window.raw_time_window.findData(duration))
                    window.raw_vertical_gains['EEG'].setValue(gain)
                    publish_for(.8)
                    self.assertTrue(pump_until(
                        lambda: eeg._configuration[:2] == (count, float(duration)), 3))
                    self.assertEqual(tuple(layer.visual.shared_program for layer in eeg.layers['raw']),
                                     programs[:count])
                    self.assertEqual(window.workers, workers)
                    self.assertEqual(eeg.engine.amplitude_ruler._unit, 'µV')
                    span, _ = eeg.engine._amplitude_range
                    self.assertAlmostEqual(span, 20. * (6*count+3) / gain)
                window.eeg_focus_button.setChecked(True)
                publish_for(.5)
                window.eeg_focus_button.setChecked(False)
                window.tabs.setCurrentWidget(window.sources_page)
                publish_for(.5)
                window.tabs.setCurrentWidget(window.raw_page)
                publish_for(.5)
                self.assertEqual(tuple(layer.visual.shared_program for layer in eeg.layers['raw']),
                                 programs)
                for worker in workers.values():
                    self.assertEqual(worker.mailbox.stats()['dropped_samples'], 0)
                window.tabs.setCurrentWidget(window.metrics_page)
                publish_for(.8)
                metrics = window.vispy_metric_plot
                metric_programs = tuple(layer.visual.shared_program
                                        for pair in metrics._layers.values() for layer in pair)
                for duration in (10, 30, 5):
                    window.metric_time_window.setCurrentIndex(window.metric_time_window.findData(duration))
                    publish_for(.5)
                    self.assertAlmostEqual(metrics._duration, duration)
                    self.assertEqual(tuple(layer.visual.shared_program
                                           for pair in metrics._layers.values() for layer in pair),
                                     metric_programs)
                window.normalization.setCurrentIndex(window.normalization.findData('zscore'))
                publish_for(.5)
                self.assertEqual(tuple(layer.visual.shared_program
                                       for pair in metrics._layers.values() for layer in pair),
                                 metric_programs)
                for key in window.metric_state.keys:
                    self.assertTrue(window.metric_state.history[key], f'No {key} history')
                    self.assertTrue(any(np.isfinite(value) for _, value in window.metric_state.history[key]),
                                    f'No valid {key} estimate with calibration active')
                # Reconfigure receivers from Sources while the other signals
                # continue. First Raw Data frames must use current live time,
                # including the restarted stream, rather than an old tab clock.
                from physiolab.raw_snapshot import build_raw_source
                from physiolab.raw_render import prepare_raw_window
                for kind in SPECS:
                    window.tabs.setCurrentWidget(window.sources_page)
                    window.stop_stream(kind)
                    self.assertTrue(pump_until(lambda: kind not in window.workers, 3))
                    publish_for(.4)
                    window.connect_stream(kind)
                    publish_for(1.)
                    chunks = window.raw_display.history[kind]
                    self.assertTrue(chunks, f'{kind}: receiver did not resume')
                    high = window.raw_display.bounds[1]
                    source = build_raw_source(chunks, left=high-10., right=high,
                                              origin=window.raw_display.origin,
                                              vispy=True, replay_history=True,
                                              fit_traces=kind != 'EEG')
                    self.assertIsNotNone(source, f'{kind}: restart cropped outside live viewport')
                    frame = prepare_raw_window(source.chunks, source.left, source.right,
                                               source.origin, fit_traces=source.fit_traces)
                    self.assertIsNotNone(frame, f'{kind}: restart has no drawable frame')
                    self.assertGreater(len(frame[0]), 1)
                    window.tabs.setCurrentWidget(window.raw_page)
                    publish_for(.4)
                    self.assertTrue(window.raw_vispy_plots[kind].configured)
            for kind in SPECS:
                window.stop_stream(kind)
            self.assertTrue(pump_until(lambda: not window.workers, 4),
                            'Receivers failed to stop')
        finally:
            window.close()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
