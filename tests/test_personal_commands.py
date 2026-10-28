import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import assistant
from personal_commands import CommandError, PersonalCommands


class PersonalCommandTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(__file__).resolve().parents[1] / "work"
        self.work.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.work)
        self.root = Path(self.temporary.name)
        self.root.joinpath("shortcuts.json").write_text(
            json.dumps({"websites": {"study": "https://example.com/study"}}), encoding="utf-8")
        self.commands = PersonalCommands(self.root)

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(self.work.resolve()))
        self.temporary.cleanup()

    def test_notes_survive_a_new_session_and_preserve_text(self):
        note = "Buy milk, don't forget bread!"
        self.commands.handle("Take a note: " + note)
        another = PersonalCommands(self.root)
        self.assertIn(note, another.handle("Read my notes!"))
        self.assertEqual(another.handle("count my notes"), "You have 1 saved note.")

    def test_empty_notes_do_not_create_a_database(self):
        self.assertIn("no saved notes", self.commands.handle("read my notes"))
        self.assertFalse((self.root / "data").exists())

    def test_read_notes_is_bounded_and_newest_first(self):
        for note in ("one", "two", "three", "four"):
            self.commands.handle("note " + note)
        result = self.commands.handle("show my notes")
        self.assertNotIn("one", result)
        self.assertIn("1. four", result)
        self.assertIn("3. two", result)

    def test_note_search_returns_matches_without_treating_sql_as_code(self):
        self.commands.handle("note Exam on Monday")
        self.commands.handle("note Buy milk")
        result = self.commands.handle("find notes about exam")
        self.assertIn("Exam on Monday", result)
        self.assertNotIn("Buy milk", result)
        self.assertEqual(self.commands.handle("search my notes for ' OR 1=1 --"), "No matching notes found.")

    def test_note_search_treats_wildcards_literally(self):
        self.commands.handle("note Progress is 90%")
        self.commands.handle("note Plain text")
        result = self.commands.handle("find notes about %")
        self.assertIn("Progress is 90%", result)
        self.assertNotIn("Plain text", result)

    @patch("personal_commands.webbrowser.open", return_value=True)
    def test_study_routine_opens_only_configured_targets(self, browser):
        self.root.joinpath("shortcuts.json").write_text(json.dumps({
            "websites": {"study": "https://example.com/study"}, "routines": {"study": ["study"]}
        }), encoding="utf-8")
        self.assertEqual(self.commands.handle("start study mode"), "Started study: opened study.")
        browser.assert_called_once_with("https://example.com/study", new=2)

    @patch("personal_commands.webbrowser.open")
    @patch("personal_commands.subprocess.Popen")
    def test_routine_validates_every_target_before_any_action(self, process, browser):
        self.root.joinpath("shortcuts.json").write_text(json.dumps({
            "websites": {"study": "https://example.com/study"}, "routines": {"study": ["study", "powershell"]}
        }), encoding="utf-8")
        with self.assertRaises(CommandError):
            self.commands.handle("start study mode")
        browser.assert_not_called()
        process.assert_not_called()

    @patch("personal_commands.webbrowser.open", side_effect=[True, False])
    def test_routine_reports_partial_failure_and_stops(self, browser):
        self.root.joinpath("shortcuts.json").write_text(json.dumps({
            "websites": {"one": "https://example.com/one", "two": "https://example.com/two"},
            "routines": {"study": ["one", "two", "one"]}
        }), encoding="utf-8")
        with self.assertRaisesRegex(CommandError, "Opened one, but could not open two"):
            self.commands.handle("start study mode")
        self.assertEqual(browser.call_count, 2)

    def test_empty_and_oversized_notes_are_not_saved(self):
        self.assertIn("followed by", self.commands.handle("take a note"))
        with self.assertRaises(CommandError):
            self.commands.handle("note " + "x" * 2001)
        self.assertFalse((self.root / "data").exists())

    @patch("personal_commands.webbrowser.open", return_value=True)
    def test_custom_website_and_encoded_search(self, browser):
        self.assertEqual(self.commands.handle("Open study."), "Opened study.")
        browser.assert_called_with("https://example.com/study", new=2)
        self.commands.handle("search the web for Python & Windows")
        self.assertEqual(browser.call_args.args[0], "https://www.google.com/search?q=Python+%26+Windows")

    @patch("personal_commands.webbrowser.open", return_value=False)
    def test_failed_browser_open_does_not_claim_success(self, browser):
        with self.assertRaises(CommandError):
            self.commands.handle("open study")

    @patch("personal_commands.subprocess.Popen")
    def test_fixed_app_launch_uses_no_shell(self, launch):
        self.assertEqual(self.commands.handle("open calculator"), "Opened calculator.")
        self.assertEqual(Path(launch.call_args.args[0][0]).name, "calc.exe")
        self.assertFalse(launch.call_args.kwargs["shell"])
        launch.reset_mock()
        self.assertIn("I can open", self.commands.handle("open cmd /c anything"))
        launch.assert_not_called()

    @patch("personal_commands.subprocess.Popen")
    def test_custom_executable_is_launched_as_a_single_literal_path(self, launch):
        executable = self.root / "My Editor.exe"
        executable.write_bytes(b"test fixture, never executed")
        self.root.joinpath("shortcuts.json").write_text(json.dumps({
            "websites": {}, "apps": {"my editor": str(executable)}
        }), encoding="utf-8")
        self.assertEqual(self.commands.handle("open my editor"), "Opened my editor.")
        launch.assert_called_once_with([str(executable)], shell=False)

    @patch("personal_commands.subprocess.Popen")
    def test_custom_apps_reject_relative_paths_and_command_lines(self, launch):
        for value in ("editor.exe", "powershell -Command anything", str(self.root / "missing.exe")):
            self.root.joinpath("shortcuts.json").write_text(json.dumps({
                "websites": {}, "apps": {"editor": value}
            }), encoding="utf-8")
            with self.assertRaises(CommandError):
                self.commands.handle("open editor")
        launch.assert_not_called()

    @patch("personal_commands.webbrowser.open")
    def test_bad_shortcuts_cannot_launch_executables_or_script_urls(self, browser):
        for value in ("javascript:alert(1)", "file:///C:/Windows/System32/cmd.exe", "https://user:password@example.com"):
            self.root.joinpath("shortcuts.json").write_text(
                json.dumps({"websites": {"study": value}}), encoding="utf-8")
            with self.assertRaises(CommandError):
                self.commands.handle("open study")
        browser.assert_not_called()

    def test_corrupt_notes_produce_a_safe_error(self):
        directory = self.root / "data"
        directory.mkdir()
        (directory / "notes.sqlite3").write_bytes(b"not a database")
        with self.assertRaises(CommandError):
            self.commands.handle("read my notes")

    @patch("assistant.Services")
    @patch("requests.post")
    @patch.dict("os.environ", {}, clear=True)
    def test_local_cli_and_text_mode_bypass_gemini(self, post, services):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(assistant.main(["--command", "help"]), 0)
            self.assertEqual(assistant.main(["--text", "what time is it"]), 0)
        self.assertIn("The time is", output.getvalue())
        services.return_value.reply.assert_not_called()
        post.assert_not_called()

    @patch("assistant.Services")
    def test_ordinary_question_still_uses_gemini(self, services):
        services.return_value.reply.return_value = "A useful study tip."
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(assistant.main(["--text", "Give me one study tip"]), 0)
        services.return_value.reply.assert_called_once_with("Give me one study tip")

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("builtins.input", return_value="q")
    @patch("assistant.play")
    @patch("assistant.record", return_value=b"wav")
    @patch("assistant.Services")
    def test_spoken_local_command_bypasses_gemini_and_speaks_answer(self, services, record, play, prompt):
        services.return_value.transcribe.return_value = "What time is it?"
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(assistant.main(["--listen-now"]), 0)
        services.return_value.reply.assert_not_called()
        self.assertIn("The time is", services.return_value.speak.call_args.args[0])
        services.return_value.speak.assert_called_once()


if __name__ == "__main__":
    unittest.main()
