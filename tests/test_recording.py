import io
import unittest
from unittest.mock import MagicMock, Mock, patch
import wave

import numpy as np
import assistant
from recording import RecordingOptions, SpeechGate


class RecordingTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_fast_defaults_finish_after_six_tenths_of_quiet(self):
        gate = SpeechGate(RecordingOptions.load())
        gate.observe(1000, 0.2)
        self.assertIsNone(gate.observe(0, 0.5))
        self.assertEqual(gate.observe(0, 0.1), "silence")

    def options(self, **changes):
        values = dict(automatic=True, maximum=15, pause=1, threshold=300, wait=4)
        values.update(changes)
        return RecordingOptions(**values)

    def test_stops_after_speech_and_full_pause(self):
        gate = SpeechGate(self.options())
        self.assertIsNone(gate.observe(1000, 0.2))
        self.assertIsNone(gate.observe(0, 0.9))
        self.assertEqual(gate.observe(0, 0.1), "silence")

    def test_short_pause_does_not_cut_off_question(self):
        gate = SpeechGate(self.options())
        gate.observe(1000, 0.3)
        self.assertIsNone(gate.observe(0, 0.5))
        self.assertIsNone(gate.observe(1000, 0.5))
        self.assertIsNone(gate.observe(0, 0.9))
        self.assertEqual(gate.observe(0, 0.1), "silence")

    def test_silence_and_single_click_do_not_count_as_speech(self):
        gate = SpeechGate(self.options())
        gate.observe(2000, 0.1)
        self.assertEqual(gate.observe(0, 3.9), "no speech")
        self.assertFalse(gate.heard_speech)

    def test_maximum_caps_continuous_sound(self):
        gate = SpeechGate(self.options(maximum=2))
        self.assertEqual(gate.observe(1000, 2), "limit")

    def test_invalid_settings_fail_before_microphone_use(self):
        for setting, value in (("AUTO_STOP", "yes"), ("MAX_RECORD_SECONDS", "nan"),
                               ("SILENCE_SECONDS", "0"), ("SPEECH_THRESHOLD", "-1")):
            with self.subTest(setting=setting), patch.dict("os.environ", {setting: value}, clear=True):
                with self.assertRaises(assistant.AssistantError):
                    assistant.recording_options()

    def microphone(self, levels, overflow=False):
        sound = Mock()
        sound.PortAudioError = type("FakeAudioError", (Exception,), {})
        sound.query_devices.return_value = {"default_samplerate": 16000}
        stream = Mock()
        context = MagicMock()
        context.__enter__.return_value = stream
        sound.InputStream.return_value = context
        stream.read.side_effect = [(np.full((1600, 1), level, dtype=np.int16), overflow) for level in levels]
        return sound, stream, context

    @patch.dict("os.environ", {"SILENCE_SECONDS": "1"}, clear=True)
    def test_actual_capture_stops_early_and_preserves_wav(self):
        sound, stream, context = self.microphone([0] * 2 + [1000] * 4 + [0] * 10)
        with patch("assistant.audio_modules", return_value=(np, sound)):
            data = assistant.record(5)
        with wave.open(io.BytesIO(data), "rb") as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), 16 * 1600)
        self.assertEqual(stream.read.call_count, 16)
        context.__exit__.assert_called_once()

    @patch.dict("os.environ", {"SILENCE_SECONDS": "1"}, clear=True)
    def test_no_speech_never_reaches_transcription(self):
        sound, stream, context = self.microphone([0] * 40)
        with patch("assistant.audio_modules", return_value=(np, sound)), patch("requests.post") as post:
            with self.assertRaisesRegex(assistant.AssistantError, "No clear speech"):
                assistant.record(5)
        self.assertEqual(stream.read.call_count, 40)
        post.assert_not_called()
        context.__exit__.assert_called_once()

    @patch.dict("os.environ", {"SILENCE_SECONDS": "1"}, clear=True)
    def test_overflow_closes_microphone_and_fails_safely(self):
        sound, stream, context = self.microphone([1000], overflow=True)
        with patch("assistant.audio_modules", return_value=(np, sound)):
            with self.assertRaisesRegex(assistant.AssistantError, "interrupted"):
                assistant.record(5)
        context.__exit__.assert_called_once()
