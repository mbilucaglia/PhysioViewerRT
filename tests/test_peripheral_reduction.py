"""Numerical algorithms, timestamps and waveform preservation for peripheral reducers."""
import unittest
from unittest.mock import patch
import numpy as np
from scipy.stats import laplace
from physiolab.peripheral_reduction import (PeripheralReducer,hampel_block,
    laplace_limit,sure_threshold,ppg_wavelet_block,sc_wavelet_block)
from physiolab.processing import Processor
from physiolab.processing_filters import validate_preprocessing
from physiolab.metric_observation import source_configuration

class PeripheralReductionTests(unittest.TestCase):
    def test_sure_matches_direct_risk_minimization_and_scaling(self):
        values = np.array([-.1,.2,.4,1.3,-2.7,3.])
        candidates = np.sort(np.abs(values))
        risk = [len(values)+sum(min(v*v,t*t) for v in values)
                -2*sum(abs(v)<=t for v in values) for t in candidates]
        expected = candidates[np.argmin(risk)]
        self.assertAlmostEqual(sure_threshold(values,1.),expected)
        self.assertAlmostEqual(sure_threshold(values*4.,4.),expected*4.)

    def test_laplace_threshold_has_correct_tail_probability_and_order(self):
        coefficients = np.array([[-1.,-2.],[1.,2.],[-2.,-4.],[2.,4.]])
        scale = np.mean(np.abs(coefficients),axis=0)
        limit = laplace_limit(coefficients,.1)
        self.assertTrue(np.all(limit > 0))
        np.testing.assert_allclose(2*laplace.sf(limit,scale=scale),.1,rtol=1e-12)

    def test_hampel_repairs_isolated_spike_and_preserves_monotonic_sc(self):
        clean = np.arange(32,dtype=float)[:,None]*.01+3.
        noisy = clean.copy();noisy[15] += 5.
        repaired = hampel_block(noisy)
        self.assertLess(abs(repaired[15,0]-clean[15,0]),.02)
        np.testing.assert_allclose(hampel_block(clean)[3:-3],clean[3:-3])
        self.assertEqual(noisy[15,0],clean[15,0]+5.)

    def fixture(self,kind,fs,seconds=16):
        t = np.arange(round(fs*seconds))/fs
        rng = np.random.default_rng(2)
        clean = (np.sin(2*np.pi*1.2*t)+.2*np.sin(2*np.pi*2.4*t)
                 if kind=='PPG' else 3.+.05*np.sin(.4*t))
        noisy = clean+rng.normal(0,.12 if kind=='PPG' else .02,len(t))
        noisy[round(4*fs):round(4*fs)+2] += 3.
        return t,clean,noisy[:,None]

    def test_injected_artifact_error_reduced_without_deleting_waveform_samples(self):
        for kind,fs in [('PPG',128.),('EDA',32.)]:
            times,clean,noisy = self.fixture(kind,fs)
            for method in ('hampel','wavelet'):
                reducer = PeripheralReducer(kind,fs,1,method)
                raw,out,stamps = reducer.push(noisy,times)
                n = len(out)
                self.assertLess(np.mean((out[:,0]-clean[:n])**2),np.mean((noisy[:n,0]-clean[:n])**2))
                np.testing.assert_array_equal(raw,noisy[:n])
                np.testing.assert_array_equal(stamps,times[:n])
                self.assertEqual(len(out),len(raw))

    def test_transport_independence_and_bounded_context(self):
        for kind,fs in [('PPG',128.),('EDA',32.)]:
            times,_,noisy = self.fixture(kind,fs)
            for method in ('hampel','wavelet'):
                expected = PeripheralReducer(kind,fs,1,method).push(noisy,times)
                reducer = PeripheralReducer(kind,fs,1,method)
                received = [reducer.push(noisy[i:i+17],times[i:i+17]) for i in range(0,len(times),17)]
                for field in range(3):
                    np.testing.assert_allclose(np.concatenate([x[field] for x in received]),expected[field],atol=1e-12)
                self.assertLessEqual(len(reducer.raw),round(9*fs))

    def test_delay_is_explicit_and_warmup_does_not_fabricate_samples(self):
        for method in ('hampel','wavelet'):
            reducer = PeripheralReducer('EDA',32.,1,method)
            raw,processed,stamps = reducer.push(np.ones((6,1))*3.,np.arange(6)/32.)
            self.assertEqual(len(processed),0)
            if method=='wavelet':
                raw,processed,stamps = reducer.push(np.ones((250,1))*3.,np.arange(6,256)/32.)
                self.assertEqual(len(processed),256)
                np.testing.assert_allclose(processed,3.,atol=1e-12)
                np.testing.assert_array_equal(stamps,np.arange(256)/32.)

    def test_processor_preserves_raw_and_aligns_live_baseline_timestamps(self):
        for method in ('hampel','wavelet'):
            times,_,data = self.fixture('EDA',32.)
            settings = {'notch':False,'artifact_reduction':method}
            expected = PeripheralReducer('EDA',32.,1,method).push(data,times)
            proc = Processor('EDA',32.,1,['SC'],preprocessing=settings)
            raw,clean,stamps = [],[],[]
            for i in range(0,len(data),16):
                proc.push(data[i:i+16],timestamps=times[i:i+16])
                raw.append(proc.last_raw_chunk);clean.append(proc.last_filtered_chunk);stamps.append(proc.last_timestamps)
            np.testing.assert_array_equal(proc.raw,data)
            for result,target in zip((raw,clean,stamps),expected):
                np.testing.assert_allclose(np.concatenate(result),target,atol=1e-12)

    def test_timestamp_gap_resets_reconstruction_and_filter_history(self):
        proc = Processor('EDA',32.,1,['SC'],preprocessing={'notch':False,'artifact_reduction':'wavelet'})
        proc.push(np.ones((256,1))*3.,timestamps=np.arange(256)/32.)
        self.assertEqual(len(proc.last_filtered_chunk),256)
        proc.push(np.ones((16,1))*4.,timestamps=10.+np.arange(16)/32.)
        self.assertEqual(len(proc.last_filtered_chunk),0)
        self.assertEqual(len(proc.filtered),0)

    def test_pipeline_metadata_distinguishes_modes_and_disallows_eeg_reducer(self):
        ordinary = source_configuration('EDA',32.,['SC'],{},None,['uS'])
        changed = source_configuration('EDA',32.,['SC'],{'artifact_reduction':'wavelet'},None,['uS'])
        self.assertNotEqual(ordinary,changed)
        self.assertEqual(validate_preprocessing('EDA'),{'preset':'default','notch':True})
        with self.assertRaises(ValueError):
            validate_preprocessing('EEG',artifact_reduction='wavelet')

    def test_clean_pulse_timing_and_tonic_level_preservation_are_measured(self):
        from scipy.signal import find_peaks
        fs=128.;t=np.arange(24*128)/fs
        pulse=np.sin(2*np.pi*1.2*t)+.2*np.sin(2*np.pi*2.4*t)
        for method in ('hampel','wavelet'):
            _,out,_=PeripheralReducer('PPG',fs,1,method).push(pulse[:,None],t)
            a=find_peaks(pulse[:len(out)],distance=.5*fs)[0]
            b=find_peaks(out[:,0],distance=.5*fs)[0]
            self.assertEqual(len(a),len(b))
            self.assertLessEqual(np.max(np.abs(a-b))/fs,1/fs)
            if method=='hampel':
                np.testing.assert_array_equal(out[:,0],pulse[:len(out)])
        constant=np.ones((16*32,1))*3.2
        _,out,_=PeripheralReducer('EDA',32.,1,'wavelet').push(constant,np.arange(len(constant))/32.)
        np.testing.assert_allclose(out,3.2,atol=1e-12)

    def test_bsl_passes_only_emitted_waveform_timestamps_to_decomposition(self):
        from physiolab.calibration import analyze_bsl
        times,_,data = self.fixture('EDA',32.,seconds=16.5)
        for method in ('hampel','wavelet'):
            expected = PeripheralReducer('EDA',32.,1,method).push(data,times)
            with patch('physiolab.sc_decomposition.decompose_baseline',return_value=[]) as decomposition:
                analyze_bsl({'EDA':{'data':data,'timestamps':times,'fs':32.,'channels':['SC'],
                    'preprocessing':{'notch':False,'artifact_reduction':method}}})
            actual,timestamps,fs = decomposition.call_args.args
            np.testing.assert_allclose(actual,expected[1],atol=1e-12)
            np.testing.assert_array_equal(timestamps,expected[2])
