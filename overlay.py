"""Floating voice-assistant UI. Launch with pythonw.exe for no console window."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent

from assistant import (AssistantError, Services, audio_modules, is_exit, number,
                       record, recording_options, required, transcription_language)
from personal_commands import CommandError, PersonalCommands


class TurnRunner:
    """Run blocking audio/API work off the UI thread; communicate through a queue."""
    def __init__(self, events, cancelled):
        self.events = events
        self.cancelled = cancelled
        self.services = Services()
        self.commands = PersonalCommands(ROOT)

    def emit(self, kind, value=""):
        if kind == "done" or not self.cancelled.is_set():
            self.events.put((kind, value))

    def run(self, typed=None):
        try:
            import os
            required("ELEVENLABS_API_KEY")
            if typed is None:
                self.emit("status", "Preparing microphone")
                wav = record(number(os.getenv("RECORD_SECONDS", "5")),
                             on_ready=lambda: self.emit("status", "Listening"),
                             cancel_event=self.cancelled)
                if self.cancelled.is_set():
                    return
                self.emit("status", "Transcribing")
                text = self.services.transcribe(wav)
            else:
                text = typed.strip()
            if self.cancelled.is_set():
                return
            if not text:
                raise AssistantError("No speech detected. Try again.")
            self.emit("user", text)
            if is_exit(text):
                self.emit("exit")
                return
            normalized = " ".join(text.casefold().split()).rstrip(".!?").replace("hands-free", "hands free")
            if normalized in {"stop listening", "disable hands free", "stop hands free mode"}:
                self.emit("handsfree", False)
                answer = "Hands-free listening stopped. Press Copilot when you need me."
            elif normalized in {"start hands free mode", "enable hands free", "start hands free"}:
                self.emit("handsfree", True)
                answer = "Hands-free mode is on. I will listen again after each reply. Say stop listening to end it."
            else:
                self.emit("status", "Working")
                answer = self.commands.handle(text, cancel_event=self.cancelled)
            if answer is None:
                self.emit("status", "Thinking")
                answer = self.services.reply(text)
            if self.cancelled.is_set():
                return
            self.emit("answer", answer)
            self.emit("status", "Preparing voice")
            self.services.speak(answer, on_start=lambda: self.emit("status", "Speaking"),
                                cancel_event=self.cancelled)
        except (AssistantError, CommandError) as exc:
            self.emit("error", str(exc))
        except Exception:
            # pythonw has no terminal; report a safe error without leaking inputs.
            self.emit("error", "Something went wrong. Try again, or run the checks in README.md.")
        finally:
            self.emit("done")


class Overlay:
    BG = "#10141e"
    SURFACE = "#1a2130"
    INK = "#edf3ff"
    MUTED = "#a0aec5"
    ACCENT = "#6ce5cc"

    def __init__(self, root, activation=None, listen_now=False):
        self.root = root
        self.activation = activation
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.runner = TurnRunner(self.events, self.cancelled)
        self.busy = False
        self.closed = False
        self.phase = 0
        self.next_listen = None
        self.hands_free = tk.BooleanVar(value=False)
        root.title("Voice Assistant")
        root.configure(bg=self.BG)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        width, height = 440, 560
        x = max(0, root.winfo_screenwidth() - width - 32)
        y = max(0, root.winfo_screenheight() - height - 90)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda event: self.hide())

        shell = tk.Frame(root, bg=self.BG, highlightbackground="#344158", highlightthickness=1)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(16, 4))
        title = tk.Label(header, text="VOICE ASSISTANT", font=("Segoe UI", 10, "bold"),
                         fg=self.MUTED, bg=self.BG)
        title.pack(side="left")
        self.button(header, "Close", self.close, quiet=True).pack(side="right")
        self.button(header, "Hide", self.hide, quiet=True).pack(side="right", padx=6)
        for widget in (header, title):
            widget.bind("<ButtonPress-1>", self.drag_start)
            widget.bind("<B1-Motion>", self.drag_move)

        self.orb = tk.Canvas(shell, width=396, height=68, bg=self.BG, highlightthickness=0)
        self.orb.pack(pady=(5, 0))
        self.status = tk.StringVar(value="Ready")
        tk.Label(shell, textvariable=self.status, font=("Segoe UI", 22, "bold"),
                 fg=self.INK, bg=self.BG).pack()
        self.hint = tk.StringVar(value="Press Copilot or click Listen")
        tk.Label(shell, textvariable=self.hint, font=("Segoe UI", 10), fg=self.MUTED,
                 bg=self.BG).pack(pady=(4, 14))

        content = tk.Frame(shell, bg=self.BG)
        content.pack(fill="both", expand=True, padx=20)
        tk.Label(content, text="YOU", fg=self.MUTED, bg=self.BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.user_text = tk.StringVar(value="Ask a question or give a personal command.")
        tk.Label(content, textvariable=self.user_text, fg=self.INK, bg=self.BG,
                 font=("Segoe UI", 11), wraplength=394, justify="left",
                 anchor="nw", height=2).pack(fill="x", pady=(4, 10))
        tk.Label(content, text="ASSISTANT", fg=self.MUTED, bg=self.BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.answer = tk.Text(content, height=5, wrap="word", font=("Segoe UI", 11),
                              bg=self.SURFACE, fg=self.INK, relief="flat", padx=12,
                              pady=10, cursor="arrow", state="disabled")
        self.answer.pack(fill="both", expand=True, pady=(6, 12))
        self.set_answer("Say ‘help’ for personal commands.\nVoice: ElevenLabs · AI replies: Gemini.")

        footer = tk.Frame(shell, bg=self.BG)
        footer.pack(fill="x", padx=20, pady=(0, 18))
        self.entry = tk.Entry(footer, bg=self.SURFACE, fg=self.INK, insertbackground=self.INK,
                              relief="flat", font=("Segoe UI", 11))
        self.entry.pack(fill="x", ipady=8, pady=(0, 8))
        self.entry.bind("<Return>", lambda event: self.submit())
        actions = tk.Frame(footer, bg=self.BG)
        actions.pack(fill="x")
        self.listen = self.button(actions, "Listen", self.start)
        self.listen.pack(side="left")
        self.send = self.button(actions, "Send text", self.submit, quiet=True)
        self.send.pack(side="left", padx=8)
        self.reset = self.button(actions, "Reset chat", self.reset_chat, quiet=True)
        self.reset.pack(side="right")
        mode = tk.Frame(footer, bg=self.BG)
        mode.pack(fill="x", pady=(10, 0))
        self.handsfree_toggle = tk.Checkbutton(
            mode, text="Hands-free", variable=self.hands_free, command=self.change_handsfree,
            bg=self.BG, fg=self.MUTED, activebackground=self.BG, activeforeground=self.INK,
            selectcolor=self.SURFACE, font=("Segoe UI", 10), cursor="hand2")
        self.handsfree_toggle.pack(side="left")
        self.button(mode, "Stop", self.stop_turn, quiet=True).pack(side="right")
        if activation is not None:
            activation.prepare_wait()
        root.after(80, self.poll)
        root.after(40, self.animate)
        if listen_now:
            root.after(250, self.start)

    def button(self, parent, text, action, quiet=False):
        return tk.Button(parent, text=text, command=action, relief="flat", bd=0,
                         bg=self.SURFACE if quiet else self.ACCENT,
                         fg=self.INK if quiet else self.BG, activebackground="#344158" if quiet else "#98f2de",
                         activeforeground=self.INK if quiet else self.BG,
                         disabledforeground="#68748a", cursor="hand2", padx=12, pady=6,
                         font=("Segoe UI", 10, "bold"))

    def set_answer(self, text):
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", text)
        self.answer.configure(state="disabled")

    def start(self, typed=None):
        if self.closed or self.busy:
            return
        self.busy = True
        self.cancel_pending()
        self.cancelled.clear()
        if self.activation is not None:
            self.activation.finish_wait()
        self.root.deiconify()
        self.root.lift()
        self.status.set("Starting")
        self.hint.set("Speak when the status says Listening")
        for widget in (self.listen, self.send, self.reset, self.entry):
            widget.configure(state="disabled")
        threading.Thread(target=self.runner.run, args=(typed,), daemon=True).start()

    def submit(self):
        if self.busy:
            return
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.start(text)

    def reset_chat(self):
        if not self.busy:
            self.runner.services.history.clear()
            self.user_text.set("Conversation cleared. Saved notes are unchanged.")
            self.set_answer("Ready for a fresh conversation.")

    def poll(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "exit":
                self.close()
                return
            if self.cancelled.is_set() and kind != "done":
                continue
            if kind == "status":
                self.status.set(value)
                self.hint.set("Pause briefly when you finish" if value == "Listening" else "Working on your request")
            elif kind == "user":
                self.user_text.set(value)
            elif kind == "answer":
                self.set_answer(value)
            elif kind == "error":
                self.hands_free.set(False)
                self.cancel_pending()
                self.set_answer(value)
            elif kind == "handsfree":
                self.hands_free.set(bool(value))
            elif kind == "done":
                self.busy = False
                self.status.set("Ready")
                self.hint.set("Press Copilot or click Listen")
                for widget in (self.listen, self.send, self.reset, self.entry):
                    widget.configure(state="normal")
                if self.activation is not None:
                    self.activation.prepare_wait()
                if self.hands_free.get():
                    self.hint.set("Hands-free: listening again shortly")
                    self.next_listen = self.root.after(500, self.auto_listen)
        if not self.busy and self.activation is not None and self.activation.consume():
            self.start()
        self.root.after(80, self.poll)

    def animate(self):
        if self.closed:
            return
        self.phase += 0.12
        radius = 14 + (3 * math.sin(self.phase) if self.busy else 0)
        self.orb.delete("all")
        self.orb.create_oval(198-radius-7, 34-radius-7, 198+radius+7, 34+radius+7,
                             outline="#294b51", width=2)
        self.orb.create_oval(198-radius, 34-radius, 198+radius, 34+radius,
                             fill=self.ACCENT, outline="")
        self.root.after(40, self.animate)

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        self.root.geometry(f"+{max(0, event.x_root-self.drag[0])}+{max(0, event.y_root-self.drag[1])}")

    def hide(self):
        self.stop_turn()
        self.root.withdraw()

    def cancel_pending(self):
        if self.next_listen is not None:
            self.root.after_cancel(self.next_listen)
            self.next_listen = None

    def auto_listen(self):
        self.next_listen = None
        if self.hands_free.get() and not self.closed:
            self.start()

    def change_handsfree(self):
        if self.hands_free.get():
            if not self.busy:
                self.start()
        else:
            self.cancel_pending()
            if not self.busy:
                self.hint.set("Press Copilot or click Listen")

    def stop_turn(self):
        self.hands_free.set(False)
        self.cancel_pending()
        if self.busy:
            self.cancelled.set()
            self.status.set("Stopping")
            self.hint.set("Waiting for the active operation to finish")
            try:
                audio_modules()[1].stop()  # Interrupt legacy buffered playback too.
            except Exception:
                pass


    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_pending()
        self.cancelled.set()
        if self.activation is not None:
            self.activation.finish_wait()
        self.root.destroy()


def main(argv=None, activation=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-now", action="store_true")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    root = tk.Tk()
    panel = Overlay(root, activation, args.listen_now)
    try:
        recording_options()
        transcription_language()
    except AssistantError as exc:
        panel.set_answer(str(exc))
    root.mainloop()
    return 0


if __name__ == "__main__":
    from activation import launch
    raise SystemExit(launch(main, ROOT, always_single=True))
