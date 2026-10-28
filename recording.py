"""Sample-count based speech/silence detection; no audio or network side effects."""
from dataclasses import dataclass
import math
import os


def setting(name, default, minimum, maximum):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a number between {minimum} and {maximum}.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


@dataclass
class RecordingOptions:
    automatic: bool
    maximum: float
    pause: float
    threshold: float
    wait: float

    @classmethod
    def load(cls):
        automatic = os.getenv("AUTO_STOP", "1").strip()
        if automatic not in {"0", "1"}:
            raise ValueError("AUTO_STOP must be 1 or 0.")
        return cls(automatic == "1", setting("MAX_RECORD_SECONDS", 15, 1, 60),
                   setting("SILENCE_SECONDS", 0.6, 0.3, 3),
                   setting("SPEECH_THRESHOLD", 300, 50, 10000),
                   setting("SPEECH_WAIT_SECONDS", 4, 1, 15))


class SpeechGate:
    def __init__(self, options):
        self.options = options
        self.elapsed = self.voiced = self.quiet = 0.0
        self.heard_speech = False

    def observe(self, rms, duration):
        self.elapsed += duration
        if rms >= self.options.threshold:
            self.voiced += duration
            self.quiet = 0.0
            # Reject isolated clicks; retain all captured samples, including onset.
            if self.voiced >= 0.2 - 1e-9:
                self.heard_speech = True
        else:
            self.voiced = 0.0
            self.quiet += duration
        if self.heard_speech and self.quiet >= self.options.pause - 1e-9:
            return "silence"
        if not self.heard_speech and self.elapsed >= self.options.wait - 1e-9:
            return "no speech"
        if self.elapsed >= self.options.maximum - 1e-9:
            return "limit"
        return None
