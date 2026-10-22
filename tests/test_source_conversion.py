import unittest
from unittest.mock import Mock, patch

import numpy as np

from physiolab.source_conversion import SourceConversion


class SourceConversionTests(unittest.TestCase):
    def test_affine_conversion_is_applied_to_all_channels_without_mutating_input(self):
        source = np.array([[100., 200.], [300., 400.]])
        original = source.copy()
        conversion = SourceConversion(.01, -1., 'µS')
        np.testing.assert_allclose(conversion.apply(source), [[0., 1.], [2., 3.]])
        np.testing.assert_array_equal(source, original)
        self.assertEqual(conversion.units(['µV', 'µV']), ['µS', 'µS'])
        self.assertEqual(SourceConversion().units(['µV', '']), ['µV', ''])

    def test_nonfinite_parameters_and_overflow_are_rejected(self):
        for invalid in (float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                SourceConversion(gain=invalid)
            with self.assertRaises(ValueError):
                SourceConversion(offset=invalid)
        with self.assertRaises(ValueError):
            SourceConversion(gain=1e300).apply(np.array([[1e300]]))

    def test_receiver_delivers_converted_samples_and_calculates_metrics_from_them(self):
        from pylsl import StreamInfo
        from physiolab.worker import Receiver
        info = StreamInfo('conversion-test', 'EDA', 1, 32., 'float32', 'conversion-test')
        info.desc().append_child('channels').append_child('channel').append_child_value('unit', 'µV')
        conversion = SourceConversion(.01, 3., 'µS')
        receiver = Receiver(info, 'EDA', [0], ['EDA'], conversion=conversion)
        values = np.full((128, 1), 200.)
        inlet = Mock()
        inlet.info.return_value = info
        def pull(**_):
            receiver.active = False
            return values.tolist(), (100. + np.arange(128)/32.).tolist()
        inlet.pull_chunk.side_effect = pull
        failures = []
        receiver.failure.connect(failures.append)
        with patch('physiolab.worker.StreamInlet', return_value=inlet) as constructor:
            receiver.run()
        from pylsl import proc_clocksync
        constructor.assert_called_once_with(info, max_buflen=30, processing_flags=proc_clocksync)
        self.assertFalse(failures)
        chunk, = receiver.mailbox.drain()
        np.testing.assert_allclose(chunk.raw, 5.)
        self.assertAlmostEqual(chunk.metric['SCL'], 5., places=3)
        self.assertEqual(receiver.source_units, ['µV'])
        self.assertEqual(receiver.output_units, ['µS'])
        inlet.close_stream.assert_called_once()
