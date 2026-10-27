"""Native draw/sample-age matrix with an independent LSL publisher process.

Default runs audit checkout and current worktree under matching 8/32-channel
Off/both-Hampel loads, then current 8/32-channel and EEG-inactive reducer cases.
No personal files are read or written. Only children created here are stopped.
Use --case to run one case, or --seconds for a shorter diagnostic (not comparison).
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]


def distribution(values):
    import numpy as np
    a=np.asarray(values,dtype=float)
    a=a[np.isfinite(a)]
    return {'count':len(a),**({f'p{p}':float(np.percentile(a,p)) for p in (50,95,99)} if len(a) else {}),
            'max':float(a.max()) if len(a) else None}


def trial(args):
    os.environ['QT_QPA_PLATFORM']='windows'
    sys.path.insert(0,str(Path(args.repo).resolve()))
    import numpy as np
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    from pylsl import resolve_byprop,local_clock
    from physiolab.gui import MainWindow
    from physiolab.worker import Receiver
    from physiolab.synthetic import SyntheticPhysiology,SPECS
    from physiolab.asr_tasks import fit_training_asr
    output=HERE/'.test-tmp/rendering-matrix'; output.mkdir(parents=True,exist_ok=True)
    model=None
    if not args.no_eeg:
        generator=SyntheticPhysiology(seed=2026,artifact_level='none')
        fs,names=SPECS['EEG']
        model=fit_training_asr({'fs':fs,'channels':list(names),'data':generator.generate('EEG',0,60*fs),
            'timestamps':np.arange(60*fs)/fs,'units':['uV']*len(names),'preprocessing':{'notch':False}})
    app=QApplication([])
    with patch.object(MainWindow,'refresh',lambda self:None): window=MainWindow()
    window.asr_session.model=model; window.asr_session.enabled=model is not None
    window.eeg_display_count.setRange(1,32); window.eeg_display_count.setValue(args.channels)
    window.resize(1440,900); window.tabs.setCurrentWidget(window.raw_page); window.show(); app.processEvents()
    kinds=[k for k in SPECS if not(args.no_eeg and k=='EEG')]
    paint={k:[] for k in kinds}; tips={k:[] for k in kinds}; ages={k:[] for k in kinds}
    cursor={k:[] for k in kinds}; durations={k:[] for k in kinds}
    frame_age={k:[] for k in kinds}; request_age={k:[] for k in kinds}
    workers={}; errors=[]; transitions=[]; producer=None
    token='refactor-'+uuid.uuid4().hex
    origin=local_clock()+5.
    def draw(kind,event):
        renderer=window.raw_vispy_plots[kind]
        elapsed=local_clock()-origin
        if elapsed<5. or not renderer.configured: return
        paint[kind].append(time.perf_counter())
        tips[kind].append(renderer.latest_sample_time)
        ages[kind].append((local_clock()-window.raw_display.origin-renderer.latest_sample_time)*1000.)
        cursor[kind].append(max(0.,getattr(renderer,'_sweep_head',renderer.latest_sample_time)-renderer.latest_sample_time)*1000.)
        durations[kind].append(renderer.sweep_duration)
        controller=getattr(window,'raw_controller',None)
        timing=controller.presented_timing.get(kind) if controller is not None else None
        if timing:
            frame_age[kind].append((time.perf_counter()-timing[1])*1000.)
            request_age[kind].append((time.perf_counter()-timing[0])*1000.)
    try:
        cmd=[sys.executable,'-B',str(HERE/'tools/rendering_test_producer.py'),'--id',token,
             '--origin',str(origin),'--seconds',str(args.seconds)]
        if args.no_eeg: cmd.append('--no-eeg')
        producer=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for kind in kinds:
            info=resolve_byprop('source_id',token+'-'+kind,minimum=1,timeout=4.)
            if not info: raise RuntimeError('Producer did not publish '+kind)
            rate,labels=SPECS[kind]
            reduction=('hampel' if args.reducer=='both' or args.reducer==kind.lower() else 'off')
            worker=Receiver(info[0],kind,list(range(len(labels))),list(labels),
                preprocessing={'notch':False,**({'artifact_reduction':reduction} if kind!='EEG' else {})},
                eeg_asr_model=model if kind=='EEG' else None)
            worker.stream_ready.connect(window.ready_stream)
            worker.display_scale_ready.connect(window.set_stream_display_scale)
            worker.failure.connect(errors.append)
            workers[kind]=worker; window.workers[kind]=worker; worker.start()
            window.raw_vispy_plots[kind].canvas.events.draw.connect(lambda e,k=kind:draw(k,e))
        generator=SyntheticPhysiology(seed=2027,artifact_level='moderate')
        for kind in kinds:
            rate,labels=SPECS[kind]; history=generator.generate(kind,0,60*rate)
            window.receive(kind,history,history*.8 if kind=='EEG' else history,list(labels),None,
                           rate,origin-60.+np.arange(60*rate)/rate)
        window.performance.enabled=True; window.performance.interval=1e9
        schedule=[(6.,10.),(10.,30.),(14.,5.),(18.,15.)]
        while local_clock()<origin+args.seconds:
            elapsed=local_clock()-origin
            if schedule and elapsed>=schedule[0][0]:
                _,duration=schedule.pop(0); start=time.perf_counter()
                window.raw_time_window.setCurrentIndex(window.raw_time_window.findData(duration))
                transitions.append({'at':start,'duration':duration,'command_ms':(time.perf_counter()-start)*1000.})
            app.processEvents(); time.sleep(.003)
        report={'label':args.case,'repo':str(args.repo),'platform':platform.platform(),
            'processor':platform.processor(),'python':sys.version,'channels_requested':args.channels,
            'channels_displayed':window.raw_vispy_plots['EEG'].channel_count if not args.no_eeg else 0,
            'reducer':args.reducer,'eeg_active':not args.no_eeg,'seconds':args.seconds,
            'independent_producer':True,'presentation_buffer_seconds':window.settings.presentation_delay_seconds,
            'ASR_processed_samples':workers['EEG'].asr_processed_samples if 'EEG' in workers else 0,
            'errors':errors,'streams':{},'transitions':[]}
        for kind in kinds:
            advancing=np.diff(tips[kind])>1e-6
            at=np.array(paint[kind]); advanced=at[1:][advancing]
            report['streams'][kind]={'draws':len(at),'draw_interval_ms':distribution(np.diff(at)*1000.),
                'data_advancing_draws':int(np.count_nonzero(advancing)),
                'data_advance_interval_ms':distribution(np.diff(advanced)*1000.),
                'drawn_sample_age_ms':distribution(ages[kind]),'cursor_lead_ms':distribution(cursor[kind]),
                'prepared_frame_age_at_draw_ms':distribution(frame_age[kind]),
                'request_age_at_draw_ms':distribution(request_age[kind])}
        for event in transitions:
            item={k:v for k,v in event.items() if k!='at'}; item['first_new_timebase_draw_ms']={}
            for kind in kinds:
                at=np.array(paint[kind]); duration=np.array(durations[kind])
                ready=at[(at>=event['at'])&(duration==event['duration'])]
                item['first_new_timebase_draw_ms'][kind]=float((ready[0]-event['at'])*1000.) if len(ready) else None
            report['transitions'].append(item)
        report['timings_ms']={k:distribution(v) for k,v in window.performance._samples.items() if v}
        report['outcomes']=dict(getattr(window.performance,'_counts',{}))
        report['ring_cpu_bytes']={k:sum(sum(getattr(layer.ring,name).nbytes for name in
            ('positions','stamps','values','identities')) for group in renderer._layer_pool.values() for layer in group)
            for k,renderer in window.raw_vispy_plots.items()}
        window.grab().save(str(output/(args.case+'.png')))
        (output/(args.case+'.json')).write_text(json.dumps(report,indent=2))
        print(json.dumps(report),flush=True)
        assert not errors
        if not args.no_eeg:
            assert report['ASR_processed_samples']>0
            assert report['channels_displayed']==args.channels
    finally:
        for worker in workers.values(): worker.stop()
        window.workers.clear(); window.close(); app.processEvents()
        if producer is not None:
            producer.terminate(); producer.wait(timeout=5.)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case')
    parser.add_argument('--repo',default=str(HERE))
    parser.add_argument('--baseline',default=r'C:\Users\brainlab.ext1\Desktop\GitHub Marco\PhysioViewerRT')
    parser.add_argument('--channels',type=int,default=8)
    parser.add_argument('--reducer',choices=['off','ppg','eda','both'],default='off')
    parser.add_argument('--no-eeg',action='store_true')
    parser.add_argument('--seconds',type=float,default=23.)
    args=parser.parse_args()
    if args.case: return trial(args)
    cases=[(f'baseline-{n}-{r}',args.baseline,n,r,False) for n in (8,32) for r in ('off','both')]
    cases += [(f'refactor-{n}-{r}',str(HERE),n,r,False) for n in (8,32) for r in ('off','ppg','eda','both')]
    cases += [('refactor-no-eeg-'+r,str(HERE),8,r,True) for r in ('off','ppg','eda','both')]
    folder=HERE/'.test-tmp/rendering-matrix'; folder.mkdir(parents=True,exist_ok=True)
    for name,repo,n,reducer,no_eeg in cases:
        print('Running '+name,flush=True)
        cmd=[sys.executable,'-B',__file__,'--case',name,'--repo',repo,'--channels',str(n),
             '--reducer',reducer,'--seconds',str(args.seconds)]
        if no_eeg: cmd.append('--no-eeg')
        with (folder/(name+'.log')).open('w') as log:
            result=subprocess.run(cmd,stdout=log,stderr=log,timeout=180.)
        if result.returncode: raise RuntimeError(f'{name} failed; see its log')
        print('Finished '+name,flush=True)


if __name__=='__main__': main()
