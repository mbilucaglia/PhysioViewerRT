"""Native synthetic-LSL playback reproduction: both PPG and SC use Hampel.

Run .venv/Scripts/python.exe tools/benchmark_hampel_playback.py on Windows.
Shows a window for 14 seconds, emits short source blocks (or --block-seconds 0.5 for burst delivery), saves screenshots and
timing JSON in .test-tmp, and checks source errors and the configured display-delay limit.
This local benchmark is sensitive to PC load; it is not a hard real-time claim.
"""
import os,sys,time,json,uuid,argparse
os.environ['QT_QPA_PLATFORM']='windows'
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
(root/'.test-tmp').mkdir(exist_ok=True)
import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo,StreamOutlet,resolve_byprop,local_clock
from physiolab.gui import MainWindow
from physiolab.worker import Receiver
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--block-seconds',type=float,default=.025)
args=parser.parse_args()
if not 0 < args.block_seconds <= 2.:
    parser.error('--block-seconds must be in (0, 2]')
block_seconds=args.block_seconds
app=QApplication([])
with patch.object(MainWindow,'refresh',lambda self:None):w=MainWindow()
w.resize(1440,900);w.tabs.setCurrentWidget(w.raw_page);w.show();app.processEvents()
outlets={};workers={};errors=[]
for kind,fs in (('PPG',128.),('EDA',32.)):
    identifier='hampel-display-'+kind+uuid.uuid4().hex
    info=StreamInfo(identifier,kind,1,fs,'float32',identifier)
    channel=info.desc().append_child('channels').append_child('channel')
    channel.append_child_value('label','SCL' if kind=='EDA' else 'PPG')
    channel.append_child_value('unit','microsiemens' if kind=='EDA' else 'a.u.')
    outlets[kind]=StreamOutlet(info)
    resolved=resolve_byprop('source_id',identifier,minimum=1,timeout=3.)[0]
    worker=Receiver(resolved,kind,[0],['SCL' if kind=='EDA' else 'PPG'],
        preprocessing={'artifact_reduction':'hampel','notch':False})
    worker.stream_ready.connect(w.ready_stream)
    worker.display_scale_ready.connect(w.set_stream_display_scale)
    worker.failure.connect(errors.append)
    w.workers[kind]=worker;workers[kind]=worker;worker.start()
origin=local_clock();sent=0;heads=[];ticks=[];last_tick=0;saved=False;stalls=[];drawn_ages={'PPG':[],'EDA':[]}
try:
    while local_clock()-origin<14.:
        elapsed=local_clock()-origin
        target=int(elapsed/block_seconds)
        while sent<target:
            for kind,fs in (('PPG',128.),('EDA',32.)):
                first,last=round(sent*fs*block_seconds),round((sent+1)*fs*block_seconds)
                if first==last:
                    continue
                times=(np.arange(first,last)+.5)/fs
                values=(np.sin(2*np.pi*1.2*times) if kind=='PPG' else
                        3.+.025*times+.05*np.sin(2*np.pi*.35*times))
                values+=np.where((times>4.)&(times<4.04),2.,0.)
                outlets[kind].push_chunk(values[:,None].tolist(),origin+times[-1])
            sent+=1
        app.processEvents()
        if w._last_gui_tick!=last_tick:
            last_tick=w._last_gui_tick
            if elapsed>6.:
                head=w.raw_display.bounds[1]
                if heads and abs(head-heads[-1])<1e-6:
                    stalls.append({'elapsed':elapsed,'head':head,'clock_heads':{k:c.head-origin for k,c in w.raw_display.source_clocks.items()},'since_receipt':{k:time.monotonic()-c.received_at for k,c in w.raw_display.source_clocks.items()},'last_sample':{k:v-origin for k,v in w.raw_display.last_sample.items()},'source_bounds':w.raw_display.source_bounds})
                heads.append(head);ticks.append(last_tick)
                for kind in workers:
                    renderer=w.raw_vispy_plots.get(kind)
                    if renderer is not None and np.isfinite(renderer.latest_sample_time):
                        drawn_ages[kind].append(1000*(local_clock()-w.raw_display.origin-renderer.latest_sample_time))
        if elapsed>12. and not saved:
            w.grab().save(str(root/'.test-tmp/hampel-live-all.png'));saved=True
        time.sleep(.002)
    w.set_raw_focus('EDA',True);app.processEvents()
    w.set_plot_paused('raw',True)
    app.processEvents();w.grab().save(str(root/'.test-tmp/hampel-live-sc.png'))
    steps=np.diff(heads);intervals=np.diff(ticks)
    report={'errors':errors,'frames_measured':len(heads),'zero_advance_frames':int(np.count_nonzero(steps<=1e-6)),'stalls':stalls,
        'frame_interval_p50_ms':float(np.median(intervals)*1000),'frame_interval_p95_ms':float(np.percentile(intervals,95)*1000),
        'head_step_p50_ms':float(np.median(steps)*1000),'head_step_p95_ms':float(np.percentile(steps,95)*1000),
        'presentation_buffer_seconds':w.settings.presentation_delay_seconds,
        'source_block_seconds':block_seconds,
        'drawn_sample_age_ms':{k:{'median':float(np.median(v)),'p95':float(np.percentile(v,95))} for k,v in drawn_ages.items()},
        'ring_invalid_slots':{k:int(np.count_nonzero(np.all(w.raw_vispy_plots[k].layers['filtered'][0].ring.positions==-10.,axis=(1,2)))) for k in workers},
        'timestamps_strictly_increasing':all(np.all(np.diff(np.concatenate([c[0] for c in w.raw_display.history[k]]))>0) for k in workers)}
    (root/'.test-tmp/hampel-live-display.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    assert not errors
    assert report['presentation_buffer_seconds']==w.settings.presentation_delay_seconds,report
finally:
    for worker in workers.values():worker.stop()
    w.workers.clear();w.close();app.processEvents()
