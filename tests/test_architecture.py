"""Executable import boundaries, including imports deferred inside functions."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PURE = {'metric_state', 'affect_state', 'asr_session', 'calibration_coordinator',
        'reference_policy', 'calibration_validation', 'calibration_contracts',
        'metric_observation', 'asr_training_policy', 'receiver_state',
        'signal_history', 'raw_display_state', 'raw_render', 'render_contracts'}
FORBIDDEN = {'PySide6', 'pyqtgraph', 'vispy', 'pylsl'}


def imports(tree):
    local, external = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            (local if node.level else external).add(node.module.split('.')[0])
        elif isinstance(node, ast.Import):
            external.update(item.name.split('.')[0] for item in node.names)
    return local, external


class ArchitectureTests(unittest.TestCase):
    def test_deferred_imports_are_checked(self):
        _, external = imports(ast.parse('def delayed():\n    from PySide6 import QtCore\n'))
        self.assertEqual(external & FORBIDDEN, {'PySide6'})

    def test_pure_models_have_no_transitive_gui_or_lsl_dependency(self):
        graph = {path.stem: imports(ast.parse(path.read_text(encoding='utf-8-sig')))
                 for path in (ROOT / 'physiolab').glob('*.py')}
        for module in PURE:
            seen, todo = set(), [module]
            while todo:
                name = todo.pop()
                if name in seen or name not in graph:
                    continue
                seen.add(name)
                local, external = graph[name]
                self.assertFalse(external & FORBIDDEN, f'{module} reaches {name}: {external & FORBIDDEN}')
                todo.extend(local)

    def test_relative_import_graph_has_no_cycles(self):
        graph = {path.stem: imports(ast.parse(path.read_text(encoding='utf-8-sig')))[0]
                 for path in (ROOT / 'physiolab').glob('*.py')}
        completed = set()

        def visit(name, stack):
            self.assertNotIn(name, stack, f'Import cycle: {stack + [name]}')
            if name in completed or name not in graph:
                return
            for dependency in graph[name]:
                visit(dependency, stack + [name])
            completed.add(name)

        for name in graph:
            visit(name, [])

    def test_model_import_does_not_load_storage_or_qt(self):
        code = ('import sys; import physiolab.metric_state; import physiolab.calibration_coordinator; '
                'from physiolab.metric_observation import eeg_configuration; '
                'assert "physiolab.calibration_storage" not in sys.modules; '
                'assert not any(n.startswith("PySide6") for n in sys.modules)')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
