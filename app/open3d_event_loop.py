"""Drive Open3D on Qt's GUI thread without entering a second event loop."""

from collections import deque
import traceback

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal


class Open3DEventLoop(QObject):
    failed = Signal(str)
    shutdown_ready = Signal()

    def __init__(self, application, parent=None):
        super().__init__(parent)
        self.application = application
        self.in_tick = False
        self.stopping = False
        self._shutdown_emitted = False
        self._pending = deque()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def _check_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Open3D must be accessed on the Qt GUI thread")

    def start(self):
        self._check_thread()
        if not self.stopping:
            self.timer.start()

    def defer(self, callback):
        """Run window creation/destruction outside native event callbacks."""
        self._check_thread()
        if not self.stopping:
            self._pending.append(callback)

    def request_shutdown(self):
        self._check_thread()
        self.stopping = True
        self.timer.stop()
        self._pending.clear()
        if not self.in_tick:
            self._emit_shutdown()

    def _emit_shutdown(self):
        if not self._shutdown_emitted:
            self._shutdown_emitted = True
            self.shutdown_ready.emit()

    def _tick(self):
        self._check_thread()
        if self.in_tick or self.stopping:
            return
        self.in_tick = True
        try:
            # Work queued by a callback during this tick waits for the next one.
            for _ in range(len(self._pending)):
                if self.stopping:
                    break
                self._pending.popleft()()
            if not self.stopping and not self.application.run_one_tick():
                self.request_shutdown()
        except Exception:
            self.failed.emit(traceback.format_exc())
            self.request_shutdown()
        finally:
            self.in_tick = False
            if self.stopping:
                QTimer.singleShot(0, self._emit_shutdown)
