"""Small Windows voice assistant. Audio and conversation stay in memory locally."""
from __future__ import annotations

import argparse
import io
import math
import os
from pathlib import Path
import re
import sys
import wave
from personal_commands import CommandError, PersonalCommands
from recording import RecordingOptions, SpeechGate

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


class AssistantError(Exception):
    """Safe, user-facing failure; never includes request headers or keys."""


def number(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        raise AssistantError("RECORD_SECONDS must be a number between 1 and 30.") from None
    if not math.isfinite(result) or not 1 <= result <= 30:
        raise AssistantError("RECORD_SECONDS must be between 1 and 30.")
    return result


def device(value: str):
    value = value.strip()
    if not value:
        return None
    if not value.isdecimal():
        raise AssistantError("Device settings must be numeric IDs from --devices, or blank.")
    return int(value)


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith(("your_", "replace", "paste", "<")):
        raise AssistantError(f"Set {name} in {ROOT / '.env'} first.")
    return value


def identifier(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise AssistantError(f"{name} must be a nonempty model or voice ID.")
    return value


def transcription_language() -> str | None:
    value = os.getenv("STT_LANGUAGE", "en").strip().lower()
    if value == "auto":
        return None
    if not re.fullmatch(r"[a-z]{2,3}", value):
        raise AssistantError("STT_LANGUAGE must be a two/three-letter language code, such as en, or auto.")
    return value


def request(service: str, url: str, session=None, **kwargs):
    import requests
    try:
        post = session.post if session is not None else requests.post
        response = post(url, timeout=(10, 90), allow_redirects=False, **kwargs)
    except requests.Timeout:
        raise AssistantError(f"{service} timed out. Try again when your connection is stable.") from None
    except requests.RequestException:
        raise AssistantError(f"Could not reach {service}. Check internet access and proxy settings.") from None
    if response.status_code != 200:
        hints = {
            400: "Check the selected model and request settings.",
            401: "Check the API key in .env.",
            403: "Check key permissions and account access.",
            404: "Check that the model or voice ID is available to your account.",
            422: "Check the model, voice and audio settings.",
            429: "Check quota or billing, or wait before retrying.",
        }
        hint = hints.get(response.status_code, "The service may be unavailable. Try again later.")
        if kwargs.get("stream"):
            response.close()
        # Do not print the raw response: providers can echo sensitive inputs.
        raise AssistantError(f"{service} returned HTTP {response.status_code}. {hint}")
    return response


def json_body(response, service: str) -> dict:
    try:
        body = response.json()
    except ValueError:
        raise AssistantError(f"{service} returned invalid JSON.") from None
    if not isinstance(body, dict):
        raise AssistantError(f"{service} returned an unexpected response.")
    return body


class Services:
    def __init__(self):
        import requests
        self.http = requests.Session()
        self.history: list[dict] = []

    def transcribe(self, wav: bytes) -> str:
        key = required("ELEVENLABS_API_KEY")
        data = {"model_id": identifier("ELEVENLABS_STT_MODEL", "scribe_v2"),
                "tag_audio_events": "false", "diarize": "false"}
        language = transcription_language()
        if language:
            data["language_code"] = language
        response = request(
            "ElevenLabs transcription", "https://api.elevenlabs.io/v1/speech-to-text",
            session=self.http,
            headers={"xi-api-key": key},
            data=data,
            files={"file": ("microphone.wav", wav, "audio/wav")},
        )
        text = json_body(response, "ElevenLabs").get("text")
        if not isinstance(text, str):
            raise AssistantError("ElevenLabs returned no transcript field.")
        return text.strip()

    def reply(self, text: str) -> str:
        key = required("GEMINI_API_KEY")
        model = identifier("GEMINI_MODEL", "gemini-3.5-flash")
        config = {"maxOutputTokens": 1024}
        thinking = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip().lower()
        if thinking not in {"default", "minimal", "low", "medium", "high"}:
            raise AssistantError("GEMINI_THINKING_LEVEL must be default, minimal, low, medium, or high.")
        if model.startswith("gemini-3") and thinking != "default":
            config["thinkingConfig"] = {"thinkingLevel": thinking}
        turn = {"role": "user", "parts": [{"text": text}]}
        response = request(
            "Gemini", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            session=self.http,
            headers={"x-goog-api-key": key},
            json={
                "systemInstruction": {"parts": [{"text":
                    "You are a helpful personal voice assistant. Answer naturally in plain text, "
                    "in English by default, even if a transcript contains another language. "
                    "Switch languages only when the user explicitly asks you to do so. "
                    "Use one or two short sentences unless the user asks for more detail. Do not claim to perform actions "
                    "or have live information. Supported local commands are handled separately; "
                    "you cannot perform additional computer actions or save notes yourself."}]},
                "contents": self.history + [turn],
                "generationConfig": config,
            },
        )
        body = json_body(response, "Gemini")
        try:
            parts = body["candidates"][0]["content"]["parts"]
            answer = " ".join(p["text"] for p in parts
                              if isinstance(p.get("text"), str) and not p.get("thought")).strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            answer = ""
        if not answer:
            raise AssistantError("Gemini returned no answer; it may have blocked the prompt. Try rephrasing.")
        # Keep at most ten successful exchanges, and only commit successful replies.
        self.history = (self.history + [turn, {"role": "model", "parts": [{"text": answer}]}])[-20:]
        return answer

    def speech(self, text: str) -> bytes:
        voice = identifier("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        response = request(
            "ElevenLabs speech", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            session=self.http,
            headers={"xi-api-key": required("ELEVENLABS_API_KEY"),
                     "Accept": "application/octet-stream"},
            params={"output_format": "pcm_24000"},
            json={"text": text, "model_id": identifier("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")},
        )
        audio = response.content
        if not audio or len(audio) % 2 or "json" in response.headers.get("Content-Type", "").lower():
            raise AssistantError("ElevenLabs returned invalid PCM audio.")
        return audio

    def speech_chunks(self, text: str):
        """Close the HTTP stream on completion, cancellation, or playback failure."""
        import requests
        voice = identifier("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        response = request(
            "ElevenLabs speech", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream",
            session=self.http,
            headers={"xi-api-key": required("ELEVENLABS_API_KEY"), "Accept": "application/octet-stream"},
            params={"output_format": "pcm_24000"}, stream=True,
            json={"text": text, "model_id": identifier("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")},
        )
        pending = b""
        received = False
        try:
            content_type = response.headers.get("Content-Type", "").lower()
            if "json" in content_type or content_type.startswith("text/"):
                raise AssistantError("ElevenLabs returned invalid PCM audio.")
            for chunk in response.iter_content(chunk_size=2048):
                pending += chunk
                length = len(pending) // 2 * 2
                if length:
                    received = True
                    yield pending[:length]
                    pending = pending[length:]
            if pending or not received:
                raise AssistantError("ElevenLabs returned incomplete PCM audio.")
        except requests.RequestException:
            raise AssistantError("Speech streaming was interrupted. Check your connection and try another turn.") from None
        finally:
            response.close()

    def speak(self, text: str, on_start=None, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            return
        if streaming_enabled():
            play_stream(self.speech_chunks(text), on_start=on_start, cancel_event=cancel_event)
        else:
            pcm = self.speech(text)
            if cancel_event is None or not cancel_event.is_set():
                if on_start:
                    on_start()
                play(pcm)


def streaming_enabled():
    value = os.getenv("STREAM_SPEECH", "1").strip()
    if value not in {"0", "1"}:
        raise AssistantError("STREAM_SPEECH must be 1 or 0.")
    return value == "1"


def play_stream(chunks, on_start=None, cancel_event=None):
    _, sd = audio_modules()
    started = False
    try:
        with sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16",
                                device=device(os.getenv("OUTPUT_DEVICE", ""))) as speaker:
            if cancel_event is not None and cancel_event.is_set():
                return
            for chunk in chunks:
                if cancel_event is not None and cancel_event.is_set():
                    speaker.abort()
                    return
                if not started:
                    if on_start:
                        on_start()
                    started = True
                speaker.write(chunk)
    except sd.PortAudioError:
        raise AssistantError("Speaker playback failed. Check OUTPUT_DEVICE and Windows sound settings.") from None
    finally:
        close = getattr(chunks, "close", None)
        if close:
            close()


def audio_modules():
    import numpy as np
    import sounddevice as sd
    return np, sd


def recording_options():
    try:
        return RecordingOptions.load()
    except ValueError as exc:
        raise AssistantError(str(exc)) from None


def record(seconds: float, on_ready=None, cancel_event=None) -> bytes:
    np, sd = audio_modules()
    options = recording_options()
    selected = device(os.getenv("INPUT_DEVICE", ""))
    try:
        info = sd.query_devices(selected, "input")
        rate = int(info["default_samplerate"])
        sd.check_input_settings(device=selected, channels=1, dtype="int16", samplerate=rate)
        if options.automatic:
            gate = SpeechGate(options)
            blocks = []
            captured = 0
            limit = round(options.maximum * rate)
            with sd.InputStream(samplerate=rate, channels=1, dtype="int16", device=selected) as microphone:
                if on_ready:
                    on_ready()
                print(f"Recording... Speak now. Stops after {options.pause:g}s of quiet (maximum {options.maximum:g}s).", flush=True)
                while captured < limit:
                    if cancel_event is not None and cancel_event.is_set():
                        raise AssistantError("Recording cancelled.")
                    count = min(max(1, round(rate * 0.1)), limit - captured)
                    block, overflow = microphone.read(count)
                    if overflow:
                        raise AssistantError("Microphone audio was interrupted. Try recording again.")
                    blocks.append(block.copy())
                    captured += len(block)
                    rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
                    reason = gate.observe(rms, len(block) / rate)
                    if reason:
                        break
            if not gate.heard_speech:
                raise AssistantError("No clear speech detected; nothing was uploaded. Speak closer to the microphone and try again.")
            samples = np.concatenate(blocks)
            if reason == "limit":
                print("Recording limit reached. Increase MAX_RECORD_SECONDS if your question was cut off.")
        else:
            if on_ready:
                on_ready()
            print(f"Recording for {seconds:g} seconds... Speak now.", flush=True)
            samples = sd.rec(round(seconds * rate), samplerate=rate, channels=1,
                             dtype="int16", device=selected, blocking=True)
    except sd.PortAudioError:
        raise AssistantError("Microphone unavailable. Check Windows microphone permissions and INPUT_DEVICE.") from None
    finally:
        sd.stop()
    if np.max(np.abs(samples.astype(np.int32))) < 100:
        raise AssistantError("Recording is nearly silent. Check your microphone, gain and INPUT_DEVICE.")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.astype("<i2").tobytes())
    return stream.getvalue()


def play(pcm: bytes, rate: int = 24000):
    np, sd = audio_modules()
    try:
        sd.play(np.frombuffer(pcm, dtype="<i2"), samplerate=rate,
                device=device(os.getenv("OUTPUT_DEVICE", "")), blocking=True)
    except sd.PortAudioError:
        raise AssistantError("Speaker playback failed. Check OUTPUT_DEVICE and Windows sound settings.") from None
    finally:
        sd.stop()


def microphone_test(seconds: float):
    recording = record(seconds)
    with wave.open(io.BytesIO(recording), "rb") as wav:
        rate = wav.getframerate()
        pcm = wav.readframes(wav.getnframes())
    print("Playing your recording locally. No audio is uploaded.")
    play(pcm, rate)


def is_exit(text: str) -> bool:
    return text.casefold().strip().rstrip(".!?") in {"quit", "exit", "stop", "goodbye"}


def parser():
    p = argparse.ArgumentParser(description="Press Enter to speak; q or Ctrl+C to quit.")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Check local configuration; no API calls")
    modes.add_argument("--devices", action="store_true", help="List local audio devices")
    modes.add_argument("--mic-test", action="store_true", help="Record and replay locally")
    modes.add_argument("--transcribe-test", action="store_true", help="Record and upload only to ElevenLabs")
    modes.add_argument("--tts-test", metavar="TEXT", help="Speak text using only ElevenLabs")
    modes.add_argument("--text", metavar="TEXT", help="Local command or Gemini reply, without audio")
    modes.add_argument("--command", metavar="TEXT", help="Run an explicit personal command without Gemini or audio")
    modes.add_argument("--text-mode", action="store_true", help="Type prompts and hear replies")
    modes.add_argument("--listen-now", action="store_true", help="Record the first turn immediately, for a button launcher")
    return p


def main(argv=None, activation=None) -> int:
    args = parser().parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False, interpolate=False)
        if args.devices:
            _, sd = audio_modules()
            print(sd.query_devices())
            return 0
        seconds = number(os.getenv("RECORD_SECONDS", "5"))
        if args.check:
            required("ELEVENLABS_API_KEY")
            required("GEMINI_API_KEY")
            for name, default in (("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"),
                                  ("ELEVENLABS_STT_MODEL", "scribe_v2"),
                                  ("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5"),
                                  ("GEMINI_MODEL", "gemini-3.5-flash")):
                identifier(name, default)
            device(os.getenv("INPUT_DEVICE", ""))
            device(os.getenv("OUTPUT_DEVICE", ""))
            transcription_language()
            recording_options()
            streaming_enabled()
            audio_modules()
            print("Local configuration and imports OK. Keys were not authenticated; no API calls made.")
            return 0
        if args.mic_test:
            microphone_test(seconds)
            return 0
        commands = PersonalCommands(ROOT)
        if args.command is not None:
            answer = commands.handle(args.command)
            if answer is None:
                raise CommandError("Unknown local command. Run --command help to see available commands.")
            print("Assistant:", answer)
            return 0
        services = Services()
        if args.transcribe_test:
            required("ELEVENLABS_API_KEY")
            print("Transcript:", services.transcribe(record(seconds)) or "(no speech detected)")
            return 0
        if args.tts_test is not None:
            services.speak(args.tts_test)
            return 0
        if args.text is not None:
            print("Assistant:", commands.handle(args.text) or services.reply(args.text))
            return 0
        required("ELEVENLABS_API_KEY")
        print("Ready. Audio goes to ElevenLabs; conversation text goes to Gemini.")
        print("Say help for personal commands. Local commands do not use Gemini.")
        print("Type /reset to clear conversation memory. Use q or Ctrl+C to quit.")
        listen_now = args.listen_now
        while True:
            if listen_now:
                command = ""
                listen_now = False
            else:
                command = (activation.wait_for_command() if activation is not None
                           else input("You: " if args.text_mode else "Press Enter to record (q to quit): ").strip())
            if command.casefold() in {"q", "quit", "exit"}:
                break
            if command == "/reset":
                services.history.clear()
                print("Conversation cleared.")
                continue
            if args.text_mode and not command:
                continue
            if not args.text_mode and command:
                print("Press Enter without typing to record, or type q to quit.")
                continue
            try:
                text = command if args.text_mode else services.transcribe(record(seconds))
                if not text:
                    print("No speech detected. Try again.")
                    continue
                if not args.text_mode:
                    print("You:", text)
                if is_exit(text):
                    break
                answer = commands.handle(text) or services.reply(text)
                print("Assistant:", answer)
                services.speak(answer)
            except (AssistantError, CommandError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        return 0
    except ImportError:
        print("Missing dependency. Run setup.ps1 first.", file=sys.stderr)
        return 1
    except (AssistantError, CommandError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from activation import launch
    raise SystemExit(launch(main, ROOT))
