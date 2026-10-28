"""Offline regression tests: fake APIs only, no microphone and no real keys."""
import io
import unittest
from unittest.mock import patch
import requests
import assistant as app


class Response:
    status_code = 200
    headers = {}
    content = b"\x00\x01"
    def __init__(self, body=None):
        self.body = body or {}
    def json(self):
        return self.body


class AssistantTests(unittest.TestCase):
    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret", "GEMINI_API_KEY": "test-secret"}, clear=True)
    @patch("builtins.input", return_value="q")
    @patch("assistant.play")
    @patch("assistant.record", return_value=b"wav")
    @patch("assistant.Services")
    def test_button_launch_records_before_first_prompt(self, services, record, play, prompt):
        services.return_value.transcribe.return_value = "Hello"
        services.return_value.reply.return_value = "Hi"
        self.assertEqual(app.main(["--listen-now"]), 0)
        record.assert_called_once_with(5)
        services.return_value.transcribe.assert_called_once_with(b"wav")
        services.return_value.speak.assert_called_once_with("Hi")
        prompt.assert_called_once()

    def test_reject_invalid_duration(self):
        for value in ("nan", "inf", "0", "31", "abc"):
            with self.subTest(value=value), self.assertRaises(app.AssistantError):
                app.number(value)

    def test_exact_exit_command(self):
        self.assertTrue(app.is_exit("Goodbye!"))
        self.assertFalse(app.is_exit("Please stop the music"))

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_transcript_uses_wav_multipart(self, post):
        post.return_value = Response({"text": " Hello "})
        self.assertEqual(app.Services().transcribe(b"wav"), "Hello")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["files"]["file"], ("microphone.wav", b"wav", "audio/wav"))
        self.assertEqual(kwargs["data"]["language_code"], "en")
        self.assertFalse(kwargs["allow_redirects"])

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_history_is_bounded_and_failed_turn_not_added(self, post):
        post.return_value = Response({"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})
        services = app.Services()
        for _ in range(15):
            self.assertEqual(services.reply("hello"), "Hi")
        self.assertEqual(len(services.history), 20)
        previous = list(services.history)
        post.return_value = Response({"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaises(app.AssistantError):
            services.reply("blocked")
        self.assertEqual(services.history, previous)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_current_model_uses_compatible_settings(self, post):
        post.return_value = Response({"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]})
        self.assertEqual(app.Services().reply("hello"), "Hello")
        self.assertIn("gemini-3.5-flash:generateContent", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})
        instruction = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("English by default", instruction)

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "eleven-test", "GEMINI_API_KEY": "gemini-test"}, clear=True)
    @patch("requests.Session.post")
    def test_persistent_connection_client_keeps_provider_keys_separate(self, post):
        services = app.Services()
        post.side_effect = [Response({"text": "Hello"}), Response({"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})]
        client = services.http
        services.transcribe(b"wav")
        services.reply("Hello")
        self.assertIs(services.http, client)
        first, second = post.call_args_list
        self.assertEqual(first.kwargs["headers"], {"xi-api-key": "eleven-test"})
        self.assertEqual(second.kwargs["headers"], {"x-goog-api-key": "gemini-test"})
        self.assertNotIn("xi-api-key", client.headers)
        self.assertNotIn("x-goog-api-key", client.headers)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test", "GEMINI_THINKING_LEVEL": "default"}, clear=True)
    @patch("requests.Session.post")
    def test_provider_default_thinking_can_be_restored(self, post):
        post.return_value = Response({"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})
        app.Services().reply("Hello")
        self.assertNotIn("thinkingConfig", post.call_args.kwargs["json"]["generationConfig"])

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test", "GEMINI_THINKING_LEVEL": "invalid"}, clear=True)
    @patch("requests.Session.post")
    def test_invalid_thinking_setting_does_not_make_a_request(self, post):
        with self.assertRaises(app.AssistantError):
            app.Services().reply("Hello")
        post.assert_not_called()

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret", "STT_LANGUAGE": "auto"}, clear=True)
    @patch("requests.Session.post")
    def test_automatic_language_detection_requires_explicit_setting(self, post):
        post.return_value = Response({"text": "Hello"})
        app.Services().transcribe(b"wav")
        self.assertNotIn("language_code", post.call_args.kwargs["data"])

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret", "STT_LANGUAGE": "English"}, clear=True)
    @patch("requests.Session.post")
    def test_invalid_language_setting_stops_before_upload(self, post):
        with self.assertRaises(app.AssistantError):
            app.Services().transcribe(b"wav")
        post.assert_not_called()

    @patch("requests.post")
    def test_error_does_not_echo_provider_body(self, post):
        response = Response({"error": "test-secret"})
        response.status_code = 401
        post.return_value = response
        with self.assertRaises(app.AssistantError) as caught:
            app.request("Test", "https://example.invalid")
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertIn("401", str(caught.exception))

    @patch("requests.post", side_effect=requests.Timeout("secret"))
    def test_timeout_is_safe(self, post):
        with self.assertRaises(app.AssistantError) as caught:
            app.request("Test", "https://example.invalid")
        self.assertNotIn("secret", str(caught.exception))

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}, clear=True)
    @patch("requests.Session.post")
    def test_missing_key_makes_no_request(self, post):
        with self.assertRaises(app.AssistantError):
            app.Services().speech("hello")
        post.assert_not_called()

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_speech_requests_matching_pcm_format(self, post):
        post.return_value = Response()
        self.assertEqual(app.Services().speech("hello"), b"\x00\x01")
        self.assertEqual(post.call_args.kwargs["params"]["output_format"], "pcm_24000")

    @patch.dict("os.environ", {"INPUT_DEVICE": "", "AUTO_STOP": "0"}, clear=True)
    @patch("assistant.audio_modules")
    def test_recording_is_valid_wav(self, modules):
        import numpy as np
        from unittest.mock import Mock
        sd = Mock()
        sd.query_devices.return_value = {"default_samplerate": 16000}
        sd.rec.return_value = np.full((16000, 1), 1000, dtype=np.int16)
        modules.return_value = (np, sd)
        data = app.record(1)
        import wave
        with wave.open(io.BytesIO(data), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()),
                             (16000, 1, 2))
            self.assertEqual(wav.getnframes(), 16000)
        sd.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
