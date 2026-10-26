"""Measure native draw events, data-tip progress and cursor errors with all streams."""
import os,sys,time,json,uuid,argparse
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='windows'
root=Path(__file__).resolve().parents[1]
(root/'.test-tmp').mkdir(exist_ok=True)
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=16.)
args=parser.parse_args()
import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo,StreamOutlet,resolve_byprop,local_clock
from physiolab.gui import MainWindow
from physiolab.worker import Receiver
from physiolab.synthetic import SyntheticPhysiology,SPECS
from physiolab.asr_tasks import fit_training_asr

train_gen=SyntheticPhysiology(seed=2026,artifact_level='none')
fs,names=SPECS['EEG']
training={'fs':fs,'channels':list(names),'data':train_gen.generate('EEG',0,60*fs),
    'timestamps':np.arange(60*fs)/fs,'units':['uV']*len(names),'preprocessing':{'notch':False}}
model=fit_training_asr(training)
app=QApplication([])
with patch.object(MainWindow,'refresh',lambda self:None):w=MainWindow()
w.asr_session.model=model;w.asr_session.enabled=True
w.eeg_display_count.setRange(1,32);w.eeg_display_count.setValue(8)
w.resize(1440,900);w.tabs.setCurrentWidget(w.raw_page);w.show();app.processEvents()
outlets={};workers={};errors=[];paint={k:[] for k in SPECS};tips={k:[] for k in SPECS};cursor_errors={k:[] for k in SPECS}
gen=SyntheticPhysiology(seed=2027,artifact_level='moderate');sent={k:0 for k in SPECS}
def on_draw(kind,event):
    renderer=w.raw_vispy_plots.get(kind)
    if renderer is None or not renderer.configured:return
    now=time.perf_counter()
    if now-origin_perf<5.:return
    paint[kind].append(now);tips[kind].append(renderer.latest_sample_time)
    head=getattr(renderer,'_sweep_head',float('nan'))
    cursor_errors[kind].append(max(0.,head-renderer.latest_sample_time))
try:
    for kind,(rate,labels) in SPECS.items():
        identifier='three-stream-'+kind+uuid.uuid4().hex
        info=StreamInfo(identifier,kind,len(labels),rate,'float32',identifier)
        channels=info.desc().append_child('channels')
        for label in labels:
            channel=channels.append_child('channel');channel.append_child_value('label',label)
            channel.append_child_value('unit','uV' if kind=='EEG' else 'microsiemens' if kind=='EDA' else 'a.u.')
        outlets[kind]=StreamOutlet(info)
        resolved=resolve_byprop('source_id',identifier,minimum=1,timeout=3.)[0]
        worker=Receiver(resolved,kind,list(range(len(labels))),list(labels),
            preprocessing={'notch':False,**({'artifact_reduction':'hampel'} if kind!='EEG' else {})},
            eeg_asr_model=model if kind=='EEG' else None)
        worker.stream_ready.connect(w.ready_stream);worker.display_scale_ready.connect(w.set_stream_display_scale)
        worker.failure.connect(errors.append);workers[kind]=worker;w.workers[kind]=worker;worker.start()
    for kind in SPECS:
        w.raw_vispy_plots[kind].canvas.events.draw.connect(lambda event,k=kind:on_draw(k,event))
    origin=local_clock();origin_perf=time.perf_counter()
    while local_clock()-origin<args.seconds:
        elapsed=local_clock()-origin
        for kind,(rate,labels) in SPECS.items():
            target=int(elapsed*rate)
            if target>sent[kind]:
                values=gen.generate(kind,sent[kind],target-sent[kind])
                outlets[kind].push_chunk(values.tolist(),origin+(target-1)/rate)
                sent[kind]=target
        app.processEvents();time.sleep(.003)
    report={'errors':errors,'ASR_processed_samples':workers['EEG'].asr_processed_samples,
        'display_buffer_seconds':w.raw_display.clock.presentation_delay,
        'eeg_displayed_channels':w.raw_vispy_plots['EEG'].channel_count,'streams':{}}
    for kind in SPECS:
        intervals=np.diff(paint[kind])*1000
        progress=np.diff(tips[kind])>1e-6
        report['streams'][kind]={'draws':len(paint[kind]),'draw_interval_median_ms':float(np.median(intervals)),
            'draw_interval_p95_ms':float(np.percentile(intervals,95)),
            'data_advancing_draws':int(np.count_nonzero(progress)),
            'max_cursor_ahead_of_drawn_samples_ms':float(max(cursor_errors[kind],default=0.)*1000)}
    w.grab().save(str(root/'.test-tmp/three-stream-playback-restored.png'))
    (root/'.test-tmp/three-stream-playback-restored.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report));assert not errors;assert report['ASR_processed_samples']>0
    assert report['eeg_displayed_channels']==8
    assert all(s['max_cursor_ahead_of_drawn_samples_ms']<=1e-6 for s in report['streams'].values())
finally:
    for worker in workers.values():worker.stop()
    w.workers.clear();w.close();app.processEvents()
