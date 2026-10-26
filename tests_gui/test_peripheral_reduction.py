"""Real LSL source-time alignment and Designer controls for waveform reduction."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
import uuid
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QComboBox
from pylsl import StreamInfo,StreamOutlet,resolve_byprop,local_clock
from physiolab.gui import MainWindow
from physiolab.worker import Receiver

class PeripheralReductionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_designer_choices_and_restart_request_are_per_modality(self):
        with patch.object(MainWindow,'refresh',lambda self:None):
            window = MainWindow()
        try:
            for kind in ('PPG','EDA'):
                choice = window.findChild(QComboBox,kind+'ArtifactReduction')
                self.assertIs(choice,window.artifact_choices[kind])
                self.assertEqual([choice.itemData(i) for i in range(choice.count())],['off','hampel','wavelet'])
                with patch.object(window,'schedule_source_change') as changed:
                    choice.setCurrentIndex(2)
                    changed.assert_called_once_with(kind)
                self.assertIn('8-second',choice.toolTip())
        finally:
            window.close();self.app.processEvents()

    def test_metric_plot_time_matches_raw_source_time_despite_late_delivery(self):
        with patch.object(MainWindow,'refresh',lambda self:None):
            window = MainWindow()
        try:
            end=local_clock()-.5
            stamps=end-np.arange(15,-1,-1)/32.
            raw=np.sin(np.arange(16))[:,None]
            metric={'HR':72.,'_observations':{'HR':{'window_end':end,'available_at':end+1.4}}}
            window.receive('PPG',raw,raw,['PPG'],metric,32.,stamps,metric_at=500.)
            at,value=window.metric_state.history['PPG','HR'][-1]
            self.assertAlmostEqual(at+window._affect_clock_offset,end)
            self.assertAlmostEqual(window.raw_display.history['PPG'][-1][0][-1],end)
            self.assertNotEqual(at,500.)
        finally:
            window.close();self.app.processEvents()

    def test_live_wavelet_buffers_then_keeps_raw_processed_and_metric_source_times_aligned(self):
        outlets,receivers = {},{}
        errors=[]
        prefix='peripheral-'+uuid.uuid4().hex
        fs_by_kind={'PPG':128.,'EDA':32.}
        for kind,fs in fs_by_kind.items():
            info=StreamInfo(prefix+kind,kind,1,fs,'float32',prefix+kind)
            channel=info.desc().append_child('channels').append_child('channel')
            channel.append_child_value('label',kind)
            channel.append_child_value('unit','microsiemens' if kind=='EDA' else 'a.u.')
            outlets[kind]=StreamOutlet(info)
            resolved=resolve_byprop('source_id',prefix+kind,minimum=1,timeout=3.)
            self.assertTrue(resolved)
            receiver=Receiver(resolved[0],kind,[0],[kind],preprocessing={'artifact_reduction':'wavelet','notch':False})
            receiver.failure.connect(errors.append)
            receivers[kind]=receiver
            receiver.start()
        ticks=dict.fromkeys(fs_by_kind,0)
        captured={kind:[] for kind in fs_by_kind}
        origin=local_clock()
        try:
            while local_clock()-origin < 11.:
                for kind,fs in fs_by_kind.items():
                    target=int((local_clock()-origin)*fs)
                    if target>ticks[kind]:
                        t=np.arange(ticks[kind],target)/fs
                        data=np.sin(2*np.pi*1.2*t) if kind=='PPG' else 3.+.05*np.sin(.4*t)
                        data=data+np.where((t>4.)&(t<4.04),2.,0.)
                        outlets[kind].push_chunk(data[:,None].tolist(),origin+(target-1)/fs)
                        ticks[kind]=target
                    captured[kind].extend(receivers[kind].mailbox.drain())
                self.app.processEvents();time.sleep(.01)
            self.assertFalse(errors,errors)
            for kind,fs in fs_by_kind.items():
                chunks=captured[kind]
                self.assertTrue(chunks,kind)
                for chunk in chunks:
                    self.assertEqual(chunk.raw.shape,chunk.filtered.shape)
                    self.assertEqual(len(chunk.timestamps),len(chunk.raw))
                    t=np.rint((np.asarray(chunk.timestamps)-origin)*fs)/fs
                    expected=np.sin(2*np.pi*1.2*t) if kind=='PPG' else 3.+.05*np.sin(.4*t)
                    expected=expected+np.where((t>4.)&(t<4.04),2.,0.)
                    np.testing.assert_allclose(chunk.raw[:,0],expected,atol=2e-5)
                    if chunk.metric:
                        for observation in chunk.metric.get('_observations',{}).values():
                            self.assertLessEqual(observation['window_end'],chunk.timestamps[-1]+5e-5)
                            self.assertGreaterEqual(observation['available_at'],observation['window_end'])
                all_times=np.concatenate([c.timestamps for c in chunks])
                np.testing.assert_allclose(np.diff(all_times),1/fs,atol=5e-5)
                np.testing.assert_array_equal(np.diff(np.rint((all_times-origin)*fs).astype(int)),1)
                self.assertEqual(receivers[kind].source_configuration['preprocessing']['artifact_reduction'],'wavelet')
                metric_name='HR' if kind=='PPG' else 'SCL'
                self.assertTrue(any(c.metric and c.metric.get(metric_name) is not None for c in chunks),kind)
        finally:
            for receiver in receivers.values(): receiver.stop()
            self.app.processEvents()
