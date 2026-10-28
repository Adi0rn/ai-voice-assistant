import os
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from overlay import Overlay, TurnRunner
from assistant import AssistantError


class OverlayRunnerTests(unittest.TestCase):
    def setUp(self):
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.runner = TurnRunner(self.events, self.cancelled)
        self.runner.services = Mock()
        self.runner.commands = Mock()

    def collected(self):
        result = []
        while not self.events.empty():
            result.append(self.events.get_nowait())
        return result

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("overlay.record", return_value=b"wav")
    def test_voice_turn_reports_stages_and_keeps_local_commands_local(self, record):
        self.runner.services.transcribe.return_value = "what time is it"
        self.runner.commands.handle.return_value = "It is noon."
        self.runner.services.speak.side_effect = lambda text, on_start, cancel_event: on_start()
        self.runner.run()
        self.runner.services.reply.assert_not_called()
        self.runner.services.speak.assert_called_once()
        messages = self.collected()
        self.assertIn(("user", "what time is it"), messages)
        self.assertIn(("answer", "It is noon."), messages)
        self.assertIn(("status", "Speaking"), messages)
        self.assertEqual(messages[-1], ("done", ""))

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("overlay.record")
    def test_typed_question_skips_recording_and_uses_gemini(self, record):
        self.runner.commands.handle.return_value = None
        self.runner.services.reply.return_value = "Hello"
        self.runner.run("Say hello")
        record.assert_not_called()
        self.runner.services.transcribe.assert_not_called()
        self.runner.services.reply.assert_called_once_with("Say hello")

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("overlay.record", side_effect=AssistantError("No clear speech detected."))
    def test_microphone_failure_is_visible_and_finishes_turn(self, record):
        self.runner.run()
        self.runner.services.transcribe.assert_not_called()
        self.assertIn(("error", "No clear speech detected."), self.collected())

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    def test_closing_after_record_prevents_upload(self):
        def cancelled_record(*args, **kwargs):
            self.cancelled.set()
            return b"wav"
        with patch("overlay.record", side_effect=cancelled_record):
            self.runner.run()
        self.runner.services.transcribe.assert_not_called()
        self.runner.commands.handle.assert_not_called()
        self.runner.services.speak.assert_not_called()

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    def test_goodbye_closes_without_gemini_or_speech(self):
        self.runner.run("goodbye")
        self.assertIn(("exit", ""), self.collected())
        self.runner.services.reply.assert_not_called()
        self.runner.services.speak.assert_not_called()

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    def test_handsfree_voice_controls_bypass_gemini(self):
        self.runner.run("start hands-free mode")
        self.assertIn(("handsfree", True), self.collected())
        self.runner.run("stop listening")
        self.assertIn(("handsfree", False), self.collected())
        self.runner.commands.handle.assert_not_called()
        self.runner.services.reply.assert_not_called()

    def test_cancellation_still_emits_done_to_release_busy_ui(self):
        self.cancelled.set()
        self.runner.emit("error", "cancelled")
        self.runner.emit("done")
        self.assertEqual(self.collected(), [("done", "")])


@unittest.skipUnless(os.environ.get("RUN_OVERLAY_UI_TESTS") == "1", "Native Tk desktop access required")
class OverlayWidgetTests(unittest.TestCase):
    def test_hidden_ui_layout_and_busy_state(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        activation = Mock()
        activation.consume.return_value = False
        panel = Overlay(root, activation=activation)
        try:
            root.update_idletasks()
            self.assertEqual(root.winfo_width(), 440)
            self.assertEqual(root.winfo_height(), 560)
            self.assertEqual(panel.status.get(), "Ready")
            self.assertTrue(root.attributes("-topmost"))
            self.assertLessEqual(panel.listen.winfo_rooty() + panel.listen.winfo_height(), root.winfo_rooty() + 560)
            with patch("overlay.threading.Thread") as thread:
                panel.start()
                panel.start()
                thread.assert_called_once()
            self.assertEqual(str(panel.listen.cget("state")), "disabled")
            panel.events.put(("answer", "A test reply"))
            panel.events.put(("done", ""))
            panel.poll()
            self.assertFalse(panel.busy)
            self.assertEqual(str(panel.listen.cget("state")), "normal")
            self.assertIn("A test reply", panel.answer.get("1.0", "end"))
            self.assertFalse(panel.hands_free.get())
            panel.hands_free.set(True)
            panel.events.put(("done", ""))
            panel.poll()
            self.assertIsNotNone(panel.next_listen)
            panel.hands_free.set(False)
            panel.change_handsfree()
            self.assertIsNone(panel.next_listen)
            panel.hands_free.set(True)
            panel.events.put(("error", "No speech"))
            panel.events.put(("done", ""))
            panel.poll()
            self.assertFalse(panel.hands_free.get())
            self.assertIsNone(panel.next_listen)
            panel.hide()
            self.assertEqual(root.state(), "withdrawn")
        finally:
            panel.close()
