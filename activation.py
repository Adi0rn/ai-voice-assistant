"""Reuse one button-launched assistant via Windows session-local events."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
import time


class ButtonActivation:
    def __init__(self, root):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self.kernel
        for name, arguments in (
            ("CreateMutexW", [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]),
            ("CreateEventW", [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]),
            ("OpenEventW", [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]),
        ):
            function = getattr(k, name)
            function.argtypes = arguments
            function.restype = wintypes.HANDLE
        for name in ("SetEvent", "ResetEvent", "CloseHandle"):
            getattr(k, name).argtypes = [wintypes.HANDLE]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        token = hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:16]
        self.name = "Local\\VoiceAssistantButton-" + token
        self.mutex = self.trigger = self.ready = None
        self.owner = False

    def claim(self):
        self.mutex = self.kernel.CreateMutexW(None, False, self.name)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.owner = ctypes.get_last_error() != 183
        if self.owner:
            self.trigger = self.kernel.CreateEventW(None, False, False, self.name + "-trigger")
            self.ready = self.kernel.CreateEventW(None, True, False, self.name + "-ready")
            if not self.trigger or not self.ready:
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            for _ in range(40):
                self.trigger = self.kernel.OpenEventW(0x0002, False, self.name + "-trigger")
                self.ready = self.kernel.OpenEventW(0x00100000, False, self.name + "-ready")
                if self.trigger and self.ready:
                    break
                for handle in (self.trigger, self.ready):
                    if handle:
                        self.kernel.CloseHandle(handle)
                self.trigger = self.ready = None
                time.sleep(0.05)
            if not self.trigger or not self.ready:
                raise RuntimeError("The existing assistant is still starting. Try the button again.")
        return self.owner

    def signal(self):
        if self.kernel.WaitForSingleObject(self.ready, 0) != 0:
            return False  # Busy presses never queue a surprise recording.
        if not self.kernel.SetEvent(self.trigger):
            raise ctypes.WinError(ctypes.get_last_error())
        return True

    def prepare_wait(self):
        self.kernel.ResetEvent(self.trigger)
        self.kernel.SetEvent(self.ready)

    def finish_wait(self):
        self.kernel.ResetEvent(self.ready)
        self.kernel.ResetEvent(self.trigger)

    def consume(self):
        return self.kernel.WaitForSingleObject(self.trigger, 0) == 0

    def wait_for_command(self):
        import msvcrt
        prompt = "Press Copilot or Enter to record (q to quit): "
        if not sys.stdin.isatty():
            return input(prompt).strip()
        print(prompt, end="", flush=True)
        typed = []
        self.prepare_wait()
        try:
            while True:
                if self.consume():
                    print()
                    self.focus_console()
                    return ""
                if msvcrt.kbhit():
                    character = msvcrt.getwch()
                    if character == "\x03":
                        raise KeyboardInterrupt
                    if character in {"\x00", "\xe0"}:
                        msvcrt.getwch()  # Ignore cursor/function key suffix.
                    elif character == "\r":
                        print()
                        return "".join(typed).strip()
                    elif character == "\b":
                        if typed:
                            typed.pop()
                            print("\b \b", end="", flush=True)
                    elif character.isprintable():
                        typed.append(character)
                        print(character, end="", flush=True)
                else:
                    time.sleep(0.05)
        finally:
            self.finish_wait()

    def focus_console(self):
        # Windows Terminal may not expose a focusable console window; recording
        # still works when Windows does not permit changing foreground focus.
        self.kernel.GetConsoleWindow.restype = wintypes.HWND
        window = self.kernel.GetConsoleWindow()
        if window:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.SetForegroundWindow.argtypes = [wintypes.HWND]
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)

    def close(self):
        for handle in (self.ready, self.trigger, self.mutex):
            if handle:
                self.kernel.CloseHandle(handle)
        self.ready = self.trigger = self.mutex = None


def launch(main, root, argv=None, always_single=False):
    arguments = sys.argv[1:] if argv is None else argv
    if os.name != "nt" or (not always_single and arguments != ["--listen-now"]):
        return main(arguments)
    instance = ButtonActivation(root)
    try:
        if not instance.claim():
            print("Recording in the existing assistant." if instance.signal()
                  else "The assistant is already recording or responding; try again when it is ready.")
            return 0
        return main(arguments, activation=instance)
    except (OSError, RuntimeError) as exc:
        print("Could not activate assistant:", exc, file=sys.stderr)
        return 1
    finally:
        instance.close()
