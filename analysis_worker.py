"""Background analysis worker.

The worker only runs pure-Python loading/statistics/diagnostics/AI-summary
code.  Qt widgets are constructed by the main window after the result
arrives.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

import analysis_loader


class AnalysisWorker(QThread):
    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(
        self,
        generation,
        filename,
        target_fps=60,
        target_fps_explicit=False,
        language="zh_CN",
        scenario_override=None,
        parent=None,
    ):
        super().__init__(parent)

        self.generation = int(generation)
        self.filename = str(filename)
        self.target_fps = int(target_fps)
        self.target_fps_explicit = bool(target_fps_explicit)
        self.language = str(language)
        self.scenario_override = scenario_override

    def run(self):

        try:

            prepared = analysis_loader.load_analysis_bundle(
                self.filename,
                target_fps=self.target_fps,
                target_fps_explicit=self.target_fps_explicit,
                language=self.language,
                scenario_override=self.scenario_override,
            )

        except Exception as error:

            self.failed.emit(
                self.generation,
                str(error),
            )
            return

        if self.isInterruptionRequested():

            return

        self.ready.emit(self.generation, prepared)
