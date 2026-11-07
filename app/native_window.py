"""Checked, pointer-sized Win32 calls used for Open3D native windows."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
from threading import get_native_id
import traceback


GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
FRAME_EX_STYLES = 0x00000001 | 0x00000100 | 0x00000200 | 0x00020000
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GA_ROOT = 2
WH_GETMESSAGE = 3
HC_ACTION = 0
PM_REMOVE = 1
WM_NULL = 0x0000
WM_KEYFIRST = 0x0100
WM_KEYLAST = 0x0109
VK_ESCAPE = 0x1B


@dataclass(frozen=True)
class NativeHandle:
    hwnd: int
    title: str
    pid: int


class NativeWindowApi:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Open3D native embedding requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._enum_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, ctypes.c_ssize_t
        )
        self._monitor_enum_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), ctypes.c_ssize_t
        )
        self._message_hook_proc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        )
        self._bind("EnumThreadWindows", [wintypes.DWORD, self._enum_proc, ctypes.c_ssize_t], wintypes.BOOL)
        self._bind("EnumDisplayMonitors",
                   [wintypes.HDC, ctypes.POINTER(wintypes.RECT), self._monitor_enum_proc, ctypes.c_ssize_t],
                   wintypes.BOOL)
        self._bind("IsWindow", [wintypes.HWND], wintypes.BOOL)
        self._bind("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int)
        self._bind("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
        self._bind("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)
        suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
        self._get_long = self._bind("GetWindowLong" + suffix, [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t)
        self._set_long = self._bind("SetWindowLong" + suffix, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t)
        self._bind("GetParent", [wintypes.HWND], wintypes.HWND)
        self._bind("GetAncestor", [wintypes.HWND, wintypes.UINT], wintypes.HWND)
        self._bind("SetWindowsHookExW",
                   [ctypes.c_int, self._message_hook_proc, wintypes.HINSTANCE, wintypes.DWORD],
                   wintypes.HANDLE)
        self._bind("CallNextHookEx",
                   [wintypes.HANDLE, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t],
                   ctypes.c_ssize_t)
        self._bind("UnhookWindowsHookEx", [wintypes.HANDLE], wintypes.BOOL)
        self._bind("GetForegroundWindow", [], wintypes.HWND)
        self._bind("GetFocus", [], wintypes.HWND)
        self._bind("SetFocus", [wintypes.HWND], wintypes.HWND)
        self._bind("SetWindowPos", [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL)
        self._bind("ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
        self._bind("LoadImageW", [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.HANDLE)
        self._bind("SendMessageW", [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t)
        self._bind("DestroyIcon", [wintypes.HICON], wintypes.BOOL)
        self._icon = None
        self._keyboard_hook = None
        self._keyboard_callback = None
        self._keyboard_target = None

    def _bind(self, name, args, result):
        function = getattr(self.user32, name)
        function.argtypes = args
        function.restype = result
        return function

    def _belongs_to_gui_thread(self, hwnd):
        pid = wintypes.DWORD()
        thread_id = self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return thread_id == get_native_id() and pid.value == os.getpid()

    def _title(self, hwnd):
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def find_window(self, title):
        matches = []
        errors = []

        @self._enum_proc
        def visit(hwnd, _):
            # ctypes callbacks cannot propagate Python exceptions to the caller.
            try:
                if self._belongs_to_gui_thread(hwnd) and self._title(hwnd) == title:
                    matches.append(int(hwnd))
            except OSError as error:
                errors.append(error)
                return False
            return True

        # GetWindowText sends synchronous messages to windows in this process.
        # Filament owns a hidden window on its render thread, which may not pump
        # those messages. Only enumerate windows created on this GUI thread.
        self.user32.EnumThreadWindows(get_native_id(), visit, 0)
        if errors:
            raise errors[0]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one Open3D window on the GUI thread: {title!r}; found {len(matches)}")
        handle = NativeHandle(matches[0], title, os.getpid())
        self.validate(handle)
        return handle

    def validate(self, handle):
        if (not self.user32.IsWindow(handle.hwnd)
                or handle.pid != os.getpid()
                or not self._belongs_to_gui_thread(handle.hwnd)
                or self._title(handle.hwnd) != handle.title):
            raise RuntimeError("Open3D native window handle is no longer valid")

    def offscreen_origin(self):
        edges = []

        @self._monitor_enum_proc
        def visit(_monitor, _dc, bounds, _data):
            edges.append((bounds.contents.right, bounds.contents.bottom))
            return True

        if not self.user32.EnumDisplayMonitors(None, None, visit, 0) or not edges:
            raise RuntimeError("Could not determine the Windows monitor bounds")
        right = max(edge[0] for edge in edges)
        bottom = max(edge[1] for edge in edges)
        # Leave room for the native frame around Open3D's client-area origin.
        return right + 64, bottom + 64

    def _get(self, hwnd, index):
        ctypes.set_last_error(0)
        value = self._get_long(hwnd, index)
        error = ctypes.get_last_error()
        if not value and error:
            raise ctypes.WinError(error)
        return value

    def _set(self, hwnd, index, value):
        ctypes.set_last_error(0)
        previous = self._set_long(hwnd, index, value)
        error = ctypes.get_last_error()
        if not previous and error:
            raise ctypes.WinError(error)

    def _refresh_frame(self, hwnd):
        if not self.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED):
            raise ctypes.WinError(ctypes.get_last_error())

    def remove_frame(self, handle):
        self.validate(handle)
        style = self._get(handle.hwnd, GWL_STYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_POPUP)
        self._set(handle.hwnd, GWL_STYLE, style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
        ex_style = self._get(handle.hwnd, GWL_EXSTYLE)
        self._set(handle.hwnd, GWL_EXSTYLE, ex_style & ~(WS_EX_APPWINDOW | WS_EX_TOOLWINDOW | FRAME_EX_STYLES))
        self._refresh_frame(handle.hwnd)

    def verify_child(self, handle, parent_hwnd):
        self.validate(handle)
        if (not self._get(handle.hwnd, GWL_STYLE) & WS_CHILD
                or self.user32.GetParent(handle.hwnd) != parent_hwnd):
            raise RuntimeError("Open3D was not embedded as a Qt native child window")

    def hide(self, handle):
        self.validate(handle)
        self.user32.ShowWindow(handle.hwnd, 0)

    def is_foreground_window(self, hwnd):
        return self.user32.GetForegroundWindow() == hwnd

    def route_keyboard(self, handle, main_hwnd, is_main_popup):
        if self._keyboard_hook is not None:
            raise RuntimeError("Open3D keyboard routing is already installed")
        self.validate(handle)

        @self._message_hook_proc
        def route(code, flags, address):
            result = self.user32.CallNextHookEx(None, code, flags, address)
            target = self._keyboard_target
            if code == HC_ACTION and flags == PM_REMOVE and target is not None:
                try:
                    message = ctypes.cast(address, ctypes.POINTER(wintypes.MSG)).contents
                    if WM_KEYFIRST <= message.message <= WM_KEYLAST and message.hWnd:
                        root = self.user32.GetAncestor(message.hWnd, GA_ROOT)
                        if root == main_hwnd or (root and is_main_popup(root)):
                            if message.wParam == VK_ESCAPE:
                                # Open3D closes the window before its Python key handler runs.
                                message.message = WM_NULL
                            elif (message.hWnd != target
                                  and self.user32.GetAncestor(target, GA_ROOT) == main_hwnd):
                                # Keep the original message's scan code, repeat and modifier flags.
                                message.hWnd = target
                except Exception:
                    traceback.print_exc()
            return result

        # Both Qt and GLFW pump this GUI thread's message queue.
        hook = self.user32.SetWindowsHookExW(WH_GETMESSAGE, route, None, get_native_id())
        if not hook:
            raise ctypes.WinError(ctypes.get_last_error())
        self._keyboard_hook = hook
        self._keyboard_callback = route
        self._keyboard_target = handle.hwnd

    def stop_keyboard_routing(self):
        self._keyboard_target = None
        if self._keyboard_hook is not None:
            if not self.user32.UnhookWindowsHookEx(self._keyboard_hook):
                raise ctypes.WinError(ctypes.get_last_error())
            self._keyboard_hook = None
            self._keyboard_callback = None

    def set_keyboard_focus(self, handle):
        self.validate(handle)
        if self.user32.GetFocus() == handle.hwnd:
            return
        ctypes.set_last_error(0)
        previous = self.user32.SetFocus(handle.hwnd)
        error = ctypes.get_last_error()
        # A null previous focus is also valid when no window had focus.
        if not previous and error:
            raise ctypes.WinError(error)

    def set_tool_owner(self, handle, owner_hwnd):
        self.validate(handle)
        if not self._belongs_to_gui_thread(owner_hwnd):
            raise RuntimeError("Invalid Qt owner window")
        self._set(handle.hwnd, GWLP_HWNDPARENT, owner_hwnd)
        self._set(handle.hwnd, GWL_EXSTYLE,
                  (self._get(handle.hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        self._set(handle.hwnd, GWL_STYLE, self._get(handle.hwnd, GWL_STYLE) & ~WS_SYSMENU)
        self._refresh_frame(handle.hwnd)

    def set_icon(self, handle, path):
        self.validate(handle)
        if self._icon is None:
            self._icon = self.user32.LoadImageW(None, str(path), 1, 0, 0, 0x0010)
            if not self._icon:
                raise ctypes.WinError(ctypes.get_last_error())
        self.user32.SendMessageW(handle.hwnd, 0x0080, 0, self._icon)
        self.user32.SendMessageW(handle.hwnd, 0x0080, 1, self._icon)

    def close(self):
        if self._icon:
            self.user32.DestroyIcon(self._icon)
            self._icon = None
