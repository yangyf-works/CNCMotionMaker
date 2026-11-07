"""Qt container for an existing Open3D HWND; no image readback is involved."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


class Open3DHost(QWidget):
    def __init__(self, native_api, parent=None):
        super().__init__(parent)
        self.native_api = native_api
        self.handle = None
        self.foreign_window = None
        self.container = None
        self.setMinimumSize(320, 240)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def attach(self, title):
        self.handle = self.native_api.find_window(title)
        self.native_api.remove_frame(self.handle)
        self.foreign_window = QWindow.fromWinId(self.handle.hwnd)
        if self.foreign_window is None:
            raise RuntimeError("Qt could not wrap the Open3D native window")
        self.container = QWidget.createWindowContainer(self.foreign_window, self)
        self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.container.installEventFilter(self)
        self.container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._layout.addWidget(self.container)
        # Let the container reparent on Show. Manually reparenting here would
        # detach it from the container's geometry/focus management.
        self.container.winId()

    def verify_embedding(self):
        # Called after QMainWindow.show(), when Qt has replaced its temporary
        # parent with the native container. Ownership alone is insufficient.
        self.native_api.verify_child(self.handle, int(self.container.winId()))

    def start_keyboard_routing(self):
        self.native_api.route_keyboard(self.handle, int(self.window().winId()), self._is_main_popup)

    def _is_main_popup(self, hwnd):
        popup = QApplication.activePopupWidget()
        parent = popup.parentWidget() if popup is not None else None
        return parent is not None and parent.window() is self.window() and popup.effectiveWinId() == hwnd

    def focus_renderer(self):
        container = self.container
        if (self.handle is None or container is None or not container.isVisible()
                or not container.isEnabled() or QApplication.activePopupWidget() is not None
                or not self.native_api.is_foreground_window(int(self.window().winId()))):
            return
        container.setFocus(Qt.FocusReason.OtherFocusReason)
        self.native_api.set_keyboard_focus(self.handle)

    def eventFilter(self, watched, event):
        if watched is self.container and event.type() == QEvent.Type.FocusIn:
            self.focus_renderer()
        return super().eventFilter(watched, event)

    def release(self):
        """Delete Qt wrappers synchronously while Open3D still owns a live HWND."""
        if self.container is not None:
            self.container.removeEventFilter(self)
        # The container owns the foreign QWindow when it exists. If creating
        # it failed, the foreign wrapper still needs to be released directly.
        wrapper = self.container if self.container is not None else self.foreign_window
        if wrapper is not None:
            self.native_api.hide(self.handle)
            # Let Qt destroy the container through its normal QObject path.
            # Deliver only this object's deletion event before closing Open3D.
            wrapper.deleteLater()
            QCoreApplication.sendPostedEvents(wrapper, QEvent.Type.DeferredDelete)
        self.container = None
        self.foreign_window = None
        self.handle = None
