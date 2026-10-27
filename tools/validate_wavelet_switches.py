"""Native Off/Wavelet/Off reception and drawing probe with its own LSL producer."""
import os
os.environ['QT_QPA_PLATFORM']='windows'
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from pylsl import local_clock,resolve_byprop
from physiolab.gui import MainWindow
from physiolab.synthetic import SPECS


def main():
    app=QApplication([])
    token='wavelet-switch-'+uuid.uuid4().hex
    origin=local_clock()+3.
    producer=subprocess.Popen([sys.executable,'-B',str(ROOT/'tools/rendering_test_producer.py'),
        '--id',token,'--origin',str(origin),'--seconds','32'])
    with patch.object(MainWindow,'refresh',lambda self:None): window=MainWindow()
    report={'errors':[],'observations':[],'draws':{k:[] for k in SPECS}}
    connected=set()
    try:
        window.resize(1440,900); window.tabs.setCurrentWidget(window.raw_page); window.show()
        for kind,(rate,names) in SPECS.items():
            found=resolve_byprop('source_id',token+'-'+kind,minimum=1,timeout=5.)
            assert found,kind
            info=found[0]
            window.channel_metadata_cache[info.uid()]=(list(names),'')
            selector=window.selectors[kind]
            selector.blockSignals(True); selector.clear(); selector.addItem(kind,info); selector.blockSignals(False)
            window.stream_selection_changed(kind); window.connect_stream(kind)
            def draw(event,k=kind):
                renderer=window.raw_vispy_plots[k]
                tip=renderer.latest_sample_time
                report['draws'][k].append([local_clock()-origin,tip if math.isfinite(tip) else None])
            window.raw_vispy_plots[kind].canvas.events.draw.connect(draw)
        commands=[(4.,'PPG','wavelet'),(4.,'EDA','wavelet'),(22.,'PPG','off'),(25.,'EDA','off')]
        next_record=0.
        while local_clock()-origin<29.:
            elapsed=local_clock()-origin
            while commands and elapsed>=commands[0][0]:
                _,kind,method=commands.pop(0)
                choice=window.artifact_choices[kind]; choice.setCurrentIndex(choice.findData(method))
            for kind,worker in window.workers.items():
                if worker not in connected:
                    worker.failure.connect(report['errors'].append); connected.add(worker)
            app.processEvents(); time.sleep(.003)
            if elapsed>=next_record:
                record={'elapsed':elapsed,'status':window.statusBar().currentMessage(),'sources':{}}
                for kind in SPECS:
                    worker=window.workers.get(kind)
                    tip=window.raw_vispy_plots[kind].latest_sample_time
                    record['sources'][kind]={
                        'running':bool(worker and worker.isRunning()),
                        'method':getattr(worker,'preprocessing',{}).get('artifact_reduction','off'),
                        'input_tip':getattr(worker,'latest_source_timestamp',None),
                        'feedback':getattr(worker,'reduction_feedback',None),
                        'plot_tip':tip if math.isfinite(tip) else None,
                        'button':window.stream_buttons[kind].text()}
                report['observations'].append(record); next_record+=.5
        for kind in ('PPG','EDA'):
            tips=[tip for at,tip in report['draws'][kind] if 15.<at<21. and tip is not None]
            assert tips and max(tips)-min(tips)>3.,f'{kind}: no sustained Wavelet progression'
            observations=[r['sources'][kind] for r in report['observations'] if 15.<r['elapsed']<21.]
            assert all(r['running'] for r in observations),f'{kind}: reception stopped'
            assert all(r['method']=='wavelet' for r in observations),f'{kind}: Wavelet was not applied'
            tips=[tip for at,tip in report['draws'][kind] if 26.<at<29. and tip is not None]
            assert tips and max(tips)-min(tips)>1.5,f'{kind}: Off did not resume drawing'
            observations=[r['sources'][kind] for r in report['observations'] if 26.<r['elapsed']<29.]
            assert observations and all(r['running'] and r['method']=='off' for r in observations),kind
        eeg=[tip for at,tip in report['draws']['EEG'] if 15.<at<21. and tip is not None]
        assert eeg and max(eeg)-min(eeg)>3.,'Wavelet interrupted EEG drawing'
        assert not report['errors'],report['errors']
        start=time.perf_counter()
        for kind in SPECS: window.stop_stream(kind)
        report['stop_command_ms']=(time.perf_counter()-start)*1000.
        report['passed']=True
    finally:
        window.close(); app.processEvents()
        producer.terminate(); producer.wait(timeout=5.)
        output=ROOT/'.test-tmp/wavelet-switches.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2,allow_nan=False))
        print(json.dumps({k:v for k,v in report.items() if k not in ('draws','observations')},indent=2))


if __name__=='__main__': main()
