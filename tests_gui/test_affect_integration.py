"""Real LSL → cvxEDA → compatible BSL → both native affect trajectories."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo, StreamOutlet, local_clock

from physiolab.calibration import analyze_bsl, analyze_eyc
from physiolab.gui import MainWindow
from physiolab.synthetic import SPECS, SyntheticPhysiology
from physiolab.source_conversion import SourceConversion
from physiolab.sc_decomposition import TonicSCProcessor


class AffectIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the native application alive across subsequent GL test classes.
        cls.app = QApplication.instance() or QApplication([])

    def test_real_streams_enable_both_responses_and_stop_hides_only_peripheral(self):
        if not TonicSCProcessor().available:
            self.skipTest('Install requirements-affect.txt')
        app = self.app
        baseline_model = SyntheticPhysiology(seed=2026, artifact_level='none')
        streams, outlets = {}, {}
        prefix = 'affect-test-'+uuid.uuid4().hex
        for kind, (fs, names) in SPECS.items():
            unit = 'microvolts' if kind == 'EEG' else 'microsiemens' if kind == 'EDA' else 'a.u.'
            streams[kind] = {'data': baseline_model.generate(kind, 0, int(60*fs)),
                'timestamps': np.arange(int(60*fs))/fs, 'fs': fs, 'channels': list(names),
                'units': [unit]*len(names), 'conversion': SourceConversion().metadata()}
            info = StreamInfo(prefix+kind, kind, len(names), fs, 'float32', prefix+kind)
            channels = info.desc().append_child('channels')
            for name in names:
                channel = channels.append_child('channel')
                channel.append_child_value('label', name)
                channel.append_child_value('unit', unit)
            outlets[kind] = StreamOutlet(info)
        eyc = analyze_eyc(streams['EEG'])
        bsl = analyze_bsl(streams, eyc['iaf_hz'])
        window = MainWindow()
        window.resize(1440,900)
        window.show()

        def pump(predicate, timeout=10):
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return True
                time.sleep(.01)
            return False

        try:
            window.apply_calibration('EYC', {'analysis': eyc})
            window.apply_calibration('BSL', {'analysis': bsl})
            self.assertTrue(pump(lambda: not window.lsl_tasks))
            for kind, combo in window.selectors.items():
                index = next((i for i in range(combo.count())
                              if combo.itemData(i).name() == prefix+kind), -1)
                self.assertGreaterEqual(index, 0)
                combo.setCurrentIndex(index)
            self.assertTrue(pump(lambda: not window.lsl_tasks))
            for kind in SPECS:
                window.connect_stream(kind)
            window.tabs.setCurrentWidget(window.affect_page)
            live = SyntheticPhysiology(seed=42, artifact_level='none')
            ticks = dict.fromkeys(SPECS, 0)
            origin = local_clock()

            def publish(seconds):
                deadline = local_clock()+seconds
                while local_clock() < deadline:
                    for kind, (fs, _) in SPECS.items():
                        target = int((local_clock()-origin)*fs)
                        count = target-ticks[kind]
                        if count:
                            data = live.generate(kind, ticks[kind], count)
                            outlets[kind].push_chunk(data.tolist(), origin+(target-1)/fs)
                            ticks[kind] = target
                    app.processEvents()
                    time.sleep(.01)
            # Peripheral must be available without the former 20-second wait.
            publish(8)
            snapshot = window.affect_state.snapshot(local_clock(), 60.)
            self.assertTrue(all(response.current is not None for response in snapshot.responses),
                            [(r.key,r.status) for r in snapshot.responses])
            self.assertGreater(len(snapshot.responses[0].points), 10)
            self.assertGreater(len(snapshot.responses[1].points), 2)
            self.assertTrue(window.metric_state.observations['EDA','SCL'])
            self.assertIsNotNone(window.affect_view.ei_plot.current)
            self.assertFalse(window.affect_view.ei_card.isHidden())
            window.refresh_affect_view()
            app.processEvents()
            output = Path('.test-tmp/affect-live.png').resolve()
            output.parent.mkdir(exist_ok=True)
            window.grab().save(str(output))
            window.affect_view.pause.setChecked(True)
            frozen = window.affect_view.plane.responses
            publish(.7)
            self.assertIs(window.affect_view.plane.responses, frozen)
            window.affect_view.pause.setChecked(False)
            window.stop_stream('EDA')
            self.assertTrue(window.affect_view.ei_card.isHidden())
            self.assertIsNone(window.affect_view.ei_plot.current)
            publish(.7)
            snapshot = window.affect_state.snapshot(local_clock(), 60.)
            self.assertIsNotNone(snapshot.responses[0].current)
            self.assertIsNone(snapshot.responses[1].current)
        finally:
            window.close()
            app.processEvents()
