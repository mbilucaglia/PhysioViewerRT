"""Independent local LSL producer used only by the rendering validation matrix."""
import argparse
import time
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pylsl import StreamInfo,StreamOutlet,local_clock
from physiolab.synthetic import SyntheticPhysiology,SPECS


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--id',required=True)
    parser.add_argument('--origin',type=float,required=True)
    parser.add_argument('--seconds',type=float,required=True)
    parser.add_argument('--no-eeg',action='store_true')
    args=parser.parse_args()
    generator=SyntheticPhysiology(seed=2027,artifact_level='moderate')
    outlets={}; sent={}
    for kind,(rate,labels) in SPECS.items():
        if args.no_eeg and kind=='EEG': continue
        name=args.id+'-'+kind
        info=StreamInfo(name,kind,len(labels),rate,'float32',name)
        channels=info.desc().append_child('channels')
        for label in labels:
            ch=channels.append_child('channel'); ch.append_child_value('label',label)
            ch.append_child_value('unit','uV' if kind=='EEG' else 'microsiemens' if kind=='EDA' else 'a.u.')
        outlets[kind]=StreamOutlet(info)
        # Generate initial history to advance the deterministic generator state.
        generator.generate(kind,0,60*rate); sent[kind]=60*rate
    while local_clock()<args.origin+args.seconds+2.:
        elapsed=local_clock()-args.origin
        for kind,outlet in outlets.items():
            rate,_=SPECS[kind]
            target=int((max(0.,elapsed)+60.)*rate)
            if target>sent[kind]:
                data=generator.generate(kind,sent[kind],target-sent[kind])
                outlet.push_chunk(data.tolist(),args.origin-60.+(target-1)/rate)
                sent[kind]=target
        time.sleep(.005)


if __name__=='__main__': main()
