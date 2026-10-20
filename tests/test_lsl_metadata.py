"""LSL discovery supplies short info; inlet.info() supplies full channel labels."""
import sys
import types
import unittest
from unittest.mock import patch
from physiolab.channel_selection import full_channel_labels, channel_labels


class FakeNode:
    def __init__(self, label=None, sibling=None):
        self.label = label
        self.sibling = sibling

    def child(self, name):
        return self

    def child_value(self, name):
        return self.label if name == 'label' else ''

    def next_sibling(self):
        return self.sibling or FakeNode()


class FakeInfo:
    def __init__(self, labels):
        self.labels = labels

    def channel_count(self):
        return len(self.labels)

    def desc(self):
        node = FakeNode()
        for label in reversed(self.labels):
            node = FakeNode(label, node)
        return node


class MetadataTests(unittest.TestCase):
    def test_discovery_info_is_unlabeled_full_inlet_info_is_labeled(self):
        short = FakeInfo(['', '', ''])
        full = FakeInfo(['F3', 'F4', 'O1'])
        self.assertTrue(all('unlabeled' in x for x in channel_labels(short)))
        calls = []
        class FakeInlet:
            def __init__(self, info, max_buflen):
                calls.append(('opened', info, max_buflen))
            def info(self, timeout):
                calls.append(('full_info', timeout))
                return full
            def close_stream(self):
                calls.append(('closed',))
        with patch.dict(sys.modules, {'pylsl': types.SimpleNamespace(StreamInlet=FakeInlet)}):
            names, warning = full_channel_labels(short)
        self.assertEqual(names, ['F3', 'F4', 'O1'])
        self.assertEqual(warning, '')
        self.assertEqual(calls[-1], ('closed',))

    def test_missing_publisher_names_remain_explicitly_unlabeled(self):
        short = FakeInfo(['', ''])
        class FakeInlet:
            def __init__(self, info, max_buflen):
                pass
            def info(self, timeout):
                return short
            def close_stream(self):
                pass
        with patch.dict(sys.modules, {'pylsl': types.SimpleNamespace(StreamInlet=FakeInlet)}):
            names, warning = full_channel_labels(short)
        self.assertEqual(names, ['Ch1 (unlabeled)', 'Ch2 (unlabeled)'])
        self.assertIn('2 of 2', warning)


if __name__ == '__main__':
    unittest.main()
