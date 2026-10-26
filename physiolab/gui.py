"""Local two-tab biosignal monitor: waveforms and metrics."""
import os
import importlib.util
import time
from pathlib import Path
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt, QDir
from PySide6.QtUiTools import QUiLoader
from pylsl import local_clock
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGridLayout, QTabWidget, QCheckBox,
    QMessageBox, QFileDialog, QDialog, QPlainTextEdit, QToolButton,
    QScrollArea, QSizePolicy, QApplication, QStackedWidget, QSplitter, QDoubleSpinBox, QFrame, QStatusBar, QSpinBox,
    QProgressDialog, QMenu
)
from .worker import Receiver
from .processing import validate_preprocessing
from .channel_selection import validated_indices
from .lsl_tasks import LSLTask
from .metric_display import prepare_metric_curve, metric_amplitude_label
from .scale_rulers import ScaleRuler
from .branding import apply_window_branding
from .modality_labels import modality_label
from .raw_render_worker import RawRenderWorker
from .raw_snapshot import build_raw_source
from .vispy_raw import VisPyRawPlot
from .vispy_metrics import VisPyMetricPlot
from .performance import PerformanceMonitor
from .settings import DEFAULT_VIEWER_SETTINGS
from .metric_catalog import DEFAULT_METRICS, validate_metrics, metric_color
from .metric_widgets import build_metric_toggles, build_metric_readouts
from .display_units import DEFAULT_EEG_DISPLAY_STEP, ARBITRARY_UNIT
from .raw_display_state import RawDisplayState
from .metric_state import MetricState
from .calibration_session import CalibrationSession
from .calibration_tasks import CalibrationAnalysisTask
from .affect_state import AffectState
from .affect_widgets import AffectView
from .asr_widgets import ASRControls
from .asr_quality import training_report
from .panel_arrangement import PanelArrangement
from .flow_layout import install_designer_flows, install_flow, fit_scroll_page, AdaptiveRawWorkspace
from .ui_icons import set_action, set_panel_expanded, set_view_paused
from .asr_session import ASRSession
from .asr_runtime import asr_runtime_state
from .peripheral_runtime import peripheral_runtime_state
from .asr_training import ASRTrainingAccumulator
from .asr_training_dialog import ASRTrainingDialog
from .asr_tasks import ASRFitTask, CalibrationReferenceTask
from .render_policy import RAW_DISPLAY_POLICY
from .desktop_widgets import CheckChannelDropdown, CalibrationScreen, ResponsiveSources
from .source_conversion_widgets import SourceConversionControls
from .amplitude_display import visible_gain
from .calibration import (
    analyze_eyc, analyze_bsl, save_calibration, load_calibration,
    DURATION_SECONDS,
)


class MainWindow(QMainWindow):

    def __init__(self, settings=DEFAULT_VIEWER_SETTINGS, metric_definitions=DEFAULT_METRICS):
        super().__init__()
        self.settings = settings
        self.raw_display = RawDisplayState(settings)
        self.metric_definitions = validate_metrics(metric_definitions)
        self.metric_state = MetricState(self.metric_definitions, settings.metric_history_capacity)
        self.asr_session = ASRSession()
        self.asr_tasks = []
        self._asr_report_dialog = None
        self._asr_report_generation = None
        self.eeg_reference_tasks = []
        self.eeg_reference_pending = False
        self.eeg_reference_error = None
        self.eyc_recording = None
        self._reference_source_configuration = None
        self._asr_resume_after_fit = False
        self.affect_state = AffectState(max_points=settings.metric_history_capacity,
                                        history_seconds=settings.history_seconds)
        self._affect_clock_offset = local_clock() - time.monotonic()
        self._affect_clear_before = float('-inf')
        self._tonic_live_configuration = None
        self.setWindowTitle('PhysioViewerRT — local LSL monitor')
        self.resize(1450, 940)
        # All geometry, tabs, control placement and palette come from
        # designer/PhysioViewerRT_ClinicalLayout.ui. Code below only attaches
        # application state and live rendering widgets to named hosts.
        self.selectors, self.channel_selectors, self.workers = {}, {}, {}
        self.stream_buttons = {}
        self.pending_source_changes = set()
        self.source_change_timers = {}
        self.channel_metadata_cache = {}
        self.lsl_tasks = {}
        self._metadata_requests = {}
        self.lsl_task_serial = 0
        self.discovery_serial = 0
        self._closing = False
        self.performance = PerformanceMonitor()
        self._last_gui_tick = time.monotonic()
        self.plots, self.curves = {}, {}
        self.raw_plot_stacks = {}
        self.raw_vispy_plots = {}
        self.raw_renderer_mode = 'pyqtgraph'
        self.raw_vertical_gains = {}
        self.raw_autoscale_buttons = {}
        self.metric_dirty = True
        self.metric_presentation_epoch = 0
        self.metric_renderer_mode = 'pyqtgraph'
        self.vispy_metric_plot = None
        self.metric_gl_bounds = (-settings.default_view_seconds, 0.)
        self.metric_labels, self.metric_status = {}, {}
        self.metric_ruler_keys = set()
        self.capture = None
        self.loaded_eyc = None
        self.loaded_bsl = None
        self.calibration_paths = {'EYC': None, 'BSL': None}
        self.metric_plot_origin = time.monotonic()
        self.metric_view_seconds = settings.default_view_seconds
        self.metric_follow_live = True
        self.iaf_hz = 10.0
        self._load_designer_layout()
        self._connect_designer_controls()
        self._connect_affect_view()
        self._connect_asr_view()
        self._connect_metric_workspace()
        install_designer_flows(self)
        for scroll in self.findChildren(QScrollArea):
            if scroll.property("fitViewport"):
                fit_scroll_page(scroll)
        self._raw_workspace = AdaptiveRawWorkspace(
            self._required_ui("rawDataTabScroll", QScrollArea).viewport(), self.raw_plot_splitter)
        self.update_metrics_availability()
        # Raw data reduction runs off the GUI thread; painting remains here.
        # Prefer GPU on normal desktop sessions when the optional VisPy
        # package is installed. Offscreen CI retains the original backend.
        if (os.environ.get('QT_QPA_PLATFORM', '').lower() != 'offscreen'
                and importlib.util.find_spec('vispy') is not None):
            self.raw_renderer_choice.setCurrentIndex(1)
            self.metric_renderer_choice.setCurrentIndex(1)

        self.raw_render_worker = RawRenderWorker(self)
        self.raw_render_worker.frame_ready.connect(self.apply_raw_frame)
        self.raw_render_worker.start()

        self.statusBar().showMessage('Start an LSL source, then press Refresh LSL.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render_frame)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.start(settings.timer_interval_ms)
        self.refresh()

    def _required_ui(self, name, widget_type):
        widget = self.centralWidget().findChild(widget_type, name)
        if widget is None:
            raise RuntimeError(
                f'Qt Designer layout is missing required {widget_type.__name__} '
                f'widget "{name}". Restore its objectName in the .ui file.'
            )
        return widget

    def _load_designer_layout(self):
        """Load the saved Qt Designer design on every application startup."""
        path = Path(__file__).resolve().parent.parent / 'designer' / 'PhysioViewerRT_ClinicalLayout.ui'
        if not path.is_file():
            raise FileNotFoundError(f'Editable Qt Designer interface not found: {path}')
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(path.parent)))
        self._ui_form = loader.load(str(path))
        if self._ui_form is None:
            raise RuntimeError(f'Qt Designer could not load {path}')
        self.setCentralWidget(self._ui_form.takeCentralWidget())
        self.setStatusBar(QStatusBar(self))
        # Calibration actions are in Sources; no unused menu strip above tabs.
        self.menuBar().setVisible(False)
        self.setStyleSheet(self._ui_form.styleSheet())
        apply_window_branding(self)
        self.tabs = self._required_ui('mainTabs', QTabWidget)
        self.sources_page = self._required_ui('sourcesTab', QWidget)
        self._responsive_sources = ResponsiveSources(self._required_ui('sourcesScroll', QScrollArea))
        self.raw_page = self._required_ui('rawDataTab', QWidget)
        self.metrics_page = self._required_ui('metricsTab', QWidget)
        self.affect_page = self._required_ui('affectTab', QWidget)
        self.tabs.currentChanged.connect(self.tab_changed)
        # Never hard-code tab positions: Qt Designer may reorder the pages.
        # Keep their titles and layout exactly as saved in the .ui file.
        if any(self.tabs.indexOf(page) < 0 for page in
               (self.sources_page, self.raw_page, self.metrics_page, self.affect_page)):
            raise RuntimeError('Qt Designer mainTabs must contain all four pages')

    def _connect_asr_view(self):
        self.asr_view = ASRControls(self._required_ui('EEGASRPanel', QFrame))
        self.asr_view.train_requested.connect(self.train_eeg_asr)
        self.asr_view.report_requested.connect(self.show_asr_training_report)
        self.asr_view.train.setText(f'Train (auto · ≥{self.settings.asr_training_seconds:g} s)')
        self.asr_view.fit_requested.connect(self.fit_eeg_asr)
        self.asr_view.enabled_changed.connect(self.set_eeg_asr_enabled)
        self.update_asr_availability()

    def update_asr_availability(self):
        if not hasattr(self, 'asr_view'):
            return
        worker = self.workers.get('EEG')
        live = getattr(worker, 'source_configuration', None)
        source_ok, source_status = self.asr_session.source_availability(
            live if getattr(worker, 'active', False) else None)
        available, status, _ = self.asr_session.availability(live)
        self.asr_view.set_source(source_ok, source_status or status, available)
        model = self.asr_session.model
        fitted = (model is not None and available and source_ok
                  and all(getattr(model.settings, key) == value
                          for key, value in self.asr_view.settings().items()))
        self.asr_view.set_fit_state(fitted, self.asr_session.busy or self.capture is not None)
        self.asr_view.set_enabled(self.asr_session.enabled and fitted)
        self.asr_view.report.setEnabled(model is not None and not self.asr_session.busy)

    def train_eeg_asr(self):
        worker = self.workers.get('EEG')
        live = getattr(worker, 'source_configuration', None)
        available, status = self.asr_session.source_availability(
            live if getattr(worker, 'active', False) else None)
        if not available or self.capture is not None or self.asr_session.busy:
            self.statusBar().showMessage(status or 'Finish the current recording or training first.')
            return
        minimum = self.settings.asr_training_seconds
        metadata = {'fs': float(worker.info.nominal_srate()),
                    'channels': list(worker.selected_names),
                    'preprocessing': dict(worker.preprocessing),
                    'conversion': worker.conversion.metadata(),
                    'source_units': list(worker.source_units), 'units': list(worker.output_units),
                    'start_lsl_timestamp': worker.latest_source_timestamp}
        started = time.monotonic()
        session = CalibrationSession('ASR', {'EEG': metadata}, started+300.)
        monitor = ASRTrainingAccumulator(metadata['fs'], metadata['channels'], max(180., minimum+60.))
        progress = ASRTrainingDialog(minimum, self)
        fit = {'running': False, 'next': minimum, 'error': '', 'model': None, 'eeg': None}
        settings = self.asr_view.settings()
        cancelled = False

        def checked(generation, model, error):
            fit['running'] = False
            if cancelled or self._closing:
                return
            if error is not None:
                fit['error'] = error
                fit['next'] = monitor.status()['accepted_seconds']+10.
            else:
                fit['model'] = model
                progress.accept()

        def advance():
            status = monitor.status()
            now = time.monotonic()
            progress.show_status(status, now-started, fit['running'], fit['error'])
            if (self._closing or session.errors or not worker.active
                    or self.workers.get('EEG') is not worker
                    or now > session.deadline):
                progress.reject()
                return
            if (not fit['running'] and fit['next'] > status['accepted_seconds']
                    and monitor.accepted_samples >= monitor.maximum_samples):
                progress.reject()
                return
            if (not fit['running'] and status['accepted_seconds'] >= fit['next']):
                eeg = monitor.snapshot(metadata)
                task = ASRFitTask(0, eeg, settings, self)
                fit.update(running=True, eeg=eeg)
                self.asr_tasks.append(task)
                task.completed.connect(checked)
                task.finished.connect(lambda t=task: self._asr_task_finished(t))
                task.start()

        self.capture = session
        worker.asr_training_monitor = monitor
        self.update_asr_availability()
        timer = QTimer(progress)
        timer.setInterval(100)
        timer.timeout.connect(advance)
        timer.start()
        try:
            result = progress.exec()
        finally:
            cancelled = True
            timer.stop()
            worker.asr_training_monitor = None
            self.capture = None
            self.update_asr_availability()
            for kind in tuple(self.pending_source_changes):
                self.schedule_source_change(kind)
        if result != QDialog.DialogCode.Accepted or self._closing or fit['model'] is None:
            reason = fit['error'] or ('; '.join(session.errors)) or monitor.status()['reason']
            self.statusBar().showMessage('ASR training not completed; previous model kept. '+reason)
            return
        if self.asr_session.enabled:
            self.set_eeg_asr_enabled(False)
        if self._asr_report_dialog is not None:
            self._asr_report_dialog.close()
        self.asr_session.set_training(fit['eeg'])
        self._asr_resume_after_fit = True
        self.eeg_asr_fitted(self.asr_session.generation, fit['model'], None)

    def fit_eeg_asr(self, settings, enable_on_success=False):
        live = getattr(self.workers.get('EEG'), 'source_configuration', None)
        available, status, _ = self.asr_session.availability(live)
        if not available or self.asr_session.busy or self.capture is not None:
            self.asr_view.set_fit_state(False, self.asr_session.busy, status or 'Finish recording first.')
            return
        if self.asr_session.model is not None:
            try:
                old = self.asr_session.model
                if any(getattr(old.settings, key) != value for key, value in settings.items() if key != 'cutoff'):
                    raise ValueError('Changing ASR calibration settings requires a new training recording')
                updated = old.with_cutoff(settings.get('cutoff', old.settings.cutoff))
            except ValueError as exc:
                self.asr_view.cutoff.blockSignals(True)
                self.asr_view.cutoff.setValue(old.settings.cutoff)
                self.asr_view.cutoff.blockSignals(False)
                self.update_asr_availability()
                self.statusBar().showMessage(str(exc))
                return
            self.asr_session.model = updated
            self.asr_session.cleaned_analysis = None
            if updated is not old:
                self._apply_asr_metric_references()
                if self.asr_session.enabled:
                    self.schedule_source_change('EEG')
            if enable_on_success and not self.asr_session.enabled:
                self.set_eeg_asr_enabled(True)
            self.update_asr_availability()
            self.statusBar().showMessage('ASR threshold updated; learned calibration preserved.')
            if self._asr_report_dialog is not None and self._asr_report_dialog.isVisible():
                self.show_asr_training_report()
            return
        if self._asr_report_dialog is not None:
            self._asr_report_dialog.close()
        self._asr_resume_after_fit = enable_on_success or self.asr_session.enabled
        if self.asr_session.enabled:
            self.set_eeg_asr_enabled(False)
        task = ASRFitTask(self.asr_session.generation, self.asr_session.training, settings, self)
        self.asr_session.busy = True
        self.asr_view.set_fit_state(False, True)
        self.asr_tasks.append(task)
        task.completed.connect(self.eeg_asr_fitted)
        task.finished.connect(lambda t=task: self._asr_task_finished(t))
        task.start()

    def _asr_task_finished(self, task):
        if task in self.asr_tasks:
            self.asr_tasks.remove(task)
        task.deleteLater()

    def eeg_asr_fitted(self, generation, result, error):
        if self._closing or generation != self.asr_session.generation:
            return
        self.asr_session.busy = False
        if error is not None:
            self.asr_view.set_fit_state(False, False, error)
            return
        self.asr_session.install_fit(result)
        self.update_asr_availability()
        if self._asr_resume_after_fit:
            self.set_eeg_asr_enabled(True)
        self._asr_resume_after_fit = False
        self.statusBar().showMessage('ASR trained independently. All selected EEG channels are preserved.')
        if generation != self._asr_report_generation:
            self._asr_report_generation = generation
            self.show_asr_training_report()
        elif self._asr_report_dialog is not None and self._asr_report_dialog.isVisible():
            self.show_asr_training_report()

    def show_asr_training_report(self):
        model = self.asr_session.model
        if model is None or self.asr_session.busy:
            return
        if self._asr_report_dialog is None:
            folder = Path(__file__).resolve().parent.parent / 'designer'
            loader = QUiLoader()
            loader.setWorkingDirectory(QDir(str(folder)))
            self._asr_report_dialog = loader.load(str(folder / 'ASRTrainingReport.ui'), self)
            if self._asr_report_dialog is None:
                raise RuntimeError('Cannot load Designer ASR training report')
        for key, value in training_report(model).items():
            self._asr_report_dialog.findChild(QLabel, key + 'Value').setText(value)
        self._asr_report_dialog.show()


    def _apply_asr_metric_references(self):
        session = self.asr_session
        session.reference_generation += 1
        self.eeg_reference_pending = False
        self.eeg_reference_error = None
        self.metric_state.reset('EEG')
        self.affect_state.reset('EEG')
        live = getattr(self.workers.get('EEG'), 'source_configuration', None)
        self._reference_source_configuration = deepcopy(live)
        if self._reference_source_configuration is not None:
            self._reference_source_configuration.pop('asr_model_id', None)
        eeg = session.streams.get('EEG') if self.loaded_bsl is not None else None
        if self.eyc_recording is not None or eeg is not None:
            self.eeg_reference_pending = True
            self.calibration_state.setText('Recalculating EEG EYC and BSL references…')
            model = session.model if session.enabled else None
            live = getattr(self.workers.get('EEG'), 'source_configuration', None)
            task = CalibrationReferenceTask(session.reference_generation,
                self.eyc_recording, eeg, session.base_analysis, self.iaf_hz, model, live, self)
            self.eeg_reference_tasks.append(task)
            task.completed.connect(self.calibration_references_ready)
            task.finished.connect(lambda t=task: self._eeg_reference_finished(t))
            task.start()
        self.update_metrics_availability()
        self.refresh_metrics()
        self.refresh_affect_references()

    def calibration_references_ready(self, generation, result, error):
        if self._closing or generation != self.asr_session.reference_generation:
            return
        self.eeg_reference_pending = False
        self.eeg_reference_error = error
        if error:
            self.statusBar().showMessage(error)
        else:
            iaf_changed = not np.isclose(self.iaf_hz, result['iaf_hz'])
            self.iaf_hz = result['iaf_hz']
            if result['eyc'] is not None and self.loaded_eyc is not None:
                self.loaded_eyc = {**self.loaded_eyc, 'analysis': result['eyc']}
            if result['bsl'] is not None and self.loaded_bsl is not None:
                self.loaded_bsl = {**self.loaded_bsl, 'analysis': result['bsl']}
                if self.asr_session.enabled:
                    self.asr_session.cleaned_analysis = result['bsl']
            worker = self.workers.get('EEG')
            if worker is not None:
                worker.iaf_hz = self.iaf_hz
            if iaf_changed:
                self.metric_state.reset('EEG')
                self.affect_state.reset('EEG')
            self.calibration_state.setText(
                f'EYC: {self.iaf_hz:.2f} Hz | BSL: {"loaded" if self.loaded_bsl else "none"}')
        self.update_metrics_availability()
        self.refresh_metrics()
        self.refresh_affect_references()

    def _eeg_reference_finished(self, task):
        if task in self.eeg_reference_tasks:
            self.eeg_reference_tasks.remove(task)
        task.deleteLater()

    def set_eeg_asr_enabled(self, enabled):
        if self.capture is not None:
            self.asr_view.set_enabled(self.asr_session.enabled)
            return
        if enabled:
            live = getattr(self.workers.get('EEG'), 'source_configuration', None)
            available, status, _ = self.asr_session.availability(live)
            if not available:
                self.asr_view.set_enabled(False)
                self.statusBar().showMessage(status)
                return
        try:
            self.asr_session.set_enabled(enabled)
        except ValueError as exc:
            self.asr_view.set_enabled(False)
            self.statusBar().showMessage(str(exc))
            return
        self._apply_asr_metric_references()
        self.asr_view.set_enabled(enabled)
        self.schedule_source_change('EEG')

    def _connect_affect_view(self):
        self.affect_view = AffectView()
        host = self._required_ui('affectViewHost', QFrame)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.affect_view)
        self._affect_workspace = AdaptiveRawWorkspace(
            self._required_ui("affectTabScroll", QScrollArea).viewport(), self.affect_view.cards_splitter)
        self.affect_view.clear_requested.connect(self.clear_affect_trails)
        self.affect_view.normalization_changed.connect(lambda _: self.refresh_affect_view())
        self.affect_view.retention_changed.connect(lambda _: self.refresh_affect_view())
        self.affect_view.set_active(self.tabs.currentWidget() is self.affect_page)
        self.sync_affect_sources()

    def _connect_metric_workspace(self):
        splitter = self._required_ui('metricsWorkspaceSplitter', QSplitter)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(9)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 360])
        self.metric_panel_focus = None
        self.metric_arrangement = PanelArrangement(self, splitter,
            {'trends':self._required_ui('metricsTrendCard', QFrame),
             'values':self._required_ui('metricsValuesCard', QFrame)},
            {'trends':self._required_ui('metricsTrendMove', QToolButton),
             'values':self._required_ui('metricsValuesMove', QToolButton)},
            {'trends':'Metric trends', 'values':'Metric values'})
        self.metric_arrangement.changed.connect(self._restore_metric_panels)
        for key, name in (('trends','metricsTrendExpand'), ('values','metricsValuesExpand')):
            self._required_ui(name, QToolButton).clicked.connect(
                lambda checked=False,k=key:self.toggle_metric_panel_focus(k))
        self._metric_workspace = AdaptiveRawWorkspace(
            self._required_ui('metricsTabScroll', QScrollArea).viewport(), splitter)

    def toggle_metric_panel_focus(self, key):
        splitter = self.metric_arrangement.container
        if self.metric_panel_focus is None:
            self._metric_panel_sizes = splitter.sizes()
        self.metric_panel_focus = None if self.metric_panel_focus == key else key
        self._sync_metric_panels()

    def _restore_metric_panels(self, order):
        self.metric_panel_focus = None
        self._sync_metric_panels()

    def _sync_metric_panels(self):
        for key, name in (('trends','metricsTrendExpand'), ('values','metricsValuesExpand')):
            self.metric_arrangement.panels[key].setVisible(self.metric_panel_focus in (None,key))
            set_panel_expanded(self._required_ui(name,QToolButton), self.metric_panel_focus == key)
        if self.metric_panel_focus is None and hasattr(self,'_metric_panel_sizes'):
            self.metric_arrangement.container.setSizes(self._metric_panel_sizes)

    def sync_affect_sources(self):
        """Peripheral Affect and EI require both live peripheral receivers."""
        if not hasattr(self, 'affect_view'):
            return
        available = all(getattr(self.workers.get(kind), 'active', False)
                        for kind in ('PPG', 'EDA'))
        self.affect_view.set_peripheral_available(available)

    def clear_affect_trails(self):
        self.affect_state.clear()
        self._affect_clear_before = local_clock()

    def metric_references(self):
        """One compatibility policy for both Metrics and Affect normalization."""
        analysis = (self.loaded_bsl or {}).get('analysis') or {}
        references = dict(analysis.get('metrics', {}))
        configurations = analysis.get('source_configurations', {})
        for kind, baseline in configurations.items():
            live = getattr(self.workers.get(kind), 'source_configuration', None)
            if live is not None and live != baseline:
                references.pop(kind, None)
        if (self.eeg_reference_pending or self.eeg_reference_error
                or not np.isclose(analysis.get('iaf_hz_used', self.iaf_hz), self.iaf_hz)
                or (self.asr_session.enabled and 'asr_model_id' not in configurations.get('EEG', {}))):
            references.pop('EEG', None)
        metadata = analysis.get('tonic_sc') or {}
        if not (metadata.get('configuration_id') and
                metadata['configuration_id'] == self._tonic_live_configuration):
            references.pop('EDA', None)
        if not (references.get('PPG', {}).get('HR') and references.get('EDA', {}).get('SCL')):
            references.pop('EI', None)
        return references

    def refresh_affect_references(self):
        analysis = (self.loaded_bsl or {}).get('analysis') or {}
        metadata = analysis.get('tonic_sc') or {}
        compatible = bool(metadata.get('configuration_id') and
                          metadata['configuration_id'] == self._tonic_live_configuration)
        references = self.metric_references()
        self.affect_state.set_references(references, compatible)
        self.metric_state.set_ei_references(
            references.get('PPG', {}).get('HR'), references.get('EDA', {}).get('SCL'))

    def refresh_affect_view(self):
        self.sync_affect_sources()
        now = local_clock()
        snapshot = self.affect_state.snapshot(
            now, float(self.affect_view.retention.currentData()),
            self.affect_view.normalization.currentData())
        if self.eeg_reference_pending:
            snapshot = replace(snapshot, responses=tuple(
                replace(response, status='Updating EEG baseline references…')
                if response.key == 'central' else response for response in snapshot.responses))
        tonic_status = self.metric_state.latest.get('EDA', {}).get('_tonic_status', '')
        if tonic_status and tonic_status != 'Tonic SC ready (cvxEDA)':
            snapshot = replace(snapshot, responses=tuple(
                replace(response, status=tonic_status)
                if response.key == 'peripheral' and response.status == 'Waiting for valid metric observations'
                else response for response in snapshot.responses))
        # Each view normalizes retained raw EI once using its own selector.
        references = self.metric_references()
        ei_points = [(at+self._affect_clock_offset,
                      self.metric_state.normalized_value('EI', 'EI', value,
                          self.affect_view.normalization.currentData(), references))
                     for at, value in self.metric_state.history.get(('EI', 'EI'), ())
                     if at+self._affect_clock_offset >= self._affect_clear_before]
        ei_status = (self.metric_state.latest.get('EI', {}).get('status')
                     or self.metric_state.ei_unavailable_reason())
        if not references.get('EI', {}).get('EI'):
            ei_status = 'EI needs compatible BSL references for the selected normalization'
        if ei_points and ei_points[-1][1] is None and self.metric_state.ei.value() is not None:
            ei_status = 'EI baseline has insufficient variability for the selected normalization'
        ei_points = [(at, value if value is not None else float('nan')) for at, value in ei_points]
        self.affect_view.update_snapshot(snapshot, ei_points, now, ei_status=ei_status)
        if self.affect_view.pause.isChecked():
            return
        estimator = self.metric_state.ei
        if estimator.value() is not None:
            h = (estimator.latest['HR'][1]-estimator.hr_reference['mu'])/estimator.hr_reference['sigma']
            g = (estimator.latest['SCL'][1]-estimator.scl_reference['mu'])/estimator.scl_reference['sigma']
            self.affect_view.ei_diagnostics.setText(f'HRz {h:+.2f} · SCLz {g:+.2f} · raw EI {estimator.value():+.3f}')
        else:
            self.affect_view.ei_diagnostics.setText('Awaiting compatible HR and tonic SCL')

    def _fill_combo(self, combo, options):
        combo.blockSignals(True)
        combo.clear()
        for label, value in options:
            combo.addItem(label, value)
        combo.blockSignals(False)

    def _connect_designer_controls(self):
        """Wire the live application to named Designer widgets, not a mockup."""
        self.filter_choices, self.filter_notches = {}, {}
        self.artifact_choices = {}
        self.source_conversions = {}
        for kind in ('EEG', 'EDA', 'PPG'):
            conversion = SourceConversionControls()
            self.source_conversions[kind] = conversion
            source_layout = self._required_ui(f'{kind}SourceLayout', QVBoxLayout)
            conversion_position = (source_layout.indexOf(self._required_ui('EEGProcessingPanel', QWidget))+1
                                   if kind == 'EEG' else 2)
            source_layout.insertWidget(conversion_position, conversion)
            combo = self._required_ui(f'{kind}StreamSelector', QComboBox)
            combo.clear()
            self.selectors[kind] = combo
            combo.currentIndexChanged.connect(
                lambda _, k=kind: self.stream_selection_changed(k))
            picker = CheckChannelDropdown(kind)
            self.channel_selectors[kind] = picker
            picker.selection_changed.connect(lambda k=kind: self.channel_selection_changed(k))
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(self.settings.source_change_debounce_ms)
            timer.timeout.connect(lambda k=kind: self.apply_pending_source_change(k))
            self.source_change_timers[kind] = timer
            if kind == 'EEG':
                row = self._required_ui(f'{kind}Channels', QGridLayout)
                row.addWidget(picker, 0, 1)
            else:
                row = self._required_ui(f'{kind}Channels', QHBoxLayout)
                row.insertWidget(1, picker)
            action = self._required_ui(f'{kind}Play', QPushButton)
            self.stream_buttons[kind] = action
            action.clicked.connect(lambda _, k=kind: self.toggle_stream(k))
            action.setToolTip(f'Start/stop local {modality_label(kind)} LSL reception')
            self._required_ui(f'{kind}Refresh', QPushButton).clicked.connect(self.refresh)
            self._required_ui(f'{kind}ChooseChannels', QPushButton).setVisible(False)
            choices = self._required_ui(f'{kind}FilterPreset', QComboBox)
            configurations = {
                'EEG': [('Default 1–40 Hz', 'default'), ('Wide', 'wide'),
                        ('Focused', 'focused'), ('Off', 'off')],
                'PPG': [('Default 0.5–8 Hz', 'default'), ('Pulse', 'pulse'),
                        ('Wide', 'wide'), ('Off', 'off')],
                'EDA': [('Default', 'default'), ('Low-pass 1 Hz', 'smooth_1hz'),
                        ('Low-pass 2 Hz', 'smooth_2hz')],
            }
            self._fill_combo(choices, configurations[kind])
            self.filter_choices[kind] = choices
            notch = self._required_ui(f'{kind}Notch', QCheckBox)
            notch.setChecked(True)
            self.filter_notches[kind] = notch
            if kind in ('PPG','EDA'):
                artifacts = self._required_ui(f'{kind}ArtifactReduction',QComboBox)
                for index,method in enumerate(('off','hampel','wavelet')):
                    artifacts.setItemData(index,method)
                self.artifact_choices[kind] = artifacts
                artifacts.currentIndexChanged.connect(lambda _,k=kind:self.schedule_source_change(k))
            choices.setToolTip('Used on next stream start, not mid-capture')
            notch.setToolTip('Used on next stream start, not mid-capture')
        self._required_ui('refreshAllStreams', QPushButton).clicked.connect(self.refresh)
        self.eeg_display_count = self._required_ui('eegDisplayChannelCount', QSpinBox)
        self.eeg_display_count.setRange(1, 1)
        self.eeg_display_count.setEnabled(False)
        self.eeg_display_count.valueChanged.connect(self.change_eeg_display_count)
        self.calibration_file_labels = {}
        for kind in ('EYC', 'BSL'):
            self.calibration_file_labels[kind] = self._required_ui(f'{kind}Status', QLabel)
            self._required_ui(f'{kind}Execute', QPushButton).clicked.connect(
                lambda _, k=kind: self._baseline_designer_action(k))
            self._required_ui(f'{kind}Mode', QComboBox).currentIndexChanged.connect(
                lambda _, k=kind: self.update_calibration_action(k))
            self.update_calibration_action(kind)
        self.calibration_state = self._required_ui('baselineSummary', QLabel)
        self.calibration_state.setText('EYC: none (default IAF 10 Hz) | BSL: none')

        self.show_raw = self._required_ui('showRaw', QCheckBox)
        self.show_processed = self._required_ui('showFiltered', QCheckBox)
        self.show_raw.setChecked(True)
        self.show_processed.setChecked(True)
        self._raw_trace_selection_refresh = False
        self.show_raw.toggled.connect(self.raw_trace_selection_changed)
        self.show_processed.toggled.connect(self.raw_trace_selection_changed)
        self.raw_renderer_choice = self._required_ui('rawRendererChoice', QComboBox)
        self._fill_combo(self.raw_renderer_choice, [
            ('pyqtgraph (original)', 'pyqtgraph'),
            ('VisPy / OpenGL', 'vispy')])
        self.raw_renderer_choice.currentIndexChanged.connect(self.set_raw_renderer)
        self.raw_time_window = self._required_ui('rawSweepDuration', QComboBox)
        self._fill_combo(self.raw_time_window, [
            ('5 s', 5), ('8 s', 8), ('10 s', 10), ('15 s', 15),
            ('30 s', 30), ('1 min', 60), ('5 min', 300)])
        self.raw_time_window.currentIndexChanged.connect(self.set_raw_time_window)
        self._required_ui('rawZoomMinus', QPushButton).clicked.connect(
            lambda: self.zoom_raw_plots(2.))
        self._required_ui('rawZoomPlus', QPushButton).clicked.connect(
            lambda: self.zoom_raw_plots(.5))
        self.raw_asr_status = self._required_ui('rawASRStatus', QLabel)
        self._last_asr_indicator = None
        self.raw_reduction_status = {kind:self._required_ui(kind+'ReductionStatus',QLabel)
                                     for kind in ('PPG','EDA')}
        self._last_reduction_indicators = {}
        self.raw_live_button = self._required_ui('rawFollowLive', QPushButton)
        set_action(self.raw_live_button, 'Live', 'live')
        self.raw_live_button.clicked.connect(self.resume_raw_live)
        self.raw_live_button.setEnabled(False)
        self.raw_plot_splitter = self._required_ui('rawPlotSplitter', QSplitter)
        self.raw_plot_splitter.setChildrenCollapsible(False)
        self.raw_plot_splitter.setHandleWidth(9)
        self.raw_plot_splitter.setStretchFactor(0, 4)
        self.raw_plot_splitter.setStretchFactor(1, 1)
        self.raw_peripheral_splitter = self._required_ui('rawPeripheralSplitter', QSplitter)
        self.raw_peripheral_splitter.setChildrenCollapsible(False)
        self.raw_peripheral_splitter.setHandleWidth(9)
        self.raw_peripheral_splitter.setStretchFactor(0, 1)
        self.raw_peripheral_splitter.setStretchFactor(1, 1)
        self.raw_panel_order = ('EEG', 'PPG', 'EDA')
        self.raw_move_menus = {}
        self.raw_focus_buttons = {}
        self.focused_raw_kind = None
        for kind in ('EEG', 'PPG', 'EDA'):
            focus = self._required_ui(f'{kind}Expand', QToolButton)
            focus.setToolTip(f'Give {modality_label(kind)} the full plot area; all streams keep acquiring')
            focus.toggled.connect(lambda checked, k=kind: self.set_raw_focus(k, checked))
            self.raw_focus_buttons[kind] = focus
            move = self._required_ui(f'{kind}Move', QToolButton)
            menu = QMenu(move)
            move.setMenu(menu)
            move.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu.aboutToShow.connect(lambda k=kind: self.update_raw_move_menu(k))
            self.raw_move_menus[kind] = menu
            plot = pg.PlotWidget(title=(
                f'{modality_label(kind)} — {self.settings.default_view_seconds:g} s view, '
                f'{self.settings.history_seconds / 60:g} min history'))
            plot.showGrid(x=True, y=True, alpha=.2)
            plot.setLabel('bottom', 'Elapsed session time', 's')
            plot.getViewBox().sigRangeChangedManually.connect(
                lambda *args, k=kind: self.raw_view_changed_manually(k))
            plot.setXRange(-self.settings.default_view_seconds, 0., padding=0)
            plot.setMinimumHeight(75)
            plot.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Expanding)
            stack = QStackedWidget()
            stack.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
            stack.addWidget(plot)
            host = self._required_ui(f'{kind}PlotHost', QFrame)
            if host.layout() is None:
                host_layout = QVBoxLayout(host)
                host_layout.setContentsMargins(0, 0, 0, 0)
            host.layout().addWidget(stack)
            self.raw_plot_stacks[kind] = stack
            self.plots[kind] = plot
            self.curves[kind] = []
            gain = self._required_ui(f'{kind}Amplitude', QDoubleSpinBox)
            gain.hide()  # Keep bounded gain state; adjustment uses − / Fit / + only.
            gain.setDecimals(2)
            # Qt's Windows stylesheet gives NoButtons a zero-width editor.
            # Hide the subcontrols instead, preserving the editable number.
            gain.setStyleSheet(
                'QDoubleSpinBox::up-button, QDoubleSpinBox::down-button '
                '{ width: 0px; height: 0px; border: none; } '
                'QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow '
                '{ image: none; width: 0px; height: 0px; }')
            gain.setRange(self.settings.gain_minimum, self.settings.gain_maximum)
            gain.setSingleStep(.1)
            gain.setSuffix('×')
            gain.setValue(1.)
            gain.valueChanged.connect(
                lambda _, k=kind: self.set_raw_vertical_gain(k))
            self.raw_vertical_gains[kind] = gain
            autoscale = self._required_ui(f'{kind}Autoscale', QToolButton)
            autoscale.setToolTip('Fit visible raw/filtered extrema; EEG keeps one shared gain')
            autoscale.clicked.connect(lambda _, k=kind: self.autoscale_raw(k))
            self.raw_autoscale_buttons[kind] = autoscale
            self._required_ui(f'{kind}AmplitudeMinus', QPushButton).clicked.connect(
                lambda _, k=kind: self.adjust_raw_vertical_gain(k, 1/self.settings.gain_step))
            self._required_ui(f'{kind}AmplitudePlus', QPushButton).clicked.connect(
                lambda _, k=kind: self.adjust_raw_vertical_gain(k, self.settings.gain_step))
        self.raw_plot_splitter.setSizes([720, 360])
        self.raw_peripheral_splitter.setSizes([240, 240])
        # No scroll area: the splitter shares the available screen height.
        self.raw_scroll = QScrollArea(self)
        self.raw_scroll.hide()  # Compatibility event source; not part of the layout.
        self.raw_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.raw_scroll.verticalScrollBar().valueChanged.connect(self.raw_view_scrolled)

        self.normalization = self._required_ui('metricNormalization', QComboBox)
        self._fill_combo(self.normalization, [
            ('Original (identity)', 'identity'), ('z-score (BSL)', 'zscore'),
            ('robust z-MAD (BSL)', 'zmad'),
            ('robust IQR (BSL)', 'robust_iqr'),
            ('fixed min-max (BSL)', 'minmax')])
        self.normalization.currentIndexChanged.connect(self.refresh_metrics)
        self.metric_renderer_choice = self._required_ui('metricsRendererChoice', QComboBox)
        self._fill_combo(self.metric_renderer_choice, [
            ('pyqtgraph (original)', 'pyqtgraph'),
            ('VisPy / OpenGL', 'vispy')])
        self.metric_renderer_choice.currentIndexChanged.connect(self.set_metric_renderer)
        self.metric_time_window = self._required_ui('metricsSweepDuration', QComboBox)
        self._fill_combo(self.metric_time_window, [
            ('5 s', 5), ('10 s', 10), ('30 s', 30),
            ('1 min', 60), ('5 min', 300)])
        self.metric_time_window.currentIndexChanged.connect(self.set_metric_time_window)
        self._required_ui('metricsZoomMinus', QPushButton).clicked.connect(
            lambda: self.zoom_metric_plot(2.))
        self._required_ui('metricsZoomPlus', QPushButton).clicked.connect(
            lambda: self.zoom_metric_plot(.5))
        self.metric_live_button = self._required_ui('metricsFollowLive', QPushButton)
        set_action(self.metric_live_button, 'Live', 'live')
        self.metric_live_button.clicked.connect(self.resume_metric_live)
        self.metric_smoothing = self._required_ui('metricsSmoothing', QComboBox)
        self._fill_combo(self.metric_smoothing, [
            ('None', 'none'), ('Moving average', 'mean'),
            ('Exponential (EMA)', 'ema'), ('Moving median', 'median')])
        self.metric_smoothing.currentIndexChanged.connect(self.refresh_metric_plot)
        self.metric_smoothing_duration = self._required_ui(
            'metricsSmoothingDuration', QComboBox)
        self._fill_combo(self.metric_smoothing_duration,
                         [(f'{d} s', float(d)) for d in (1, 2, 3, 5, 10)])
        self.metric_smoothing_duration.setCurrentIndex(1)
        self.metric_smoothing_duration.setEnabled(False)
        self.metric_smoothing_duration.currentIndexChanged.connect(
            self.refresh_metric_plot)
        self.metric_smoothing.currentIndexChanged.connect(
            lambda: self.metric_smoothing_duration.setEnabled(
                self.metric_smoothing.currentData() != 'none'))
        self.metric_interpolation = self._required_ui('metricsInterpolation', QComboBox)
        self._fill_combo(self.metric_interpolation, [
            ('None (points)', 'none'), ('Linear', 'linear'),
            ('PCHIP', 'pchip'), ('Cubic spline', 'cubic')])
        self.metric_interpolation.setCurrentIndex(2)
        self.metric_interpolation.currentIndexChanged.connect(self.refresh_metric_plot)
        self.metric_sample_markers = self._required_ui('measuredPoints', QCheckBox)
        self.metric_sample_markers.setChecked(True)
        self.metric_sample_markers.toggled.connect(self.refresh_metric_plot)
        self.metric_checks = build_metric_toggles(
            self, self._required_ui('metricsSeriesControls', QHBoxLayout),
            self.metric_definitions, self.refresh_metric_plot)

        self.metric_plot = pg.PlotWidget(
            title='Combined live metrics — 5 s default, up to 5 min history')
        self.metric_plot.setLabel('bottom', 'Elapsed session time', units='s')
        self.metric_plot.showGrid(x=True, y=True, alpha=.2)
        self.metric_plot.addLegend()
        self.metric_plot.setMouseEnabled(x=True, y=True)
        self.metric_plot.getViewBox().sigRangeChangedManually.connect(
            self.metric_view_changed_manually)
        self.metric_curves = {}
        self.metric_point_curves = {}
        for index, key in enumerate(self.metric_state.keys):
            color = metric_color(index)
            self.metric_curves[key] = self.metric_plot.plot(
                name=f'{key[0]} / {key[1]}',
                pen=pg.mkPen(color, width=2), connect='finite')
            self.metric_point_curves[key] = self.metric_plot.plot(
                pen=None, symbol='o', symbolSize=5,
                symbolBrush=pg.mkBrush(color), symbolPen=None)
        self.metric_plot_stack = QStackedWidget()
        fallback = QWidget()
        fallback_layout = QGridLayout(fallback)
        fallback_layout.setContentsMargins(0, 0, 0, 0)
        fallback_layout.setSpacing(2)
        self.metric_time_ruler = ScaleRuler(Qt.Orientation.Horizontal)
        self.metric_amplitude_ruler = ScaleRuler(Qt.Orientation.Vertical)
        fallback_layout.addWidget(self.metric_plot, 0, 0)
        fallback_layout.addWidget(self.metric_time_ruler, 1, 0)
        fallback_layout.addWidget(self.metric_amplitude_ruler, 0, 1)
        fallback_layout.setColumnStretch(0, 1)
        fallback_layout.setRowStretch(0, 1)
        self.metric_plot.getViewBox().sigRangeChanged.connect(self.update_metric_rulers)
        self.metric_plot.getViewBox().sigResized.connect(self.update_metric_rulers)
        self.metric_plot_stack.addWidget(fallback)
        metrics_host = self._required_ui('metricsPlotHost', QFrame)
        if metrics_host.layout() is None:
            host_layout = QVBoxLayout(metrics_host)
            host_layout.setContentsMargins(0, 0, 0, 0)
        metrics_host.layout().addWidget(self.metric_plot_stack)
        readouts = self._required_ui('metricsReadoutHost', QFrame)
        self.metric_labels, self.metric_status = build_metric_readouts(
            readouts, self.metric_definitions)
        install_flow(readouts)
        self._required_ui('rawPlotPause', QPushButton).clicked.connect(
            lambda: self.set_plot_paused('raw', not self.raw_display.paused))
        self._required_ui('metricsPlotPause', QPushButton).clicked.connect(
            lambda: self.set_plot_paused('metrics', not self.metric_plot_paused))
        self.raw_display.paused = False
        self.metric_plot_paused = False
        self.metric_y_auto = self._required_ui('metricsYAuto', QCheckBox)
        self.metric_y_auto.setToolTip('Continuously fit the vertical range to visible metric values. '
            'Turn off to hold the range; Fit adjusts it once; −/+ select a manual zoom.')
        self._metric_manual_y = None
        self.metric_y_auto.toggled.connect(self._metric_vertical_auto_changed)
        self._required_ui('metricsYOut', QToolButton).clicked.connect(lambda:self.zoom_metric_y(1.25))
        self._required_ui('metricsYIn', QToolButton).clicked.connect(lambda:self.zoom_metric_y(.8))
        self._required_ui('metricsYFit', QToolButton).clicked.connect(self.fit_metric_y)


    def update_calibration_action(self, kind):
        mode = self._required_ui(f'{kind}Mode', QComboBox).currentIndex()
        text, icon = (('Record','record'), ('Load','open'), ('Clear','clear'))[mode]
        button = self._required_ui(f'{kind}Execute', QPushButton)
        set_action(button, text, icon)
        button.setToolTip(('Record a fresh 60-second calibration.',
                           'Load a saved calibration recording.',
                           'Clear the active calibration; saved files are kept.')[mode])

    def _baseline_designer_action(self, kind):
        choice = self._required_ui(f'{kind}Mode', QComboBox).currentIndex()
        if choice == 0:
            self.record_calibration(kind)
        elif choice == 1:
            self.load_existing(kind)
        else:
            self.clear_calibration(kind)

    def clear_calibration(self, kind):
        if kind == 'EYC':
            self.loaded_eyc = None
            self.eyc_recording = None
            self.iaf_hz = 10.
            for worker in self.workers.values():
                if worker.kind == 'EEG':
                    worker.iaf_hz = self.iaf_hz
        else:
            self.loaded_bsl = None
            self.metric_state.ei.set_references(None, None)
            self.asr_session.set_baseline()
        self.calibration_paths[kind] = None
        self.calibration_file_labels[kind].setText('None selected')
        self.calibration_state.setText(
            f'EYC: {self.iaf_hz:.2f} Hz'
            f" | BSL: {'loaded' if self.loaded_bsl else 'none'}")
        self.update_metrics_availability()
        self.refresh_metrics()
        self.affect_state.clear()
        self.refresh_affect_references()
        self.update_asr_availability()
        self._apply_asr_metric_references()

    def update_metrics_availability(self):
        """Keep both analysis tabs visible, enabling them together after EYC/BSL."""
        eyc = self.loaded_eyc or {}
        bsl = self.loaded_bsl or {}
        iaf = (eyc.get('analysis') or {}).get('iaf_hz')
        refs = (bsl.get('analysis') or {}).get('metrics')
        ready = (iaf is not None and np.isfinite(float(iaf)) and bool(refs)
                 and not self.eeg_reference_pending and not self.eeg_reference_error)
        for page in (self.metrics_page, self.affect_page):
            index = self.tabs.indexOf(page)
            if index >= 0:
                self.tabs.setTabVisible(index, True)
                self.tabs.setTabEnabled(index, bool(ready))
                self.tabs.setTabToolTip(index, 'Available' if ready else
                    'Record or load EYC and BSL in Sources to enable analysis')
        if not ready and self.tabs.currentWidget() in (self.metrics_page, self.affect_page):
            self.tabs.setCurrentWidget(self.sources_page)
        return bool(ready)

    def sync_eeg_display_count(self, reset_default=False):
        """Offer only counts available in the EEG panel's selected source channels."""
        count = len(self.channel_selectors['EEG'].selected_indices())
        value = (self.settings.default_eeg_display_channels if reset_default
                 else self.eeg_display_count.value())
        self.eeg_display_count.setRange(1, max(1, count))
        self.eeg_display_count.setValue(min(value, max(1, count)))
        self.eeg_display_count.setEnabled(count > 0)
        self.eeg_display_count.setToolTip(
            f'Display up to {count} selected source channels; processing uses all selected channels.'
            if count else 'Select source channels to enable the display count.')

    def channel_selection_changed(self, kind):
        if kind == 'EEG':
            self.sync_eeg_display_count()
        self.schedule_source_change(kind)

    def change_eeg_display_count(self, *_):
        """Only limit waveform channels; do not change LSL processing."""
        self.raw_display.references.pop('EEG', None)
        self.raw_display.invalidate()
        # Keep the current GPU scene visible while its replacement is
        # prepared; VisPyRawPlot commits the complete channel set atomically.
        self.curves['EEG'] = []
        self.plots['EEG'].clear()

    @property

    def eeg_focus_button(self):
        return self.raw_focus_buttons['EEG']

    def update_raw_move_menu(self, kind):
        menu = self.raw_move_menus[kind]
        menu.clear()
        for other in self.raw_panel_order:
            if other != kind:
                action = menu.addAction(f'Swap with {modality_label(other)}')
                action.triggered.connect(lambda checked=False, a=kind, b=other: self.swap_raw_panels(a, b))
        menu.addSeparator()
        menu.addAction('Restore default layout').triggered.connect(
            lambda: self.set_raw_panel_order(('EEG', 'PPG', 'EDA')))

    def swap_raw_panels(self, first, second):
        order = list(self.raw_panel_order)
        a, b = order.index(first), order.index(second)
        order[a], order[b] = order[b], order[a]
        self.set_raw_panel_order(tuple(order))

    def set_raw_panel_order(self, order):
        order = tuple(order)
        if len(order) != 3 or set(order) != {'EEG', 'PPG', 'EDA'}:
            raise ValueError('Raw layout must include EEG, PPG and SC exactly once')
        if self.focused_raw_kind is not None:
            self.set_raw_focus(self.focused_raw_kind, False)
        if order == self.raw_panel_order:
            return
        sizes = self.raw_plot_splitter.sizes()
        side_sizes = self.raw_peripheral_splitter.sizes()
        panels = {kind:self._required_ui(f'{kind}PlotPanel', QWidget) for kind in order}
        # Move the existing panels, including their canvas and controls. No
        # receiver, signal history, gain or renderer is replaced by a layout swap.
        self.raw_plot_splitter.insertWidget(0, panels[order[0]])
        for index, kind in enumerate(order[1:]):
            self.raw_peripheral_splitter.insertWidget(index, panels[kind])
        for panel in panels.values():
            panel.show()
        self.raw_panel_order = order
        self.raw_plot_splitter.setSizes(sizes)
        self.raw_peripheral_splitter.setSizes(side_sizes)
        self.raw_display.dirty = True

    def set_raw_focus(self, kind, focused):
        """One shared expansion policy for every raw signal panel."""
        if focused:
            if self.focused_raw_kind is None:
                self._raw_splitter_sizes = self.raw_plot_splitter.sizes()
            self.focused_raw_kind = kind
        elif self.focused_raw_kind == kind:
            self.focused_raw_kind = None
        for modality, button in self.raw_focus_buttons.items():
            selected = self.focused_raw_kind == modality
            button.blockSignals(True)
            button.setChecked(selected)
            button.blockSignals(False)
            set_panel_expanded(button, selected)
            self._required_ui(f'{modality}PlotPanel', QWidget).setVisible(
                self.focused_raw_kind is None or selected)
        self.raw_peripheral_splitter.setVisible(self.focused_raw_kind != self.raw_panel_order[0])
        if not focused and hasattr(self, '_raw_splitter_sizes'):
            self.raw_plot_splitter.setSizes(self._raw_splitter_sizes)
        self.raw_display.dirty = True

    def set_plot_paused(self, scope, paused):
        if scope == 'raw':
            self.raw_display.paused = bool(paused)
            set_view_paused(self._required_ui('rawPlotPause', QPushButton), paused)
            if not paused:
                # Preserve GPU ring contents across plot-only pause/resume.
                # Replay buffered samples without a blank-frame reset.
                self.raw_display.dirty = True
        else:
            self.metric_plot_paused = bool(paused)
            set_view_paused(self._required_ui('metricsPlotPause', QPushButton), paused)
            if not paused:
                self.metric_presentation_epoch += 1
                self.metric_dirty = True

    def queue_lsl_task(self, operation, info=None):
        """Run blocking LSL APIs outside the Qt GUI event loop."""
        self.lsl_task_serial += 1
        token = self.lsl_task_serial
        task = LSLTask(token, operation, info, self)
        self.lsl_tasks[token] = task
        task.completed.connect(self.lsl_task_completed)
        task.finished.connect(lambda n=token, w=task: self.lsl_task_finished(n, w))
        task.start()
        return token

    def lsl_task_finished(self, token, task):
        self.lsl_tasks.pop(token, None)
        task.deleteLater()

    def refresh(self):
        if self._closing:
            return
        self.discovery_serial = self.queue_lsl_task('discover')
        self.statusBar().showMessage('Discovering LSL sources…')

    def lsl_task_completed(self, token, result, error):
        if self._closing:
            return
        if token == self.discovery_serial:
            if error:
                self.statusBar().showMessage(f'LSL discovery failed: {error}')
                return
            streams = result
            for kind, combo in self.selectors.items():
                old = combo.currentData()
                uid = old.uid() if old is not None else None
                combo.blockSignals(True)
                combo.clear()
                for info in streams:
                    combo.addItem(
                        f'{info.name()} [{info.type()}] '
                        f'({info.channel_count()} ch, {info.nominal_srate():g} Hz)',
                        info
                    )
                if uid is not None:
                    for idx in range(combo.count()):
                        if combo.itemData(idx).uid() == uid:
                            combo.setCurrentIndex(idx)
                            break
                combo.blockSignals(False)
                current = combo.currentData()
                if old is None or current is None or current.uid() != uid:
                    self.stream_selection_changed(kind)
            self.statusBar().showMessage(f'Found {len(streams)} LSL streams')
            return
        # Only the currently selected stream is permitted to change its
        # channel controls; delayed metadata from previous selections is stale.
        for identifier, pending in list(self._metadata_requests.items()):
            if pending == token:
                self._metadata_requests.pop(identifier, None)
                if error:
                    self.statusBar().showMessage(f'LSL metadata failed: {error}')
                    return
                self.channel_metadata_cache[identifier] = result
                names, warning = result
                for kind, combo in self.selectors.items():
                    info = combo.currentData()
                    if info is not None and info.uid() == identifier:
                        # Preserve checked channel indices when names arrive.
                        chosen = self.channel_selectors[kind].selected_indices()
                        self.channel_selectors[kind].set_channels(names)
                        for i, action in enumerate(self.channel_selectors[kind].actions):
                            action.setChecked(i in chosen)
                        self.channel_selectors[kind].update_label()
                        if kind == 'EEG':
                            self.sync_eeg_display_count()
                        if kind not in self.workers:
                            self.stream_buttons[kind].setEnabled(True)
                            self.stream_buttons[kind].setToolTip('Start selected LSL stream')
                        self.apply_pending_source_change(kind)
                if warning:
                    self.statusBar().showMessage(warning)
                return

    def stream_selection_changed(self, kind):
        info = self.selectors[kind].currentData()
        self.source_conversions[kind].set_source(info.uid() if info is not None else None)
        if info is None:
            self.channel_selectors[kind].set_channels([])
            if kind == 'EEG':
                self.sync_eeg_display_count()
            self.schedule_source_change(kind)
            if kind not in self.workers:
                self.stream_buttons[kind].setEnabled(False)
            return
        identifier = info.uid()
        if identifier in self.channel_metadata_cache:
            names, warning = self.channel_metadata_cache[identifier]
            self.channel_selectors[kind].set_channels(names)
            if kind == 'EEG':
                self.sync_eeg_display_count(reset_default=True)
            if kind not in self.workers:
                self.stream_buttons[kind].setEnabled(True)
                self.stream_buttons[kind].setToolTip('Start selected LSL stream')
            if warning:
                self.statusBar().showMessage(warning)
            self.schedule_source_change(kind)
            return
        # Never open StreamInlet or query its metadata from the GUI thread.
        # Display provisional channel names until asynchronous lookup finishes.
        self.channel_selectors[kind].set_channels(
            [f'Ch{i+1} (loading labels)' for i in range(info.channel_count())]
        )
        if kind == 'EEG':
            self.sync_eeg_display_count(reset_default=True)
        if kind not in self.workers:
            self.stream_buttons[kind].setEnabled(False)
            self.stream_buttons[kind].setToolTip('Waiting for channel metadata…')
        if identifier not in self._metadata_requests:
            self._metadata_requests[identifier] = self.queue_lsl_task('metadata', info)
        self.schedule_source_change(kind)

    def _receiver_processing_matches(self,kind,worker):
        requested = validate_preprocessing(kind,preset=self.filter_choices[kind].currentData(),
            notch=self.filter_notches[kind].isChecked(),
            artifact_reduction=(self.artifact_choices[kind].currentData() if kind in self.artifact_choices else 'off'))
        return getattr(worker,'preprocessing',validate_preprocessing(kind)) == requested

    def _receiver_asr_matches(self, kind, worker):
        """Changing the cleaning model requires a new receiver, even on the same source."""
        if kind != 'EEG':
            return True
        requested = self.asr_session.model if self.asr_session.enabled else None
        active = getattr(worker, 'eeg_asr_model', None)
        return ((requested.model_id if requested is not None else None)
                == (active.model_id if active is not None else None))

    def schedule_source_change(self, kind):
        """Replace an active source asynchronously; coalesce rapid selections."""
        worker = self.workers.get(kind)
        info = self.selectors[kind].currentData()
        was_pending = kind in self.pending_source_changes
        was_active = worker is not None and worker.active
        if worker is None and kind not in self.pending_source_changes:
            self.reset_stream_display(kind)
            return
        if (kind not in self.pending_source_changes and not worker.active):
            return  # An explicit Stop is still finishing; preserve that intent.
        if (worker is not None and kind not in self.pending_source_changes
                and info is not None and worker.info.uid() == info.uid()
                and worker.selected_indices == self.channel_selectors[kind].selected_indices()
                and self._receiver_asr_matches(kind, worker)
                and self._receiver_processing_matches(kind,worker)):
            return
        self.pending_source_changes.add(kind)
        if self.capture is not None:
            self.statusBar().showMessage(f'{modality_label(kind)}: selection will apply after calibration')
            return
        self.source_change_timers[kind].start()
        self.stream_buttons[kind].setEnabled(True)
        set_action(self.stream_buttons[kind], 'Stop', 'stop-white')
        self.statusBar().showMessage(f'{modality_label(kind)}: updating settings; Stop cancels the restart.')
        if worker is not None:
            worker.request_stop()
        if not was_pending or was_active:
            self.reset_stream_display(kind)

    def apply_pending_source_change(self, kind):
        if (self._closing or kind not in self.pending_source_changes
                or self.capture is not None or self.source_change_timers[kind].isActive()
                or kind in self.workers):
            return
        info = self.selectors[kind].currentData()
        if info is None or info.uid() not in self.channel_metadata_cache:
            return  # Metadata completion will retry using the latest selection.
        if not self.channel_selectors[kind].selected_indices():
            self.stream_buttons[kind].setEnabled(True)
            set_action(self.stream_buttons[kind], 'Stop', 'stop-white')
            self.statusBar().showMessage(f'{modality_label(kind)}: select channels to resume')
            return
        self.pending_source_changes.remove(kind)
        self.connect_stream(kind)

    def toggle_stream(self, kind):
        worker = self.workers.get(kind)
        if kind in self.pending_source_changes or (worker is not None and worker.isRunning()):
            self.stop_stream(kind)
        else:
            self.connect_stream(kind)

    def reset_stream_display(self, kind):
        self.raw_display.reset(kind)
        self.metric_state.reset(kind)
        self.affect_state.reset(kind)
        self.sync_affect_sources()
        if kind == 'EDA':
            self._tonic_live_configuration = None
            self.refresh_affect_references()
        self.raw_autoscale_buttons[kind].setEnabled(False)
        plot = self.plots[kind]
        plot.clear()
        self.curves[kind] = []
        if kind in self.raw_vispy_plots:
            self.raw_vispy_plots[kind].reset()
        self.refresh_metrics()

    def stop_stream(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration in progress',
                                'Finish or cancel the calibration before stopping a stream.')
            return
        self.pending_source_changes.discard(kind)
        self.source_change_timers[kind].stop()
        worker = self.workers.get(kind)
        if worker is None:
            set_action(self.stream_buttons[kind], 'Play', 'play-white')
            info = self.selectors[kind].currentData()
            self.stream_buttons[kind].setEnabled(
                info is not None and info.uid() in self.channel_metadata_cache)
            return
        self.stream_buttons[kind].setEnabled(False)
        self.stream_buttons[kind].setText('Stopping…')
        worker.request_stop()
        self.sync_affect_sources()
        self.statusBar().showMessage(f'{modality_label(kind)}: stopping receiver asynchronously…')

    def receiver_finished(self, kind, worker):
        if self.workers.get(kind) is not worker:
            return
        self.workers.pop(kind, None)
        self.source_conversions[kind].setEnabled(True)
        self.stream_buttons[kind].setEnabled(True)
        set_action(self.stream_buttons[kind], 'Play', 'play-white')
        self.reset_stream_display(kind)
        if kind in self.pending_source_changes:
            set_action(self.stream_buttons[kind], 'Stop', 'stop-white')
            self.stream_buttons[kind].setEnabled(True)
            self.apply_pending_source_change(kind)
            return
        if worker.active:
            self.statusBar().showMessage(f'{modality_label(kind)} receiver ended unexpectedly')
        else:
            self.statusBar().showMessage(f'{modality_label(kind)} reception stopped')

    def connect_stream(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration in progress',
                                'Finish or cancel calibration before changing a stream.')
            return
        info = self.selectors[kind].currentData()
        if info is None:
            self.statusBar().showMessage(f'No {modality_label(kind)} stream selected')
            return
        try:
            indices = validated_indices(
                self.channel_selectors[kind].selected_indices(),
                info.channel_count(), kind,
            )
            previous = self.workers.get(kind)
            if previous is not None and previous.isRunning():
                QMessageBox.warning(self, 'Receiver active',
                                    f'Stop {modality_label(kind)} before starting another stream.')
                return
            settings = validate_preprocessing(kind,
                preset=self.filter_choices[kind].currentData(),
                notch=self.filter_notches[kind].isChecked(),
                artifact_reduction=(self.artifact_choices[kind].currentData() if kind in self.artifact_choices else 'off'))
            worker = Receiver(info, kind, indices,
                              self.channel_selectors[kind].names,
                              preprocessing=settings,
                              conversion=self.source_conversions[kind].conversion(),
                              eeg_asr_model=(self.asr_session.model
                                             if kind == 'EEG' and self.asr_session.enabled else None))
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, f'{modality_label(kind)} channel selection', str(exc))
            return
        self.reset_stream_display(kind)
        worker.stream_ready.connect(self.ready_stream)
        worker.display_scale_ready.connect(self.set_stream_display_scale)
        worker.iaf_hz = self.iaf_hz
        worker.failure.connect(self.statusBar().showMessage)
        worker.finished.connect(lambda k=kind, w=worker: self.receiver_finished(k, w))
        self.workers[kind] = worker
        self.sync_affect_sources()
        self.source_conversions[kind].setEnabled(False)
        set_action(self.stream_buttons[kind], 'Stop', 'stop-white')
        self.stream_buttons[kind].setEnabled(True)
        worker.start()
        self.statusBar().showMessage(f'{modality_label(kind)}: starting selected LSL stream reception')

    def receive(self, kind, raw, processed, names, metric, fs, timestamps, metric_at=None,
                refresh_labels=True):
        if kind == 'EEG' and metric is not None and '_eeg_asr_id' in metric:
            expected = self.asr_session.model.model_id if self.asr_session.enabled else None
            if metric['_eeg_asr_id'] != expected:
                return  # Never mix queued data from different ASR processing modes.
        self.append_raw_chunk(kind, raw, processed, names, fs, timestamps)
        if metric is None:
            return
        at = time.monotonic() if metric_at is None else float(metric_at)
        self.metric_state.update(kind, metric, at,source_clock_offset=self._affect_clock_offset)
        if len(timestamps):
            if '_tonic_pipeline' in metric:
                configuration = metric['_tonic_pipeline']
                if configuration != self._tonic_live_configuration:
                    self._tonic_live_configuration = configuration
                    self.refresh_affect_references()
            self.affect_state.update(kind, metric, float(timestamps[-1]))
        if refresh_labels:
            self.refresh_metric_labels()
        self.metric_dirty = True

    def set_stream_display_scale(self, kind, scale, unit):
        self.raw_display.set_units(kind, scale, unit)

    def displayed_value(self, kind, name, value):
        return self.metric_state.normalized_value(
            kind, name, value, self.normalization.currentData(), self.metric_references())

    def refresh_metrics(self, *_):
        # Explicit normalization/baseline/source changes require a rebuild.
        # Ordinary live metric samples do NOT call this method.
        self.metric_presentation_epoch += 1
        self.refresh_metric_labels()
        self.metric_dirty = True

    def refresh_metric_labels(self):
        available = set()
        for (kind, name), label in self.metric_labels.items():
            raw = self.metric_state.latest.get(kind, {}).get(name)
            value = self.displayed_value(kind, name, raw)
            unit, detail = metric_amplitude_label(self.metric_definitions, {(kind, name)},
                self.normalization.currentData(), self.raw_display.units)
            if name == 'IAF':
                unit = 'Hz'
            label.setText(f'{name}: {value:.3f} {unit}' if value is not None else f'{name}: —')
            label.setToolTip(detail)
            if name != 'IAF' and value is not None:
                available.add(kind)
        for kind, label in self.metric_status.items():
            status = self.metric_state.latest.get(kind, {}).get('status')
            if kind == 'EEG' and self.eeg_reference_pending:
                status = 'Updating EEG baseline references…'
            if kind == 'EI':
                if kind in available:
                    status = 'Live' if self.normalization.currentData() == 'identity' else 'Live · BSL normalized'
                else:
                    status = (self.metric_state.ei_unavailable_reason() if self.metric_state.ei.value() is None
                              else 'EI needs compatible BSL references with usable variability for the selected normalization')
            if kind in available and (not status or status.startswith('Waiting for cvxEDA')):
                status = 'Live' if self.normalization.currentData() == 'identity' else 'Live · BSL normalized'
            label.setText(status or 'Waiting for data')

    def set_metric_renderer(self, *_):
        """Swap only Metrics presentation, keeping computation untouched."""
        mode = self.metric_renderer_choice.currentData()
        if mode == self.metric_renderer_mode:
            return
        if mode == 'vispy' and self.vispy_metric_plot is None:
            try:
                self.vispy_metric_plot = VisPyMetricPlot(self.metric_state.keys)
                self.metric_plot_stack.addWidget(self.vispy_metric_plot.widget)
            except Exception as exc:
                self.metric_renderer_choice.blockSignals(True)
                self.metric_renderer_choice.setCurrentIndex(0)
                self.metric_renderer_choice.blockSignals(False)
                QMessageBox.warning(
                    self, 'Metrics OpenGL unavailable',
                    f'Could not initialize VisPy metrics renderer: {exc}'
                )
                return
        self.metric_renderer_mode = mode
        self.metric_plot_stack.setCurrentIndex(1 if mode == 'vispy' else 0)
        self.set_metric_vertical_auto(self.metric_y_auto.isChecked())
        if not self.metric_y_auto.isChecked() and self._metric_manual_y is not None:
            self._apply_metric_y_range(*self._metric_manual_y)
        self.update_metric_xrange()
        self.metric_dirty = True
        self.refresh_metric_plot()

    def _metric_vertical_auto_changed(self, enabled):
        if not enabled:
            self._metric_manual_y = (self.vispy_metric_plot.y_range
                if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot is not None
                else tuple(self.metric_plot.viewRange()[1]))
        self.set_metric_vertical_auto(enabled)

    def set_metric_vertical_auto(self, enabled):
        self.metric_plot.enableAutoRange(axis='y', enable=enabled)
        if self.vispy_metric_plot is not None:
            self.vispy_metric_plot.set_y_auto(enabled)

    def _apply_metric_y_range(self, low, high):
        self._metric_manual_y = (low, high)
        if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot is not None:
            self.vispy_metric_plot.set_y_range(low, high)
        else:
            self.metric_plot.setYRange(low, high, padding=0)

    def zoom_metric_y(self, factor):
        self.metric_y_auto.setChecked(False)
        if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot is not None:
            low, high = self.vispy_metric_plot.y_range
        else:
            low, high = self.metric_plot.viewRange()[1]
        center, half = (low+high)/2., (high-low)*factor/2.
        self._apply_metric_y_range(center-half, center+half)

    def fit_metric_y(self):
        self.metric_y_auto.setChecked(False)
        if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot is not None:
            self.vispy_metric_plot.fit_y()
            self._metric_manual_y = self.vispy_metric_plot.y_range
            return
        left, right = self.metric_plot.viewRange()[0]
        values = []
        for key in self.metric_curves:
            if self.metric_checks[key].isChecked():
                for curve in (self.metric_curves[key], self.metric_point_curves[key]):
                    if not curve.isVisible():
                        continue
                    x, y = curve.getData()
                    if x is not None:
                        mask = (x >= left) & (x <= right) & np.isfinite(y)
                        values.extend(y[mask])
        if values:
            low, high = float(np.min(values)), float(np.max(values))
            pad = max(.1, (high-low)*.08)
            self._apply_metric_y_range(low-pad, high+pad)
        else:
            self._apply_metric_y_range(-1., 1.)

    def set_metric_time_window(self, *_):
        seconds = self.metric_time_window.currentData()
        if seconds is None:
            return
        self.metric_view_seconds = float(seconds)
        self.resume_metric_live()

    def zoom_metric_plot(self, scale):
        self.metric_view_seconds = float(np.clip(
            self.metric_view_seconds * scale, 1.0, self.settings.history_seconds
        ))
        self.metric_time_window.blockSignals(True)
        idx = self.metric_time_window.findData(self.metric_view_seconds)
        if idx < 0:
            self.metric_time_window.addItem(f'{self.metric_view_seconds:g} s', self.metric_view_seconds)
            idx = self.metric_time_window.count()-1
        self.metric_time_window.setCurrentIndex(idx)
        self.metric_time_window.blockSignals(False)
        self.resume_metric_live()

    def resume_metric_live(self):
        self.metric_follow_live = True
        self.metric_dirty = True
        set_action(self.metric_live_button, 'Live', 'live')
        self.metric_live_button.setEnabled(False)
        self.update_metric_xrange()

    def metric_view_changed_manually(self, *_):
        if self.metric_renderer_mode == 'vispy':
            return
        xlow, xhigh = self.metric_plot.viewRange()[0]
        span = float(max(.01, xhigh - xlow))
        is_zoom = abs(span - self.metric_view_seconds) > max(.001, .001*self.metric_view_seconds)
        was_following = self.metric_follow_live
        self.metric_view_seconds = span
        if was_following and is_zoom:
            self.update_metric_xrange()
        else:
            self.metric_follow_live = False
            set_action(self.metric_live_button, 'Follow live', 'live')
            self.metric_live_button.setEnabled(True)

    def update_metric_xrange(self):
        if self.metric_follow_live:
            elapsed = time.monotonic() - self.metric_plot_origin
            self.metric_gl_bounds = (
                elapsed - self.metric_view_seconds, elapsed
            )
            if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot:
                self.vispy_metric_plot.set_xrange(*self.metric_gl_bounds)
            else:
                self.metric_plot.setXRange(*self.metric_gl_bounds, padding=0)

    def refresh_metric_plot(self, *_):
        now = time.monotonic()
        method = self.metric_smoothing.currentData()
        duration = self.metric_smoothing_duration.currentData()
        interpolation = self.metric_interpolation.currentData()
        show_markers = self.metric_sample_markers.isChecked()
        gpu = self.vispy_metric_plot if self.metric_renderer_mode == 'vispy' else None
        ruler_keys = set()
        if gpu and hasattr(gpu, 'set_presentation_signature'):
            gpu.set_presentation_signature((
                self.normalization.currentData(), method, float(duration),
                interpolation, bool(show_markers),
                self.metric_presentation_epoch,
            ))
        for (kind, name), curve in self.metric_curves.items():
            key = (kind, name)
            visible = self.metric_checks[key].isChecked()
            markers = self.metric_point_curves[key]
            if not gpu:
                curve.setVisible(visible)
                markers.setVisible(visible and (show_markers or interpolation == 'none'))
            if not visible:
                if gpu:
                    empty = np.empty(0)
                    gpu.set_series(key, empty, empty, empty, empty, visible=False)
                continue
            points = [(t, val) for t, val in self.metric_state.history[key]
                      if now - t <= 300]
            if not points:
                if gpu:
                    empty = np.empty(0)
                    gpu.set_series(key, empty, empty, empty, empty, visible=False)
                else:
                    curve.clear()
                    markers.clear()
                continue
            timestamps = np.asarray(
                [t - self.metric_plot_origin for t, _ in points], dtype=float
            )
            display = [self.displayed_value(kind, name, val) for _, val in points]
            values = np.asarray(
                [float(v) if v is not None else np.nan for v in display],
                dtype=float,
            )
            x, y, measured_x, measured_y = prepare_metric_curve(
                timestamps, values,
                smoothing=method, seconds=float(duration),
                interpolation=interpolation, display_hz=20.0,
                max_gap=1.1,
            )
            if np.isfinite(measured_y).any():
                ruler_keys.add(key)
            if gpu:
                gpu.set_series(
                    key, x, y, measured_x, measured_y,
                    visible=visible, show_line=interpolation != 'none',
                    show_markers=show_markers or interpolation == 'none',
                )
            else:
                if interpolation == 'none':
                    curve.clear()
                else:
                    curve.setData(x, y, connect='finite')
                if show_markers or interpolation == 'none':
                    markers.setData(measured_x, measured_y)
                else:
                    markers.clear()
        if gpu:
            gpu.refresh_axes()
        self.metric_ruler_keys = ruler_keys
        self.update_metric_rulers()
        self.metric_dirty = False

    def update_metric_rulers(self, *_):
        unit, description = metric_amplitude_label(
            self.metric_definitions, self.metric_ruler_keys,
            self.normalization.currentData(), self.raw_display.units)
        if self.metric_renderer_mode == 'vispy' and self.vispy_metric_plot is not None:
            self.vispy_metric_plot.set_amplitude_units(unit, description)
            return
        box = self.metric_plot.getViewBox()
        (left, right), (bottom, top) = box.viewRange()
        rect = box.sceneBoundingRect()
        self.metric_time_ruler.set_scale((right-left)/max(1., rect.width()), 's')
        self.metric_amplitude_ruler.set_scale((top-bottom)/max(1., rect.height()), unit)
        self.metric_amplitude_ruler.setToolTip(description)

    def append_raw_chunk(self, kind, raw, processed, names, fs, timestamps):
        self.raw_display.append(kind, raw, processed, names, fs, timestamps)

    def set_raw_renderer(self, *_):
        """Switch only the Raw Data presentation backend at runtime."""
        mode = self.raw_renderer_choice.currentData()
        if mode == self.raw_renderer_mode:
            return
        if mode == 'vispy':
            try:
                for kind, stack in self.raw_plot_stacks.items():
                    if kind not in self.raw_vispy_plots:
                        gpu_started = time.perf_counter()
                        renderer = VisPyRawPlot(kind)
                        self.raw_vispy_plots[kind] = renderer
                        stack.addWidget(renderer.widget)
                        self.performance.measure(
                            'raw_gpu_canvas_init_' + kind,
                            time.perf_counter() - gpu_started)
            except Exception as exc:
                self.raw_renderer_choice.blockSignals(True)
                self.raw_renderer_choice.setCurrentIndex(0)
                self.raw_renderer_choice.blockSignals(False)
                QMessageBox.warning(self, 'OpenGL renderer unavailable',
                                    f'Could not initialize VisPy/OpenGL: {exc}')
                return
        self.raw_renderer_mode = mode
        for kind, stack in self.raw_plot_stacks.items():
            stack.setCurrentIndex(1 if mode == 'vispy' else 0)
        # Manual GPU panning is excluded from this first A/B experiment.
        if mode == 'vispy':
            self.resume_raw_live()
        else:
            # A paused renderer switch cannot rely on a subsequent live tick
            # to replace the fallback plot's initial empty (-5, 0) range.
            for plot in self.plots.values():
                plot.setXRange(*self.raw_display.bounds, padding=0)
        self.raw_display.dirty = True
        self.statusBar().showMessage(
            'Raw Data renderer: ' + ('VisPy / OpenGL (experimental)'
                                    if mode == 'vispy' else 'pyqtgraph')
        )

    def set_raw_vertical_gain(self, kind):
        """Independent per-modality gain; one uniform gain for all EEG leads."""
        if kind in self.raw_vispy_plots:
            self.raw_vispy_plots[kind].set_vertical_gain(
                self.raw_vertical_gains[kind].value()
            )
        self.raw_display.dirty = True

    def adjust_raw_vertical_gain(self, kind, multiplier):
        control = self.raw_vertical_gains[kind]
        control.setValue(float(np.clip(control.value() * multiplier,
                                       self.settings.gain_minimum, self.settings.gain_maximum)))

    def autoscale_raw(self, kind):
        # Normal GPU frames contain only the new tail. Ask the preparation
        # worker for the whole displayed window before measuring extrema.
        if kind not in self.raw_display.frames:
            return
        self.raw_display.request_autoscale(kind)

    def _apply_autoscale(self, kind, frame):
        head = (frame[0][-1]
                if self.raw_renderer_mode == 'vispy'
                else self.plots[kind].viewRange()[0][1])
        gain = visible_gain(frame, self.raw_display.view_seconds,
                            self.show_raw.isChecked(), self.show_processed.isChecked(), head)
        if gain is None:
            self.statusBar().showMessage(f'{modality_label(kind)}: no visible signal variation to autoscale')
            return
        control = self.raw_vertical_gains[kind]
        control.setDecimals(max(2, min(12, int(np.ceil(-np.log10(gain)))+3)))
        control.setRange(min(control.minimum(), gain), max(control.maximum(), gain))
        control.setValue(gain)
        self.statusBar().showMessage(f'{modality_label(kind)}: amplitude fitted to visible extrema')

    def set_raw_time_window(self, *_):
        seconds = self.raw_time_window.currentData()
        if seconds is not None:
            self.raw_display.set_window(seconds)
            self.resume_raw_live()

    def zoom_raw_plots(self, factor):
        self.raw_display.set_window(np.clip(
            self.raw_display.view_seconds * factor, 1.0, self.settings.history_seconds))
        self.raw_time_window.blockSignals(True)
        index = self.raw_time_window.findData(self.raw_display.view_seconds)
        if index < 0:
            seconds = self.raw_display.view_seconds
            self.raw_time_window.addItem(f'{seconds:g} s', seconds)
            index = self.raw_time_window.count()-1
        self.raw_time_window.setCurrentIndex(index)
        self.raw_time_window.blockSignals(False)
        self.resume_raw_live()

    def resume_raw_live(self):
        self.raw_display.follow_live = True
        set_action(self.raw_live_button, 'Live', 'live')
        self.raw_live_button.setEnabled(False)
        self.update_raw_xranges()
        self.raw_display.dirty = True

    def raw_view_changed_manually(self, kind, *_):
        if QApplication.activePopupWidget() is not None:
            self.raw_display.dirty = True
            return
        low, high = self.plots[kind].viewRange()[0]
        span = float(max(.01, high - low))
        was_following = self.raw_display.follow_live
        # A wheel zoom changes the width of the time axis; it should
        # NOT freeze live acquisition. Horizontal dragging translates the
        # viewport without changing its width and deliberately pauses it.
        is_zoom = abs(span - self.raw_display.view_seconds) > max(.001, .001*self.raw_display.view_seconds)
        self.raw_display.set_window(span)
        if was_following and is_zoom:
            self.update_raw_xranges()
        else:
            self.raw_display.follow_live = False
            set_action(self.raw_live_button, 'Follow live', 'live')
            self.raw_live_button.setEnabled(True)
            for other, plot in self.plots.items():
                if other != kind:
                    plot.setXRange(low, high, padding=0)
        self.draw()

    def raw_view_scrolled(self, *_):
        # Let the user drag the scroll bar without competing with plot paints.
        self.raw_display.interacting_until = time.monotonic() + .16
        self.raw_display.dirty = True

    def raw_plot_visible(self, kind):
        widget = self.raw_plot_stacks[kind]
        return self.tabs.currentWidget() is self.raw_page and widget.isVisible()

    def update_raw_xranges(self):
        changed = self.raw_display.advance(time.monotonic())
        if self.raw_renderer_mode == 'vispy' and changed:
            self.raw_display.dirty = True
        elif self.raw_renderer_mode == 'pyqtgraph' and changed:
            for kind, plot in self.plots.items():
                if self.raw_plot_visible(kind):
                    plot.setXRange(*self.raw_display.bounds, padding=0)

    def tab_changed(self, index):
        if hasattr(self, 'affect_view'):
            self.affect_view.set_active(self.tabs.widget(index) is self.affect_page)
        if self.tabs.widget(index) is self.raw_page:
            self.raw_display.tab_entered_at = time.perf_counter()
            self.raw_display.dirty = True
            self.raw_display.last_render_at = 0.
            # Never submit a first large EEG render synchronously from the
            # tab-change event. The regular timer handles acquisition first
            # and schedules one latest-only background reduction afterwards.
        elif self.tabs.widget(index) is self.metrics_page and not self.metric_plot_paused:
            self.refresh_metric_labels()
            self.metric_dirty = True
            # Paint after Qt has handled the tab change, on the display timer.

    def poll_receivers(self):
        """Consume bounded LSL chunks on the GUI timer, not per sample event."""
        started = time.perf_counter()
        incoming = []
        for kind, worker in tuple(self.workers.items()):
            if kind in self.pending_source_changes and self.capture is None:
                worker.mailbox.drain(max_chunks=self.settings.ingress_chunks_per_tick)
                continue  # Discard old-source samples while replacement is pending.
            for chunk in worker.mailbox.drain(max_chunks=self.settings.ingress_chunks_per_tick):
                incoming.append((chunk.acquired_at, kind, chunk))
        # Chronological ingestion matters for EI when EDA/PPG arrive on
        # separate threads; the GUI must not re-time buffered observations.
        incoming.sort(key=lambda entry: entry[0])
        for acquired_at, kind, chunk in incoming:
            if self.capture is not None:
                self.capture_samples(kind, chunk.raw, chunk.timestamps, chunk.names, chunk.fs)
            self.receive(kind, chunk.raw, chunk.filtered, chunk.names, chunk.metric,
                         chunk.fs, chunk.timestamps, metric_at=acquired_at, refresh_labels=False)
        if incoming and self.tabs.currentWidget() is self.metrics_page:
            self.refresh_metric_labels()
        self.performance.measure('ingress_gui', time.perf_counter() - started)

    def refresh_asr_indicator(self, now):
        worker = self.workers.get('EEG')
        state, text, detail = asr_runtime_state(worker, now, 'EEG' in self.pending_source_changes)
        signature = (state, text, detail)
        if signature != self._last_asr_indicator:
            color = {'idle': '#77768f', 'off': '#77768f', 'waiting': '#a56900',
                     'bypassed': '#bd253b', 'correcting': '#00875a', 'monitoring': '#77768f'}[state]
            self.raw_asr_status.setText('●')
            self.raw_asr_status.setAccessibleName(text)
            self.raw_asr_status.setStyleSheet(f'color: {color}; font-weight: 600; padding: 4px;')
            self.raw_asr_status.setToolTip(text+'\n'+detail)
            self._last_asr_indicator = signature

    def refresh_peripheral_indicators(self, now):
        for kind,label in self.raw_reduction_status.items():
            signature = peripheral_runtime_state(self.workers.get(kind),now,
                                                kind in self.pending_source_changes)
            if signature == self._last_reduction_indicators.get(kind):
                continue
            state,text,detail = signature
            color = {'idle':'#77768f','off':'#77768f','waiting':'#a56900',
                     'correcting':'#00875a','monitoring':'#77768f'}[state]
            label.setText('●')
            label.setAccessibleName(text)
            label.setStyleSheet(f'color: {color}; font-weight: 600; padding: 4px;')
            label.setToolTip(text+'\n'+detail)
            self._last_reduction_indicators[kind] = signature

    def render_frame(self):
        started = time.perf_counter()
        now = time.monotonic()
        self.performance.measure('tick_delay', max(0., now - self._last_gui_tick - self.settings.timer_interval_ms / 1000.))
        self._last_gui_tick = now
        self.refresh_asr_indicator(now)
        self.refresh_peripheral_indicators(now)
        if not self._closing:
            # No GUI sample draining or rendering while a menu is open.
            # Source threads keep collecting into bounded mailboxes instead.
            popup_open = QApplication.activePopupWidget() is not None
            if not popup_open:
                self.poll_receivers()
            self.update_raw_xranges()
            if not popup_open:
                if (self.tabs.currentWidget() is self.raw_page
                        and (not self.raw_display.paused or self.raw_display.autoscale_requests
                             or self._raw_trace_selection_refresh)):
                    if now >= self.raw_display.interacting_until:
                        # The precise GUI timer caps frequency; the in-flight
                        # ticket prevents overlapping preparation requests.
                        if self.raw_display.dirty:
                            self.draw()
                elif self.tabs.currentWidget() is self.metrics_page and not self.metric_plot_paused:
                    self.update_metric_xrange()
                    if self.metric_dirty:
                        self.refresh_metric_plot()
                elif self.tabs.currentWidget() is self.affect_page:
                    self.refresh_affect_view()
                self.warm_raw_renderers()
        self.performance.measure('gui_timer_total', time.perf_counter() - started)
        if self.performance.enabled:
            self.performance.maybe_flush({
                kind: worker.mailbox.stats()
                for kind, worker in self.workers.items()
            })

    def warm_raw_renderers(self):
        """Link one spare channel pair per tick, before the user needs it.

        Reserve the acquired channel count, not just the visible EEG subset.
        Smaller panels finish first; all work stays on the OpenGL GUI thread.
        """
        if (self.raw_renderer_mode != 'vispy'
                or self.tabs.currentWidget() not in (self.sources_page, self.raw_page)
                or os.environ.get('QT_QPA_PLATFORM', '').lower() == 'offscreen'):
            return
        candidates = []
        for kind, renderer in self.raw_vispy_plots.items():
            worker = self.workers.get(kind)
            info = worker.info if worker is not None else self.selectors[kind].currentData()
            if info is None or info.nominal_srate() <= 0:
                continue
            count = (len(worker.selected_names) if worker is not None
                     else len(self.channel_selectors[kind].selected_indices()))
            if count > renderer.reserved_channel_count:
                candidates.append((count, kind, renderer, info.nominal_srate()))
        for count, kind, renderer, fs in sorted(candidates, key=lambda item: item[0]):
            started = time.perf_counter()
            if renderer.warm_channels(count, self.raw_display.view_seconds, fs):
                self.performance.measure('raw_gpu_warmup_' + kind,
                                         time.perf_counter() - started)
                break

    def raw_trace_selection_changed(self):
        self.raw_display.references.pop('EEG', None)
        self.raw_display.frames.pop('EEG', None)
        self.raw_display.invalidate()
        self._raw_trace_selection_refresh = True
        if 'EEG' in self.raw_vispy_plots:
            self.raw_vispy_plots['EEG'].invalidate_history()

    def draw(self):
        """Submit a lightweight snapshot; never reduce data on the GUI thread."""
        if self.tabs.currentWidget() is not self.raw_page or self.raw_display.origin is None:
            return
        if QApplication.activePopupWidget() is not None or self.raw_display.inflight_ticket is not None:
            return
        self.raw_display.dirty = False
        self.raw_display.last_render_at = time.monotonic()
        sources = {}
        for kind, chunks in self.raw_display.history.items():
            if not chunks or not self.raw_plot_visible(kind):
                continue
            display_count = min(chunks[-1][1].shape[1],
                                self.eeg_display_count.value() if kind == 'EEG'
                                else RAW_DISPLAY_POLICY.max_single_channels)
            if self.raw_renderer_mode == 'vispy':
                # Two consecutive sweep cycles are needed: the completed
                # cycle remains visible to the right of the advancing head.
                _, high = self.raw_display.bounds
                low = high - RAW_DISPLAY_POLICY.history_cycles * self.raw_display.view_seconds
            else:
                low, high = self.plots[kind].viewRange()[0]
            renderer = self.raw_vispy_plots.get(kind)
            latest = None
            if (renderer is not None
                    and renderer.sweep_duration == self.raw_display.view_seconds
                    and np.isfinite(renderer.latest_sample_time)
                    and not renderer.history_needs_replay(
                        display_count,
                        self.raw_display.view_seconds)):
                latest = float(renderer.latest_sample_time)
            replay_history = (
                self.raw_renderer_mode == 'vispy'
                and renderer is not None
                and renderer.history_needs_replay(
                    display_count,
                    self.raw_display.view_seconds))
            if kind in self.raw_display.autoscale_requests:
                latest = None
                replay_history = True
            source = build_raw_source(
                chunks, left=low, right=high,
                replay_history=replay_history,
                origin=self.raw_display.origin,
                reference=self.raw_display.references.get(kind),
                vispy=self.raw_renderer_mode == 'vispy',
                latest=latest, sweep_seconds=self.raw_display.view_seconds,
                max_channels=display_count,
                shared_scale=self.raw_display.display_scales.get(kind),
                fit_traces=kind in ('PPG', 'EDA'),
                center_trace=('filtered' if kind == 'EEG' and self.show_processed.isChecked() else 'raw'),
            )
            if source is not None:
                sources[kind] = source
        request = self.raw_display.begin_frame(sources)
        if request is not None:
            self.raw_render_worker.submit(request)

    def apply_raw_frame(self, response):
        """Accept at most one completed raw frame; no Qt signal backlog."""
        started = time.perf_counter()
        self.performance.measure('raw_prepare', response.prepare_ms / 1000.)
        if response.queued_at is not None:
            self.performance.measure(
                'raw_worker_roundtrip',
                max(0., time.perf_counter() - response.queued_at)
            )
        if not self.raw_display.accepts(response.ticket, response.version):
            return
        if (self.tabs.currentWidget() is not self.raw_page
                or (self.raw_display.paused and not self.raw_display.autoscale_requests
                    and not self._raw_trace_selection_refresh)
                or QApplication.activePopupWidget() is not None
                or time.monotonic() < self.raw_display.interacting_until):
            self.raw_display.dirty = True
            return
        presentation_head = (self.raw_display.bounds[1] if response.presentation_head is None
                             else response.presentation_head)
        self._raw_trace_selection_refresh = False
        for kind, frame in response.frames.items():
            if not self.raw_plot_visible(kind) or frame is None:
                continue
            timestamps, raw, filtered, centers, spreads, names = frame
            self.raw_autoscale_buttons[kind].setEnabled(True)
            if kind in self.raw_display.autoscale_requests:
                self.raw_display.autoscale_requests.discard(kind)
                self._apply_autoscale(kind, frame)
            plot = self.plots[kind]
            n = raw.shape[1]
            changed = self.raw_display.remember_frame(kind, frame)
            if kind in ('PPG', 'EDA') and changed and kind in self.raw_vispy_plots:
                self.raw_vispy_plots[kind].invalidate_history()
            if self.raw_renderer_mode == 'vispy':
                self.raw_vispy_plots[kind].set_amplitude_units(
                    DEFAULT_EEG_DISPLAY_STEP if kind == 'EEG' else float(spreads[0]),
                    self.raw_display.units.get(kind, ARBITRARY_UNIT))
                self.raw_vispy_plots[kind].set_vertical_gain(
                    self.raw_vertical_gains[kind].value()
                )
                gpu_started = time.perf_counter()
                self.raw_vispy_plots[kind].set_frame(
                    frame, 0., self.raw_display.view_seconds,
                    show_raw=self.show_raw.isChecked(),
                    show_filtered=self.show_processed.isChecked(),
                    sweep_head=presentation_head,
                    nominal_fs=(self.raw_display.history[kind][-1][4]
                                if self.raw_display.history[kind] else None),
                )
                self.performance.measure(
                    'raw_gpu_frame_' + kind,
                    time.perf_counter() - gpu_started)
                if self.raw_display.tab_entered_at is not None:
                    self.performance.measure(
                        'raw_tab_to_first_frame',
                        max(0., time.perf_counter() - self.raw_display.tab_entered_at))
                    self.raw_display.tab_entered_at = None
                continue
            if len(self.curves[kind]) != 2 * n:
                plot.clear()
                self.curves[kind] = []
                plot.enableAutoRange(axis='y', enable=False)
                plot.setYRange(*RAW_DISPLAY_POLICY.bounds(n), padding=0)
                plot.getAxis('left').setTicks([
                    list(zip(RAW_DISPLAY_POLICY.offsets(n), map(str, names)))])
                for i, name in enumerate(names):
                    color = pg.intColor(i, hues=max(n, 3))
                    self.curves[kind].append(plot.plot(
                        name=f'{name} raw', pen=pg.mkPen(color, width=1),
                        connect='finite', antialias=False
                    ))
                    self.curves[kind].append(plot.plot(
                        name=f'{name} processed',
                        pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
                        connect='finite', antialias=False
                    ))
            gain = self.raw_vertical_gains[kind].value()
            for i in range(n):
                offset = RAW_DISPLAY_POLICY.channel_spacing * i
                if self.show_raw.isChecked():
                    self.curves[kind][2*i].setData(
                        timestamps, offset + gain * (raw[:, i] - offset))
                else:
                    self.curves[kind][2*i].clear()
                if self.show_processed.isChecked():
                    self.curves[kind][2*i+1].setData(
                        timestamps, offset + gain * (filtered[:, i] - offset))
                else:
                    self.curves[kind][2*i+1].clear()
        if self.raw_renderer_mode == 'vispy':
            committed_head = presentation_head
            self.raw_display.committed_head = committed_head
            for kind, renderer in self.raw_vispy_plots.items():
                if self.raw_plot_visible(kind) and renderer.configured:
                    renderer.set_sweep_head(committed_head)
        self.performance.measure('raw_qt_paint', time.perf_counter() - started)

    def ready_stream(self, kind, channels, fs):
        if kind == 'EEG':
            worker = self.workers.get(kind)
            asr_bypassed = self.asr_session.enabled and getattr(worker, 'eeg_asr_model', None) is None
            if asr_bypassed:
                self.asr_session.set_enabled(False)
                self.reset_stream_display('EEG')
            live = deepcopy(getattr(worker, 'source_configuration', None))
            if live is not None:
                live.pop('asr_model_id', None)
            if asr_bypassed or live != self._reference_source_configuration:
                self._apply_asr_metric_references()
            self.update_asr_availability()
        if kind == 'EDA':
            metadata = getattr(self.workers.get(kind), 'tonic_metadata', None) or {}
            self._tonic_live_configuration = metadata.get('configuration_id')
        self.refresh_affect_references()
        self.statusBar().showMessage(f'{modality_label(kind)} ready: {len(channels)} channels at {fs:g} Hz')

    def capture_samples(self, kind, samples, timestamps, channels, fs):
        if self.capture is not None:
            self.capture.append(kind, samples, timestamps, channels, fs, time.monotonic())

    def record_calibration(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration', 'A calibration is already running.')
            return
        connected = {modality: worker for modality, worker in self.workers.items()
                     if worker.isRunning() and worker.active}
        if kind == 'EYC' and 'EEG' not in connected:
            QMessageBox.warning(self, 'EYC calibration', 'Connect an EEG LSL stream first.')
            return
        if kind == 'BSL' and not connected:
            QMessageBox.warning(self, 'BSL calibration', 'Connect at least one LSL stream first.')
            return
        instruction = ('Close your eyes for 60 seconds. Press Esc to cancel.'
                       if kind == 'EYC' else
                       'Look steadily at the white dot for 60 seconds. Press Esc to cancel.')
        QMessageBox.information(self, f'{kind} instructions', instruction)
        # Record every connected modality during BSL, EEG during EYC.
        included = ['EEG'] if kind == 'EYC' else list(connected)
        meta = {}
        for modality in included:
            worker = connected[modality]
            info = worker.info
            channels = list(worker.selected_names)
            meta[modality] = {
                'fs': float(info.nominal_srate()), 'channels': channels,
                'preprocessing': dict(worker.preprocessing),
                'conversion': worker.conversion.metadata(),
                'source_units': list(worker.source_units),
                'units': list(worker.output_units),
                'chunks': [], 'times': [],
                'start_lsl_timestamp': worker.latest_source_timestamp,
            }
        screen = CalibrationScreen(kind, self)
        self.capture = CalibrationSession(
            kind, meta, time.monotonic() + DURATION_SECONDS + 1)
        result = screen.exec()
        session = self.capture
        self.capture = None
        for modality in tuple(self.pending_source_changes):
            self.schedule_source_change(modality)
        if kind == 'EYC':
            QMessageBox.information(self, 'EYC finished', 'Open your eyes.')
        if result != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage(f'{kind} cancelled; no calibration saved')
            return
        try:
            streams = session.finish()
        except ValueError as exc:
            QMessageBox.warning(self, 'Recording incomplete', str(exc))
            return
        try:
            analysis = self.analyze_calibration_background(kind, streams)
        except Exception as exc:
            QMessageBox.warning(self, 'Calibration analysis failed', str(exc))
            return
        # Activate the completed recording before optional inspection/saving.
        # ASR fitting must not depend on whether the user saves an NPZ file.
        self.apply_calibration(kind, {'analysis': analysis}, streams=streams)
        self.inspect_calibration(kind, analysis)
        answer = QMessageBox.question(
            self, f'Save {kind} calibration?', 'Save recorded calibration data and analysis?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, f'Save {kind}', f'{kind.lower()}_calibration.npz', 'Calibration (*.npz)'
        )
        if not filename:
            return
        if not filename.lower().endswith('.npz'):
            filename += '.npz'
        try:
            save_calibration(filename, kind, streams, analysis)
        except Exception as exc:
            QMessageBox.critical(self, 'Save failed', str(exc))
            return
        self.set_calibration_file(kind, filename)
        self.statusBar().showMessage(f'Saved {kind}: {filename}')

    def analyze_calibration(self, kind, streams):
        if kind == 'EYC':
            if 'EEG' not in streams:
                raise ValueError('An EEG stream is required')
            return analyze_eyc(streams['EEG'])
        return analyze_bsl(streams, iaf_hz=self.iaf_hz)

    def analyze_calibration_background(self, kind, streams):
        """Keep reception, raw plots and countdown/UI events responsive."""
        progress = QProgressDialog(f'Analyzing {kind} calibration…', '', 0, 0, self)
        progress.setWindowTitle('Calibration analysis')
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        task = CalibrationAnalysisTask(kind, streams, self.iaf_hz, self,
            eeg_asr_model=self.asr_session.model if self.asr_session.enabled else None)
        outcome = []

        def completed(result, error):
            outcome.extend((result, error))
            progress.accept()

        task.completed.connect(completed)
        task.start()
        progress.exec()
        task.wait()
        task.deleteLater()
        if not outcome:
            raise RuntimeError('Calibration analysis interrupted')
        if outcome[1] is not None:
            raise ValueError(outcome[1])
        return outcome[0]

    def inspect_calibration(self, kind, analysis):
        folder = Path(__file__).resolve().parent.parent / 'designer'
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(folder)))
        dlg = loader.load(str(folder / 'CalibrationInspection.ui'), self)
        if dlg is None:
            raise RuntimeError('Cannot load Designer calibration inspection')
        dlg.setWindowTitle(f'{kind} calibration inspection')
        summary = dlg.findChild(QLabel, 'calibrationSummary')
        pages = dlg.findChild(QStackedWidget, 'inspectionPages')
        if kind == 'EYC':
            summary.setText(
                f"Posterior alpha center of gravity: {analysis['iaf_hz']:.2f} Hz "
                f"(7–13 Hz), channels: {', '.join(analysis['posterior_channels'])}")
            plot = pg.PlotWidget(background='#ffffff')
            plot.setTitle('Average posterior-channel PSD (Welch, Hann, 1 s, 50% overlap)', color='#25234a')
            for axis in ('left', 'bottom'):
                plot.getAxis(axis).setPen('#77768f')
                plot.getAxis(axis).setTextPen('#25234a')
            plot.plot(analysis['psd_hz'], analysis['mean_psd'], pen=pg.mkPen('#312b79', width=2))
            plot.addLine(x=analysis['iaf_hz'], pen=pg.mkPen('#c74670', width=2))
            plot.setXRange(3, 20)
            plot.setLabel('bottom', 'Frequency', 'Hz', color='#25234a')
            plot.setLabel('left', 'PSD', color='#25234a')
            dlg.findChild(QFrame, 'spectrumHost').layout().addWidget(plot)
            pages.setCurrentWidget(dlg.findChild(QWidget, 'spectrumPage'))
        else:
            summary.setText('Baseline reference statistics')
            view = dlg.findChild(QPlainTextEdit, 'baselineStatistics')
            lines = [f"IAF used: {analysis['iaf_hz_used']:.2f} Hz", ""]
            for modality, fields in analysis['metrics'].items():
                lines.append(modality_label(modality))
                for name, stats in fields.items():
                    lines.append(
                        f"  {name}: μ={stats['mu']:.5g} σ={stats['sigma']:.5g} "
                        f"median={stats['median']:.5g} IQR={stats['iqr']:.5g} "
                        f"(N={stats['valid_windows']})")
                lines.append('')
            view.setPlainText('\n'.join(lines))
            pages.setCurrentWidget(dlg.findChild(QWidget, 'statisticsPage'))
        dlg.exec()
        dlg.deleteLater()

    def set_calibration_file(self, kind, filename):
        self.calibration_paths[kind] = filename
        file_label = self.calibration_file_labels[kind]
        file_label.setText(Path(filename).name if filename else 'Loaded (unsaved)')
        file_label.setToolTip(filename or 'Calibration active but not saved to a file')
        if kind == 'BSL':
            self.asr_session.filename = filename

    def apply_calibration(self, kind, meta, filename=None, streams=None):
        if kind == 'EYC':
            self.loaded_eyc = meta
            self.eyc_recording = deepcopy((streams or {}).get('EEG'))
            self.iaf_hz = float(meta['analysis']['iaf_hz'])
            for worker in self.workers.values():
                if worker.kind == 'EEG':
                    worker.iaf_hz = self.iaf_hz
        else:
            self.loaded_bsl = meta
            self.asr_session.set_baseline(meta.get('analysis'), streams, filename)
            # Compatible EI input references are reconciled below.
        self.set_calibration_file(kind, filename)
        self.calibration_state.setText(
            f"EYC: {self.iaf_hz:.2f} Hz"
            f" | BSL: {'loaded' if self.loaded_bsl else 'none'}"
        )
        self.update_metrics_availability()
        self.refresh_metrics()
        self.affect_state.clear()
        self.refresh_affect_references()
        self.update_asr_availability()
        self._apply_asr_metric_references()

    def load_existing(self, kind):
        filename, _ = QFileDialog.getOpenFileName(
            self, f'Open {kind} calibration', '', 'Calibration (*.npz)'
        )
        if not filename:
            return
        try:
            meta, streams = load_calibration(filename, kind)
            # Replay raw recordings through the current preprocessing chain for
            # both EYC PSD and BSL metric references; saved results may differ.
            analysis = self.analyze_calibration_background(kind, streams)
            self.inspect_calibration(kind, analysis)
            self.apply_calibration(kind, {'analysis': analysis}, filename=filename, streams=streams)
            self.statusBar().showMessage(f'Loaded {kind}: {filename}')
        except Exception as exc:
            QMessageBox.critical(self, f'Cannot load {kind}', str(exc))

    def closeEvent(self, event):
        self._closing = True
        for timer in self.source_change_timers.values():
            timer.stop()
        self.pending_source_changes.clear()
        self.timer.stop()
        for task in list(self.asr_tasks) + list(self.eeg_reference_tasks):
            task.wait()
        for task in list(self.lsl_tasks.values()):
            task.wait(3000)
        self.raw_render_worker.stop()
        for glplot in self.raw_vispy_plots.values():
            glplot.close()
        if self.vispy_metric_plot is not None:
            self.vispy_metric_plot.close()
        self.affect_view.close()
        for worker in self.workers.values():
            worker.stop()
        super().closeEvent(event)
