"""Read-only architectural probes; no production code changes."""
from pathlib import Path
import sys,ast,json,time
from types import SimpleNamespace
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import numpy as np
from physiolab.raw_render import prepare_raw_window
from physiolab.raw_snapshot import build_raw_source
from physiolab.raw_display_state import RawDisplayState
from physiolab.incremental_sweep import SweepRing
from physiolab.gui import MainWindow
from physiolab.raw_render_worker import RawRenderWorker
from physiolab.render_contracts import RawFrameRequest,RawSourceRequest
from PySide6.QtCore import QCoreApplication

def main():
    report={}

    # Peak preservation under supported long timebases.
    fs=256.;t=np.arange(int(60*fs))/fs;x=np.zeros((len(t),1));x[1,0]=100.
    frame=prepare_raw_window([(t,x,x,['Fp1'],fs)],0.,60.,0.,reference=(np.zeros(1),np.ones(1)),decimation_span=60.)
    report['decimation_peak']={'input_samples':len(t),'output_samples':len(frame[0]),
        'input_peak':float(x.max()),'display_peak':float(frame[1].max()),'timebase_seconds':30}

    # Center uses the cached incremental tail, not the full requested visible span.
    fs=128.;t=np.arange(5*128)/fs;x=(10.+np.cos(2*np.pi*t))[:,None]
    state=RawDisplayState();state.append('PPG',x,x,['PPG'],fs,t,received_at=1.)
    source=build_raw_source(state.history['PPG'],left=0.,right=5.,origin=0.,
        reference=state.recording_reference('PPG',1),vispy=True,latest=4.99,fit_traces=True)
    tail=prepare_raw_window(source.chunks,source.left,source.right,0.,reference=source.reference,
        fit_traces=True,decimation_span=source.decimation_span)
    state.remember_frame('PPG',tail)
    fake=SimpleNamespace(raw_display=state,raw_renderer_mode='vispy',raw_vispy_plots={},
        show_processed=SimpleNamespace(isChecked=lambda:True))
    MainWindow.center_raw(fake,'PPG')
    report['manual_center']={'requested_visible_seconds':5.,'cached_frame_span_seconds':float(np.ptp(tail[0])),
        'full_visible_median':float(np.median(x)),'center_used':float(state.initial_references['PPG'][0][0,0])}

    # Real gaps leave occupied line slots from much older cycles.
    ring=SweepRing(5.,10.);ring.append(np.arange(50)/10.,np.ones(50));ring.append([20.,20.1],[2.,2.])
    drawn=np.any(ring.positions!=-10.,axis=(1,2))
    report['stale_sweep_lines']={'drawn_slots':int(drawn.sum()),
        'drawn_slots_older_than_one_window':int(np.count_nonzero(drawn&(ring.stamps<15.1))),
        'newest_sample_time':ring.last_time}

    # A slow source preparation delays all response frames in the batch.
    app=QCoreApplication.instance() or QCoreApplication([])
    def prepare(chunks,*args,**kwargs):
        if chunks==('slow',):time.sleep(.15)
        return (np.array([0.,1.]),np.zeros((2,1)),np.zeros((2,1)),np.zeros(1),np.ones(1),('C',))
    sources={'EEG':RawSourceRequest(('slow',),0.,1.,0.),'PPG':RawSourceRequest(('fast',),0.,1.,0.)}
    results=[];worker=RawRenderWorker()
    worker.frame_ready.connect(lambda result:results.append((time.perf_counter(),result)))
    with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=prepare):
        worker.start();started=time.perf_counter();worker.submit(RawFrameRequest(1,0,sources,started))
        deadline=started+2.
        while not results and time.perf_counter()<deadline:app.processEvents();time.sleep(.001)
        worker.stop()
    report['cross_source_preparation']={'injected_EEG_ms':150.,
        'PPG_response_ms':round((results[0][0]-started)*1000.,2) if results else None,
        'result_sources':list(results[0][1].frames) if results else []}

    # A view change cannot submit a replacement while an obsolete frame is active.
    state=RawDisplayState();first=state.begin_frame({'EEG':sources['EEG']},queued_at=1.)
    state.set_window(30.);replacement=state.begin_frame({'PPG':sources['PPG']},queued_at=2.)
    report['inflight_replacement']={'epoch_after_view_change':state.epoch,
        'active_old_epoch':first.version,'can_submit_replacement_before_old_completion':replacement is not None}

    # Summarize structural coupling rather than treating file count as modularity.
    path=root/'physiolab/gui.py';source_text=path.read_text(encoding='utf-8');tree=ast.parse(source_text)
    window=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    mutations=[]
    for n in ast.walk(window):
        if isinstance(n,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
            targets=n.targets if isinstance(n,ast.Assign) else [n.target]
            for target in targets:
                if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Attribute) and isinstance(target.value.value,ast.Name) and target.value.value.id=='self' and target.value.attr=='raw_display':
                    mutations.append({'line':n.lineno,'field':target.attr})
    report['main_window']={'lines':window.end_lineno-window.lineno+1,
        'methods':sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in window.body),
        'direct_raw_display_assignments':len(mutations),'assigned_fields':sorted(set(m['field'] for m in mutations))}

    x=np.arange(10,dtype=float)[:,None];t=np.arange(10)/10.
    whole=RawDisplayState();whole.append('EEG',x,x,['C'],10.,t,received_at=1.)
    split=RawDisplayState();split.append('EEG',x[:2],x[:2],['C'],10.,t[:2],received_at=1.)
    split.append('EEG',x[2:],x[2:],['C'],10.,t[2:],received_at=2.)
    report['startup_reference_packet_dependence']={'same_samples':True,
        'one_packet_center':float(whole.recording_reference('EEG',1)[0][0]),
        'two_packets_center':float(split.recording_reference('EEG',1)[0][0])}
    class Layer:
        def __init__(self,*args,**kwargs):self.visual=SimpleNamespace(visible=True)
        def reconfigure(self,*args,**kwargs):pass
        def close(self):pass
    plot=VisPyRawPlot.__new__(VisPyRawPlot)
    plot.layers={'raw':[Layer() for _ in range(4)],'filtered':[Layer() for _ in range(4)]}
    plot._layer_pool={k:list(v) for k,v in plot.layers.items()}
    plot._configuration=(4,5.,128.);plot._pending_layers=None;plot._pending_configuration=None
    before=[layer.visual.visible for group in plot.layers.values() for layer in group]
    with patch('physiolab.incremental_sweep.IncrementalSweepLayer',Layer):
        pending,ready=plot._ensure_layers(8,5.,128.)
    after=[layer.visual.visible for group in plot.layers.values() for layer in group]
    report['active_pending_resource_aliasing']={'active_visibility_before':before,'replacement_ready':ready,
        'active_visibility_after_first_staging_step':after,
        'pending_aliases_active':pending['raw'][0] is plot.layers['raw'][0]}

    out=root/'.test-tmp/rendering-audit/pure-probes.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
