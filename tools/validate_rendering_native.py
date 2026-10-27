"""Native transition/retention/memory validation; opens and closes its own window."""
import os
os.environ['QT_QPA_PLATFORM']='windows'
import ctypes
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from physiolab.gui import MainWindow


def memory():
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
             'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
             'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    counters=Counters(); counters.cb=ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    handle=ctypes.windll.kernel32.GetCurrentProcess()
    assert ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb)
    return {'working_set_bytes':int(counters.WorkingSetSize),'private_commit_bytes':int(counters.PagefileUsage)}


def main():
    app=QApplication([])
    with patch.object(MainWindow,'refresh',lambda self:None): window=MainWindow()
    output=ROOT/'.test-tmp/rendering-native'; output.mkdir(parents=True,exist_ok=True)
    report={'transitions':[],'memory':[],'errors':[]}
    window.raw_controller.status.connect(report['errors'].append)
    draws={k:0 for k in ('EEG','PPG','EDA')}
    for kind,plot in window.raw_vispy_plots.items():
        plot.canvas.events.draw.connect(lambda event,k=kind:draws.__setitem__(k,draws[k]+1))

    def pump(predicate,timeout=15.):
        end=time.perf_counter()+timeout
        while time.perf_counter()<end:
            app.processEvents(); time.sleep(.003)
            if predicate(): return
        raise AssertionError('Native transition did not settle')

    def settled():
        state=window.raw_display
        if state.inflight or state.dirty or state.center_requests or state.autoscale_requests: return False
        if window.raw_renderer_mode=='vispy':
            return all(not p.history_needs_replay(window.eeg_display_count.value() if k=='EEG' else 1,
                state.view_seconds) for k,p in window.raw_vispy_plots.items())
        return all(len(window.curves[k])==2*(window.eeg_display_count.value() if k=='EEG' else 1) for k in draws)

    try:
        window.resize(1440,900); window.tabs.setCurrentWidget(window.raw_page); window.show()
        window.eeg_display_count.setRange(1,32); window.eeg_display_count.setValue(8)
        for kind,fs,count in (('EEG',256.,32),('PPG',128.,1),('EDA',32.,1)):
            t=np.arange(int(300*fs))/fs
            x=np.sin(2*np.pi*(1.2 if kind!='EEG' else 9.)*t[:,None]+np.arange(count))
            if kind=='EEG': x*=20.
            else: x+=10.
            window.receive(kind,x,x*.8,[f'C{i+1}' for i in range(count)],None,fs,1000.+t)
        pump(lambda:all(k in window.raw_display.frames for k in draws))
        window.set_plot_paused('raw',True); pump(settled)
        references={k:window.raw_display.initial_references[k][0].copy() for k in draws}
        for mode in ('vispy','pyqtgraph','vispy'):
            window.raw_renderer_choice.setCurrentIndex(window.raw_renderer_choice.findData(mode))
            for count in (8,32):
                window.eeg_display_count.setValue(count)
                for duration in (5,10,30,5,15):
                    start=time.perf_counter()
                    window.raw_time_window.setCurrentIndex(window.raw_time_window.findData(duration))
                    pump(settled)
                    for k,reference in references.items():
                        np.testing.assert_array_equal(window.raw_display.initial_references[k][0],reference)
                    if mode=='vispy':
                        plot=window.raw_vispy_plots['EEG']
                        assert plot.channel_count==count and len(plot.layers['raw'])==count
                        assert all(np.any(layer.ring.positions!=-10.) for layer in plot.layers['raw'])
                    else:
                        assert len(window.curves['EEG'])==2*count
                        assert f'{duration:g} s view' in window.plots['EEG'].getPlotItem().titleLabel.text
                    report['transitions'].append({'backend':mode,'channels':count,'seconds':duration,
                                                   'settle_ms':(time.perf_counter()-start)*1000.})
                for raw,clean in ((True,False),(False,True),(True,True),(False,False),(True,True)):
                    window.show_raw.setChecked(raw); window.show_processed.setChecked(clean); pump(settled)
                for kind in draws:
                    old_gain=window.raw_vertical_gains[kind].value()
                    window.center_raw(kind); pump(settled)
                    assert window.raw_vertical_gains[kind].value()==old_gain
                    centers=window.raw_display.initial_references[kind][0].copy()
                    window.autoscale_raw(kind); pump(settled)
                    np.testing.assert_array_equal(window.raw_display.initial_references[kind][0],centers)
                    references[kind]=centers
                window.grab().save(str(output/f'{mode}-{count}.png'))
        # The maximum supported timebase exercises both GPU resource banks.
        for index in range(21):
            duration=300 if index%2==0 else 5
            window.raw_time_window.setCurrentIndex(window.raw_time_window.findData(duration)); pump(settled)
            memory_report={'seconds':duration,**memory()}
            memory_report['ring_cpu_bytes']=sum(sum(getattr(layer.ring,name).nbytes for name in
                ('positions','stamps','values','identities')) for plot in window.raw_vispy_plots.values()
                for group in plot._layer_pool.values() for layer in group)
            memory_report['resource_bank_layers']=sum(len(group)
                for plot in window.raw_vispy_plots.values() for group in plot._layer_pool.values())
            report['memory'].append(memory_report)
        assert len({item['ring_cpu_bytes'] for item in report['memory'][1:]})==1
        assert len({item['resource_bank_layers'] for item in report['memory']})==1
        # Live history can expire while the frozen source snapshot remains usable.
        frozen=window.raw_display.visible_history('EEG')
        for kind,fs,count in (('EEG',256.,32),('PPG',128.,1),('EDA',32.,1)):
            t=np.arange(int(fs))/fs; x=np.ones((len(t),count))*100.
            window.receive(kind,x,x,[f'C{i+1}' for i in range(count)],None,fs,1600.+t)
        assert window.raw_display.visible_history('EEG') is frozen
        window.raw_renderer_choice.setCurrentIndex(0); pump(settled)
        window.raw_renderer_choice.setCurrentIndex(1); pump(settled)
        window.set_plot_paused('raw',False)
        pump(lambda:window.raw_vispy_plots['EEG'].latest_sample_time>599.)
        # Clear just this synthetic source and verify fresh generations render.
        generation=window.raw_display.signals.generations['PPG']
        window.reset_stream_display('PPG')
        assert window.raw_display.signals.generations['PPG']==generation+1
        t=np.arange(128)/128.; x=np.sin(t)[:,None]
        window.receive('PPG',x,x,['P'],None,128.,1700.+t)
        pump(lambda:window.raw_vispy_plots['PPG'].configured)
        report['draw_events']=draws
        report['passed']=True
    finally:
        start=time.perf_counter(); window.close(); app.processEvents()
        report['close_ms']=(time.perf_counter()-start)*1000.
        (output/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
