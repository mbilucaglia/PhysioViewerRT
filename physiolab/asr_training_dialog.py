"""Designer-owned subject feedback during adaptive ASR training."""
from pathlib import Path
from PySide6.QtCore import QDir, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton


class ASRTrainingDialog(QDialog):
    def __init__(self, minimum_seconds, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Train ASR · signal quality')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        folder = Path(__file__).resolve().parent.parent/'designer'
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(folder)))
        self.panel = loader.load(str(folder/'ASRTrainingCapture.ui'), self)
        if self.panel is None:
            raise RuntimeError('Cannot load ASR training capture UI')
        QVBoxLayout(self).addWidget(self.panel)
        self.minimum = minimum_seconds
        self.quality = self.panel.findChild(QLabel, 'trainingQuality')
        self.count = self.panel.findChild(QLabel, 'trainingCount')
        self.fit_status = self.panel.findChild(QLabel, 'trainingFitStatus')
        self.bar = self.panel.findChild(QProgressBar, 'trainingProgress')
        self.panel.findChild(QPushButton, 'trainingCancel').clicked.connect(self.reject)
        self.resize(560, 340)

    def show_status(self, status, elapsed, fitting=False, error=''):
        state = status['state']
        color = {'good': '#00875a', 'movement': '#a56900', 'bad': '#bd253b', 'warming': '#77768f'}[state]
        self.quality.setText('● '+status['reason'])
        self.quality.setStyleSheet(f'color: {color}; font-size: 16pt; font-weight: 600;')
        accepted = status['accepted_seconds']
        self.count.setText(f'Accepted EEG: {accepted:.0f} / {self.minimum:g} s minimum\n'
                          f'Elapsed: {elapsed:.0f} s · Excluded: {status["rejected_seconds"]:.0f} s')
        self.bar.setValue(min(100, int(100*accepted/self.minimum)))
        self.fit_status.setText('Checking ASR fit… recording continues.' if fitting else
            'ASR fit needs more data: '+error if error else
            'Stops automatically after enough accepted EEG and a successful ASR fit.')
