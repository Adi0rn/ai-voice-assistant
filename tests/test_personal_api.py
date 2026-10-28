"""No microphone, cloud calls, real Spotify actions, or personal data."""

import unittest
from unittest.mock import patch
from pathlib import Path
import requests

from personal_api_client import PersonalAPIError, handle_api_command
from personal_commands import CommandError, PersonalCommands


class PersonalAPITests(unittest.TestCase):
    def setUp(self):
        device = patch("personal_api_client.desktop_device", return_value="desktop-device")
        device.start()
        self.addCleanup(device.stop)

    @patch.dict("os.environ", {"PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("requests.Session")
    @patch("personal_commands.subprocess.Popen")
    @patch("personal_commands.webbrowser.open")
    def test_song_request_bypasses_generic_app_opening(self, browser, process, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled": True, "reply": "Requested Kiss of Life by Sade on Spotify."}
        for phrase in ("Open Spotify and play Kiss of Life by Sade", "Play Kiss of Life by Sade on Spotify.", "Play the song Kiss of Life by Sade"):
            self.assertEqual(PersonalCommands(Path.cwd()).handle(phrase), "Requested Kiss of Life by Sade on Spotify.")
            self.assertEqual(session.post.call_args.kwargs["json"], {"text": "play Kiss of Life by Sade", "device_id": "desktop-device"})
        browser.assert_not_called()
        process.assert_not_called()

    @patch("requests.Session")
    def test_song_not_supported_is_reported_without_false_playback_claim(self, factory):
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {"handled": False}
        with self.assertRaisesRegex(CommandError, "individual-song playback"):
            PersonalCommands(Path.cwd()).handle("Open Spotify and play Kiss of Life by Sade")

    @patch("requests.Session")
    def test_compound_playlist_request_keeps_existing_api_support(self, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled": True, "reply": "Playing your playlist."}
        self.assertEqual(handle_api_command("Open Spotify and play my playlist Heart and soul"), "Playing your playlist.")
        self.assertEqual(session.post.call_args.kwargs["json"], {"text": "play my playlist Heart and soul", "device_id": "desktop-device"})

    @patch("requests.Session")
    def test_native_device_receives_one_playback_command(self, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled": True, "reply": "Sent the resume command to Spotify."}
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"ready": True, "device_id": "desktop-device", "autoplay_blocked": True}
        reply = handle_api_command("play music")
        self.assertNotIn("Play here", reply)
        session.get.assert_not_called()
        self.assertEqual(session.post.call_count, 1)
        self.assertTrue(session.post.call_args.args[0].endswith("/assistant/command"))
        self.assertEqual(session.post.call_args.kwargs["json"]["device_id"], "desktop-device")

    @patch.dict("os.environ", {"PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("requests.Session")
    def test_daily_briefing_routes_through_command_handler(self, factory):
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {"handled": True, "reply": "Your daily briefing."}
        for phrase in ("Give me my daily briefing!", "What’s my day looking like?"):
            self.assertEqual(PersonalCommands(Path.cwd()).handle(phrase), "Your daily briefing.")
            self.assertEqual(factory.return_value.__enter__.return_value.post.call_args.kwargs["timeout"], (2, 75))

    @patch("requests.Session")
    def test_unknown_questions_do_not_call_the_api(self, factory):
        self.assertIsNone(handle_api_command("Explain gravity"))
        self.assertIsNone(handle_api_command("take a note buy milk"))
        factory.assert_not_called()

    @patch.dict("os.environ", {"PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("requests.Session")
    def test_recognized_command_is_sent_without_redirects(self, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled": True, "reply": "You have two tasks."}
        self.assertEqual(PersonalCommands(Path.cwd()).handle("Show my tasks!"), "You have two tasks.")
        self.assertFalse(session.trust_env)
        self.assertEqual(session.post.call_args.args[0], "http://127.0.0.1:8000/assistant/command")
        self.assertEqual(session.post.call_args.kwargs["json"], {"text": "Show my tasks!"})
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])

    @patch.dict("os.environ", {"PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("requests.Session")
    def test_connection_failure_is_a_safe_command_error(self, factory):
        factory.return_value.__enter__.return_value.post.side_effect = requests.ConnectionError()
        with self.assertRaisesRegex(CommandError, "Start its server"):
            PersonalCommands(Path.cwd()).handle("pause my music")

    @patch("requests.Session")
    def test_remote_and_credential_bearing_endpoints_are_rejected(self, factory):
        for value in ("https://example.com", "http://127.0.0.1:8000@evil.example:80", "http://127.0.0.1:8000/path", "http://user:password@127.0.0.1:8000"):
            with self.subTest(value=value), patch.dict("os.environ", {"PERSONAL_API_URL": value}):
                with self.assertRaises(PersonalAPIError):
                    handle_api_command("show my tasks")
        factory.assert_not_called()

    @patch.dict("os.environ", {"PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("personal_api_client.webbrowser.open", return_value=True)
    def test_dashboard_launches_the_local_page(self, browser):
        self.assertIn("Opened", handle_api_command("Open dashboard."))
        browser.assert_called_once_with("http://127.0.0.1:8000/dashboard", new=2)

    @patch("requests.Session")
    def test_api_error_does_not_fall_back_to_an_llm(self, factory):
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 403
        response.json.return_value = {"detail": "Approve Spotify playback permissions."}
        with self.assertRaisesRegex(CommandError, "Approve Spotify"):
            PersonalCommands(Path.cwd()).handle("pause my music")

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "fake-test-key", "PERSONAL_API_URL": "http://127.0.0.1:8000"})
    @patch("requests.Session")
    @patch("overlay.record", return_value=b"fake-wav")
    @patch("overlay.Services")
    def test_spoken_api_command_is_spoken_without_gemini(self, services, record, factory):
        import queue
        import threading
        from overlay import TurnRunner
        services.return_value.transcribe.return_value = "show my tasks"
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {"handled": True, "reply": "You have two tasks."}
        events = queue.Queue()
        runner = TurnRunner(events, threading.Event())
        runner.run()
        services.return_value.reply.assert_not_called()
        self.assertEqual(services.return_value.speak.call_args.args[0], "You have two tasks.")
        self.assertTrue(any(kind == "answer" and value == "You have two tasks." for kind, value in list(events.queue)))

    @patch("requests.Session")
    def test_failed_song_command_is_reported_without_repeating_it(self, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 409
        session.post.return_value.json.return_value = {"detail":"No available Spotify device."}
        with self.assertRaisesRegex(PersonalAPIError, "No available Spotify device"):
            handle_api_command("Open Spotify and play Kiss of Life by Sade")
        self.assertEqual(session.post.call_count, 1)
        self.assertTrue(session.post.call_args.args[0].endswith("/assistant/command"))

    @patch("requests.Session")
    def test_quoted_transcription_is_handled_before_model_fallback(self, factory):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled":True,"reply":"Requested Like a Tattoo by Sade on Spotify."}
        for phrase in ['"Play Like a Tattoo" by Sade.', '“Play Like a Tattoo” by Sade.', 'Play "Like a Tattoo" by "Sade".', '"Play Like a Tattoo by Sade".', 'Please play Like a Tattoo by Sade.']:
            with self.subTest(phrase=phrase):
                reply = PersonalCommands(Path.cwd()).handle(phrase)
                self.assertIn("Requested Like a Tattoo",reply)
                self.assertEqual(session.post.call_args.kwargs["json"]["text"],"play Like a Tattoo by Sade")

    @patch("personal_api_client._launch_spotify")
    @patch("requests.Session")
    def test_resolved_song_opens_its_exact_native_uri(self, factory, launch):
        session = factory.return_value.__enter__.return_value
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"handled":True,"action":"song_requested","track_uri":"spotify:track:"+"a"*22,"reply":"Requested Like a Tattoo by Sade on Spotify."}
        handle_api_command("play Like a Tattoo by Sade")
        launch.assert_called_once_with("spotify:track:"+"a"*22)
        self.assertEqual(session.post.call_count,1)
