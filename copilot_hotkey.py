"""Local Copilot-button launcher. No key logging, API calls, or startup changes."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
TOKEN = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:16]
EVENT_NAME = "Local\\VoiceAssistantStop-" + TOKEN
MUTEX_NAME = "Local\\VoiceAssistantListener-" + TOKEN
STATUS = ROOT / "work" / "copilot-status.json"
WM_LAUNCH = 0x8001


class CopilotGesture:
    """Track modifier state and consume only the Copilot F23 gesture."""
    def __init__(self):
        self.modifiers = set()
        self.held = False

    def update(self, key, down):
        if key in (0x5B, 0x5C, 0xA0, 0xA1):  # Left/right Windows and Shift.
            if down:
                self.modifiers.add(key)
            else:
                self.modifiers.discard(key)
        if key != 0x86:  # F23, emitted by the physical Copilot button.
            return False, False
        if not down:
            consumed = self.held
            self.held = False
            return consumed, False
        if self.held:
            return True, False
        if self.modifiers.intersection((0x5B, 0x5C)) and self.modifiers.intersection((0xA0, 0xA1)):
            self.held = True
            return True, True
        return False, False


def windows_api():
    if os.name != "nt":
        raise RuntimeError("The Copilot listener requires Windows.")
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = handle
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = handle
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = handle
    kernel.SetEvent.argtypes = [handle]
    kernel.CloseHandle.argtypes = [handle]
    kernel.WaitForSingleObject.argtypes = [handle, wintypes.DWORD]
    kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel.GetModuleHandleW.restype = handle
    user.CallNextHookEx.argtypes = [handle, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user.CallNextHookEx.restype = ctypes.c_ssize_t
    user.UnhookWindowsHookEx.argtypes = [handle]
    user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user.SetTimer.restype = ctypes.c_size_t
    user.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    return user, kernel


def control(stop=False):
    _, kernel = windows_api()
    event = kernel.OpenEventW(0x0002 if stop else 0x00100000, False, EVENT_NAME)
    if not event:
        print("Copilot binding is not running.")
        return 1
    try:
        if stop:
            kernel.SetEvent(event)
            print("Stopping Copilot binding; the assistant window can be closed separately.")
        else:
            print("Copilot binding is running.")
    finally:
        kernel.CloseHandle(event)
    return 0


def write_status(state):
    STATUS.parent.mkdir(exist_ok=True)
    STATUS.write_text(json.dumps({"state": state, "pid": os.getpid()}), encoding="utf-8")


def run(check_only=False):
    user, kernel = windows_api()
    mutex = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        print("Copilot binding is already running.")
        return 0
    hook = timer = event = None
    try:
        class Keyboard(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        user.SetWindowsHookExW.restype = wintypes.HANDLE
        gesture = CopilotGesture()
        thread_id = kernel.GetCurrentThreadId()

        @callback_type
        def callback(code, message, pointer):
            if code == 0 and message in (0x100, 0x101, 0x104, 0x105):
                key = ctypes.cast(pointer, ctypes.POINTER(Keyboard)).contents
                consumed, launch = gesture.update(key.vkCode, message in (0x100, 0x104))
                if launch:
                    user.PostThreadMessageW(thread_id, WM_LAUNCH, 0, 0)
                if consumed:
                    return 1
            return user.CallNextHookEx(None, code, message, pointer)

        # Allocate the message queue before installing the hook. Launch work happens
        # in the message loop so the keyboard callback always returns immediately.
        timer = user.SetTimer(None, 0, 200, None)
        if not timer:
            raise ctypes.WinError(ctypes.get_last_error())
        hook = user.SetWindowsHookExW(13, callback, kernel.GetModuleHandleW(None), 0)
        if not hook:
            raise ctypes.WinError(ctypes.get_last_error())
        if check_only:
            print("Windows keyboard hook installed and removed successfully.")
            return 0
        event = kernel.CreateEventW(None, True, False, EVENT_NAME)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        write_status("ready")
        assistant = None
        message = wintypes.MSG()
        while True:
            result = user.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            if result == 0 or kernel.WaitForSingleObject(event, 0) == 0:
                break
            if message.message == WM_LAUNCH:
                if assistant is None or assistant.poll() is not None:
                    try:
                        assistant = subprocess.Popen(
                            [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-B", str(ROOT / "assistant.py")],
                            cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                        )
                        write_status("ready")
                    except OSError:
                        write_status("launch failed; check the local Python environment")
        write_status("stopped")
        return 0
    finally:
        if hook:
            user.UnhookWindowsHookEx(hook)
        if timer:
            user.KillTimer(None, timer)
        if event:
            kernel.CloseHandle(event)
        kernel.CloseHandle(mutex)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Briefly install/remove hook, without launching anything")
    mode.add_argument("--stop", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        return control(args.stop) if args.stop or args.status else run(args.check)
    except (OSError, RuntimeError) as exc:
        write_status("listener error: " + str(exc))
        if sys.stderr:
            print("Could not enable Copilot binding:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
