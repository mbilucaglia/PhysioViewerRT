"""Authoritative, bounded paired samples and acquisition-start references.

The first 250 ms worth of real samples define the startup reference, independently
of packet size. This is within the existing presentation buffer and latches once.
Snapshots share read-only arrays; pause retains at most one extra bounded history.
"""
from collections import deque
import numpy as np
from .raw_timing import clean_lsl_chunk
from .render_policy import RAW_DISPLAY_POLICY


class SignalHistory:
    # Hard byte bound per source, in addition to source-time retention.
    MAX_BYTES = 64 * 1024 * 1024
    REFERENCE_SECONDS = .25

    def __init__(self, seconds, modalities):
        self.seconds = seconds
        self.chunks = {kind: deque() for kind in modalities}
        self.last_sample = {}
        self.references = {}
        self.center_traces = {}
        self.generations = dict.fromkeys(modalities, 0)

    def reset(self, kind):
        self.chunks[kind].clear()
        self.last_sample.pop(kind, None)
        self.references.pop(kind, None)
        self.center_traces.pop(kind, None)
        self.generations[kind] += 1

    def append(self, kind, raw, filtered, names, fs, timestamps, center_trace):
        t, x, y = clean_lsl_chunk(timestamps, raw, filtered, self.last_sample.get(kind))
        if not len(t): return None
        original_times=t
        if kind not in self.references:
            self.center_traces.setdefault(kind, center_trace)
            previous = self.chunks[kind]
            count=max(2,int(np.ceil(float(fs)*self.REFERENCE_SECONDS)))
            a = np.concatenate([c[1][:count] for c in previous] + [x[:count]])[:count]
            b = np.concatenate([c[2][:count] for c in previous] + [y[:count]])[:count]
            if len(a) == count:
                if kind in ('PPG','EDA'):
                    centers = np.stack((np.median(a,axis=0),np.median(b,axis=0)))
                    extent = np.maximum(np.max(np.abs(a-centers[0]),axis=0),
                                        np.max(np.abs(b-centers[1]),axis=0))
                    scales = np.maximum(extent/RAW_DISPLAY_POLICY.fit_target,1e-9)
                else:
                    centers = np.median(b if self.center_traces[kind]=='filtered' else a,axis=0)
                    scales = np.maximum(np.std(a,axis=0),np.maximum(np.max(np.abs(a),axis=0)*1e-6,1e-9))
                self.set_reference(kind, centers, scales)
        self.last_sample[kind] = float(t[-1])
        cutoff = t[-1]-self.seconds
        first = int(np.searchsorted(t,cutoff))
        # Slice oversized packets before copying retained arrays.
        max_samples = max(2,self.MAX_BYTES//(8*(1+2*x.shape[1])))
        first = max(first,len(t)-max_samples)
        t,x,y = (np.array(v[first:],copy=True) for v in (t,x,y))
        for v in (t,x,y): v.setflags(write=False)
        chunks = self.chunks[kind]
        # Small transport packets must not create an unbounded Python-object
        # overhead. Immutable block replacement keeps outstanding snapshots safe.
        if chunks and len(chunks[-1][0])<512 and len(t)<512:
            previous=chunks.pop()
            t,x,y=(np.concatenate((a,b)) for a,b in zip(previous[:3],(t,x,y)))
            for v in (t,x,y): v.setflags(write=False)
        # Fixed blocks bound both object overhead and work when pruning the
        # leading partial block. A replay-sized packet must not be recopied
        # in its entirety on each subsequent ingress tick.
        for start in range(0,len(t),512):
            parts=[v[start:start+512].copy() for v in (t,x,y)]
            for v in parts: v.setflags(write=False)
            chunks.append((*parts,tuple(names),float(fs)))
        while chunks and chunks[0][0][-1] < cutoff: chunks.popleft()
        if chunks and chunks[0][0][0] < cutoff:
            c=chunks.popleft(); start=int(np.searchsorted(c[0],cutoff))
            parts=[v[start:].copy() for v in c[:3]]
            for v in parts: v.setflags(write=False)
            chunks.appendleft((*parts,c[3],c[4]))
        total=sum(sum(v.nbytes for v in c[:3]) for c in chunks)
        while len(chunks)>1 and total>self.MAX_BYTES:
            c=chunks.popleft(); total-=sum(v.nbytes for v in c[:3])
        return original_times

    def set_reference(self, kind, centers, scales):
        centers,scales=np.array(centers,copy=True),np.array(scales,copy=True)
        centers.setflags(write=False); scales.setflags(write=False)
        self.references[kind]=(centers,scales)

    def reference(self,kind,count):
        ref=self.references.get(kind)
        if ref is None: return None
        centers,scales=ref
        return (centers[:,:count] if centers.ndim==2 else centers[:count],scales[:count])
