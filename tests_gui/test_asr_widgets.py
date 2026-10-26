"""Designer contains the static controls and icons; ASR exposes only threshold."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import unittest
from PySide6.QtCore import QCoreApplication, QDir, QEvent
from PySide6.QtTest import QTest
from PySide6.QtUiTools import QUiLoader
from PySide6 import QtSvg
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QToolButton, QWidget
from physiolab.asr_widgets import ASRControls


class ASRWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = Path(__file__).resolve().parents[1]/'designer'
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(folder)))
        self.form = loader.load(str(folder/'PhysioViewerRT_ClinicalLayout.ui'))
        self.view = ASRControls(self.form.findChild(QFrame, 'EEGASRPanel'))

    def tearDown(self):
        self.form.close()
        self.form.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def baseline(self):
        self.view.set_source(True, has_training=True)

    def test_enable_requires_a_successful_fit_from_compatible_training(self):
        self.assertFalse(self.view.enable.isEnabled())
        self.baseline()
        self.assertFalse(self.view.enable.isEnabled())
        self.view.set_fit_state(fitted=True)
        self.assertTrue(self.view.enable.isEnabled())
        self.assertFalse(self.view.enable.isChecked())

    def test_threshold_changes_are_coalesced_and_request_automatic_fitting(self):
        requested = []
        self.view.fit_requested.connect(requested.append)
        self.view.cutoff.setValue(21.)
        QTest.qWait(450)
        self.assertFalse(requested, 'No training recording must mean no ASR fit')
        self.baseline()
        for value in (22., 23., 25.):
            self.view.cutoff.setValue(value)
        QTest.qWait(500)
        self.assertEqual(requested, [{'cutoff':25.}])

    def test_fitting_disables_threshold_until_completion(self):
        self.baseline()
        self.view.set_fit_state(busy=True)
        self.assertFalse(self.view.cutoff.isEnabled())
        self.assertFalse(self.view.enable.isEnabled())
        self.view.set_fit_state(fitted=True)
        self.assertTrue(self.view.cutoff.isEnabled())

    def test_asr_is_in_sources_with_no_separate_page_or_preview(self):
        self.assertIsNone(self.form.findChild(QWidget, 'asrTab'))
        source = self.form.findChild(QWidget, 'sourcesTab')
        self.assertIs(source.findChild(QFrame,'EEGASRPanel'), self.view.panel)
        self.assertEqual(self.view.settings(), {'cutoff':20.})

    def test_icons_exist_in_unmodified_designer_preview(self):
        for name, kind in (('EEGASRTrain',QPushButton),('EEGPlay',QPushButton),('EEGRefresh',QPushButton),
                           ('rawPlotPause',QPushButton),('metricsPlotPause',QPushButton),
                           ('EEGExpand',QToolButton),('EEGAutoscale',QToolButton)):
            button = self.form.findChild(kind,name)
            self.assertFalse(button.icon().isNull(), name)
            self.assertFalse(button.icon().pixmap(16,16).isNull(), name)
        self.assertFalse(self.form.windowIcon().isNull())


    def test_each_modality_has_designer_processing_panel(self):
        from PySide6.QtWidgets import QGroupBox, QComboBox
        for kind in ('EEG', 'PPG', 'EDA'):
            panel = self.form.findChild(QGroupBox, f'{kind}ProcessingPanel')
            self.assertEqual(panel.title(), 'Processing')
            self.assertIsNotNone(panel.findChild(QComboBox, f'{kind}FilterPreset'))
        panel = self.form.findChild(QGroupBox, 'EEGProcessingPanel')
        self.assertIs(panel.findChild(QFrame, 'EEGASRPanel'), self.view.panel)

    def test_channel_checkboxes_stay_open_and_preserve_selection_rules(self):
        from PySide6.QtCore import Qt, QPoint
        from physiolab.desktop_widgets import CheckChannelDropdown
        for kind in ('EEG', 'PPG', 'EDA'):
            picker = CheckChannelDropdown(kind)
            try:
                picker.set_channels(['F3', 'F4', 'O1'])
                picker.menu.popup(QPoint(50, 50))
                QTest.qWait(30)
                for index in (1, 2):
                    QTest.mouseClick(picker.actions[index], Qt.MouseButton.LeftButton)
                    self.assertTrue(picker.menu.isVisible())
                self.assertEqual(picker.selected_indices(), [0] if kind == 'EEG' else [2])
                QTest.keyClick(picker.actions[2], Qt.Key.Key_Escape)
                self.assertFalse(picker.menu.isVisible())
            finally:
                picker.menu.close()
                picker.deleteLater()
