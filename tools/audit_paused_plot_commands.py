import os,sys,time,json
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='windows'
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import local_clock
from physiolab.gui import MainWindow
from physiolab.raw_display_state import RawDisplayState
app=QApplication([])
with patch.object(MainWindow,'refresh',lambda self:None):w=MainWindow()
report={}
try:
    w.resize(1440,900);w.tabs.setCurrentWidget(w.raw_page);w.show();app.processEvents()
    fs=128.;t=np.arange(5*128)/fs;values=np.sin(2*np.pi*1.2*t)[:,None]
    w.receive('PPG',values,values,['PPG'],None,fs,local_clock()-5.+t)
    deadline=time.monotonic()+3.
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
        if 'PPG' in w.raw_display.frames and not w.raw_display.inflight:break
    report['initial_backend']=w.raw_renderer_mode
    report['has_prepared_frame']='PPG' in w.raw_display.frames
    w.set_plot_paused('raw',True)
    w.raw_renderer_choice.setCurrentIndex(0)
    deadline=time.monotonic()+.3
    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    report['paused_backend_switch']={'CPU_curve_count':len(w.curves['PPG']),
        'prepared_frame_available':'PPG' in w.raw_display.frames,'dirty':w.raw_display.dirty,
        'display_paused':w.raw_display.paused}
    old_range=w.plots['PPG'].viewRange()[0]
    w.raw_time_window.setCurrentIndex(w.raw_time_window.findData(10))
    deadline=time.monotonic()+.3
    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    new_range=w.plots['PPG'].viewRange()[0]
    report['paused_timebase']={'old_plot_seconds':old_range[1]-old_range[0],
        'requested_seconds':w.raw_display.view_seconds,'actual_plot_seconds':new_range[1]-new_range[0]}
finally:
    w.close();app.processEvents()

state=RawDisplayState();x=np.zeros((10,1));state.append('PPG',x,x,['PPG'],10.,100.+np.arange(10)/10.,received_at=0.)
for i in range(61):state.advance(i/30.)
state.append('PPG',x,x,['PPG'],10.,120.+np.arange(10)/10.,received_at=20.)
state.advance(20.)
first=state.origin+state.viewport('PPG')[1]
for i in range(1,61):state.advance(20.+i/30.)
later=state.origin+state.viewport('PPG')[1]
report['source_gap_recovery']={'newest_sample':120.9,'viewport_head_after_new_input':first,
    'viewport_head_two_seconds_later':later,'remaining_lag_seconds':120.9-later}
out=root/'.test-tmp/rendering-audit/ui-probes.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
