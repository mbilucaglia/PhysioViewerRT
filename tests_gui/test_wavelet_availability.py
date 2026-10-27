"""A missing optional runtime must not stop a healthy LSL receiver."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo
from physiolab.gui import MainWindow
from physiolab.worker import Receiver
from physiolab.peripheral_reduction import PeripheralReducer


class WaveletAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def window(self):
        with patch.object(MainWindow,'refresh',lambda self:None): window=MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.workers.clear)
        return window

    def test_missing_wavelet_keeps_current_receiver_and_selection(self):
        window=self.window()
        for kind,previous in (('PPG','off'),('EDA','hampel')):
            with self.subTest(kind=kind):
                choice=window.artifact_choices[kind]
                choice.blockSignals(True); choice.setCurrentIndex(choice.findData(previous)); choice.blockSignals(False)
                worker=SimpleNamespace(active=True,request_stop=Mock(),
                    preprocessing={'preset':'default','notch':True,'artifact_reduction':previous})
                window.workers[kind]=worker
                with patch.dict(sys.modules,{'pywt':None}),patch.object(window,'reset_stream_display') as reset:
                    choice.setCurrentIndex(choice.findData('wavelet'))
                worker.request_stop.assert_not_called()
                reset.assert_not_called()
                self.assertIs(window.workers[kind],worker)
                self.assertNotIn(kind,window.pending_source_changes)
                self.assertEqual(choice.currentData(),previous)
                self.assertIn('setup_windows.cmd',window.statusBar().currentMessage())

    def test_missing_wavelet_is_rejected_before_starting_receiver(self):
        window=self.window()
        info=StreamInfo('test-wavelet','PPG',1,128.,'float32','test-wavelet')
        selector=window.selectors['PPG']
        selector.blockSignals(True); selector.addItem('test',info); selector.blockSignals(False)
        window.channel_selectors['PPG'].set_channels(['P'])
        choice=window.artifact_choices['PPG']
        choice.blockSignals(True); choice.setCurrentIndex(choice.findData('wavelet')); choice.blockSignals(False)
        with patch.dict(sys.modules,{'pywt':None}),patch('physiolab.gui.Receiver') as receiver:
            window.connect_stream('PPG')
        receiver.assert_not_called()
        self.assertIn('setup_windows.cmd',window.statusBar().currentMessage())

    def test_reducer_checks_dependency_before_eight_second_window(self):
        with patch.dict(sys.modules,{'pywt':None}):
            with self.assertRaisesRegex(RuntimeError,'setup_windows.cmd'):
                PeripheralReducer('PPG',128.,1,'wavelet')

    def test_receiver_retains_terminal_error(self):
        info=StreamInfo('test-failure','PPG',1,128.,'float32','test-failure')
        receiver=Receiver(info,'PPG',[0],['P'])
        errors=[]; receiver.failure.connect(errors.append)
        with patch('physiolab.worker.StreamInlet',side_effect=ModuleNotFoundError("No module named 'pywt'")):
            receiver.run()
        self.assertEqual(getattr(receiver,'last_error',None),"PPG: No module named 'pywt'")
        self.assertEqual(errors,[receiver.last_error])

    def test_finished_does_not_overwrite_receiver_error(self):
        window=self.window()
        worker=SimpleNamespace(active=True,last_error="PPG: No module named 'pywt'")
        window.workers['PPG']=worker
        window.receiver_finished('PPG',worker)
        self.assertEqual(window.statusBar().currentMessage(),worker.last_error)
        self.assertNotIn('PPG',window.workers)
        self.assertEqual(window.stream_buttons['PPG'].text(),'Play')
