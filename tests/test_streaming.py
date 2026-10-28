import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests
import assistant


class StreamResponse:
    status_code = 200
    headers = {"Content-Type": "audio/pcm"}

    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


class StreamingTests(unittest.TestCase):
    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_pcm_samples_are_aligned_across_network_chunks(self, post):
        response = StreamResponse([b"a", b"bc", b"def"])
        post.return_value = response
        chunks = list(assistant.Services().speech_chunks("hello"))
        self.assertTrue(all(len(chunk) % 2 == 0 for chunk in chunks))
        self.assertEqual(b"".join(chunks), b"abcdef")
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertTrue(post.call_args.args[0].endswith("/stream"))
        self.assertTrue(response.closed)

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_invalid_or_incomplete_stream_is_closed(self, post):
        for chunks in ([], [b"a"]):
            response = StreamResponse(chunks)
            post.return_value = response
            with self.assertRaises(assistant.AssistantError):
                list(assistant.Services().speech_chunks("hello"))
            self.assertTrue(response.closed)

    @patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-secret"}, clear=True)
    @patch("requests.Session.post")
    def test_interrupted_download_is_safe_and_closed(self, post):
        def interrupted():
            yield b"ab"
            raise requests.ConnectionError("private details")
        response = StreamResponse(interrupted())
        post.return_value = response
        with self.assertRaisesRegex(assistant.AssistantError, "streaming was interrupted"):
            list(assistant.Services().speech_chunks("hello"))
        self.assertTrue(response.closed)

    def output(self):
        sound = Mock()
        sound.PortAudioError = type("FakeAudioError", (Exception,), {})
        context = MagicMock()
        sound.RawOutputStream.return_value = context
        return sound, context.__enter__.return_value

    def test_playback_begins_before_complete_download(self):
        events = []
        sound, speaker = self.output()
        speaker.write.side_effect = lambda chunk: events.append("play " + chunk.decode())
        def chunks():
            events.append("download ab")
            yield b"ab"
            events.append("download cd")
            yield b"cd"
        with patch("assistant.audio_modules", return_value=(None, sound)):
            assistant.play_stream(chunks())
        self.assertEqual(events, ["download ab", "play ab", "download cd", "play cd"])

    def test_stop_aborts_playback_and_closes_generator(self):
        cancel = threading.Event()
        closed = []
        sound, speaker = self.output()
        def chunks():
            try:
                yield b"ab"
                cancel.set()
                yield b"cd"
            finally:
                closed.append(True)
        with patch("assistant.audio_modules", return_value=(None, sound)):
            assistant.play_stream(chunks(), cancel_event=cancel)
        speaker.write.assert_called_once_with(b"ab")
        speaker.abort.assert_called_once()
        self.assertEqual(closed, [True])

    @patch("assistant.play")
    @patch.dict("os.environ", {"STREAM_SPEECH": "0"}, clear=True)
    def test_buffered_fallback_remains_available(self, play):
        services = assistant.Services()
        services.speech = Mock(return_value=b"pcm")
        services.speak("hello")
        play.assert_called_once_with(b"pcm")

    @patch("requests.Session.post")
    def test_pre_cancelled_speech_does_not_make_a_request(self, post):
        cancel = threading.Event()
        cancel.set()
        assistant.Services().speak("hello", cancel_event=cancel)
        post.assert_not_called()
