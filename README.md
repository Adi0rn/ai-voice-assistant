# Personal AI Voice Assistant (Windows)

Press Copilot or Enter, speak, pause for one second, and hear a short AI reply.

Microphone -> in-memory WAV -> ElevenLabs Scribe transcription -> Gemini reply
-> ElevenLabs text-to-speech -> speakers.

This is a turn-based assistant with personal commands for selected apps, websites
and local notes. There is no wake word.
It keeps the last ten conversation exchanges in memory, cleared on exit or /reset.
It does not save recordings or conversation logs. Transcripts and replies appear in
your terminal; the cloud providers process the content you send.

## 1. Set up this folder

All project files, dependencies and installer temporary files stay under:
`C:\Adi stuff\Code\AI voice assistant`

Use Windows PowerShell:
```powershell
Set-Location -LiteralPath 'C:\Adi stuff\Code\AI voice assistant'
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Requires Python 3.10+ on PATH (tested here with 3.12). The setup creates .venv
locally, installs the locked binary packages without a global pip cache, and creates .env
only if it does not exist. It does not change your permanent execution policy.
No environment activation is required. Do not run a global pip install.
Internet access is needed for setup and API calls.

## 2. Add your API keys locally

Open .env in your editor. Fill these two values without sharing them in chat:
```dotenv
ELEVENLABS_API_KEY=your_actual_elevenlabs_key
GEMINI_API_KEY=your_actual_gemini_key
```

- ElevenLabs: https://elevenlabs.io/app/settings/api-keys
  Give the key access to Speech to Text and Text to Speech. Your account needs
  available quota and access to the selected models and voice.
- Gemini: https://aistudio.google.com/apikey
  This is the reply generator; ElevenLabs handles the two audio stages.
  Gemini availability and quota depend on your account/region.

API calls can consume quota or incur charges. Check your provider dashboards.
The default voice ID comes from the ElevenLabs API example. Replace
ELEVENLABS_VOICE_ID with one available to your account if it returns 403 or 404.
Model IDs are configurable in .env if your account requires different models;
the default is Gemini 3.5 Flash, verified with a live reply from this account.

.env is plaintext: keep it private, protect access to your Windows account, and
never commit or share it. .gitignore excludes it. No key is hardcoded, printed,
sent in a URL, or included in provider error messages. Existing process
environment variables take precedence over .env. Rotate a key if exposed.
Do not enable verbose HTTP logging containing request headers.

## 3. Test in this order

Run these from the project folder. Stop at the first failure.

### A. Offline tests (no keys, no microphone, no API usage)

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

These fake the cloud responses and recording. Passing them does not prove live
credentials, cloud access, or physical microphone/speaker operation.

### B. Local configuration (no uploads)

```powershell
.\.venv\Scripts\python.exe -B assistant.py --check
.\.venv\Scripts\python.exe -B assistant.py --devices
```

The first validates presence of keys and local dependencies, without authenticating
the keys. The second lists device IDs. Leave INPUT_DEVICE and OUTPUT_DEVICE blank
for Windows defaults, or set numeric IDs from this list.

### C. Local microphone and speaker (no uploads)

```powershell
.\.venv\Scripts\python.exe -B assistant.py --mic-test
```

Speak after the recording message. Pause for one second to finish; you should
hear your own voice. MAX_RECORD_SECONDS caps each recording (default 15).
Use headphones to avoid feedback.

### D. Transcription only (ElevenLabs API usage)

```powershell
.\.venv\Scripts\python.exe -B assistant.py --transcribe-test
```

Say "Hello, this is my microphone test." Expect a matching printed transcript.

### E. AI reply only (Gemini API usage)

```powershell
.\.venv\Scripts\python.exe -B assistant.py --text "Suggest one short study tip."
```

Expect a printed reply. This mode does not use the microphone or ElevenLabs.

### F. Speech only (ElevenLabs API usage)

```powershell
.\.venv\Scripts\python.exe -B assistant.py --tts-test "Hello. Your voice assistant is ready."
```

Expect audible speech. Audio is 24 kHz mono 16-bit PCM, played directly without
FFmpeg, an MP3 player, or saving an audio file. Playback streams by default.

### G. Full assistant

```powershell
.\.venv\Scripts\python.exe -B assistant.py
```

Press Enter, then speak during the recording window. Wait for the printed
transcript, reply, and spoken reply before starting another turn.
Say exactly "stop", "exit", "quit" or "goodbye" to end after transcription.
Type q at the prompt or press Ctrl+C to stop. Type /reset at the prompt to
clear conversation memory. Recording starts only when you press Enter or activate the button launcher.

If your microphone is unavailable, type prompts and hear replies:
```powershell
.\.venv\Scripts\python.exe -B assistant.py --text-mode
```

## Troubleshooting

- Missing Python: install Python 3.10+ yourself, then rerun setup. No system
  software is installed by this project.
- Microphone unavailable/silent: Windows Settings -> Privacy & security ->
  Microphone -> allow microphone access for desktop apps. Also check the Windows
  input device and gain, and INPUT_DEVICE in .env.
- No sound: check Windows output device/volume, OUTPUT_DEVICE and headphones.
- HTTP 401: incorrect or expired key. HTTP 403: key permissions/account access.
- HTTP 404: selected voice/model not accessible. Change the ID in .env.
- HTTP 429: quota, billing or rate limit. Check the provider dashboard and wait.
- Timeout/connection error: check internet, firewall and proxy settings.
  There is a 10-second connection and 90-second read timeout per request.
  Requests are not automatically retried, avoiding accidental duplicate charges.
- Permission restrictions: this chat session may need scoped filesystem access to
  modify this folder, since it is outside the session's default workspace.
- If the model returns no answer, try a different prompt. Filtered replies are
  handled without adding a broken exchange to conversation memory.

## Files

- assistant.py: configuration, microphone, cloud requests, playback and CLI.
- requirements.txt: bounded compatible dependency versions.
- requirements-lock.txt: exact versions installed during verified setup, if present.
- setup.ps1: local environment and dependency setup.
- .env.example: safe configuration template; .env: your private keys.
- tests/: offline regression checks.
- work/: ignored installer scratch files.
- VERIFICATION.md: checks actually performed in this session.

## API references checked during development

- https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash


## Launch with the physical Copilot button

The project includes a Windows-only background listener for the standard
Windows + Shift + F23 gesture emitted by the Copilot button. While enabled,
it consumes that gesture and opens this assistant in a new console window.
Press Enter in that window to record. Close it or type q to finish.
Repeated presses do not create another assistant while the one it opened is running.
It does not record speech until you press Enter, log typing, or call any API itself.
Other keyboard events pass through normally.

Enable from this project directory:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enable-copilot.ps1
```
Disable and restore the ordinary button behavior:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\disable-copilot.ps1
```
Check whether the listener is running:
```powershell
.\.venv\Scripts\python.exe -B copilot_hotkey.py --status
```

The listener runs hidden using this project's Python. Its status file is
work/copilot-status.json. All files stay in this project directory. Nothing is
installed in the Windows Startup folder or registry; enable again after sign-in
or restarting Windows. Disabling the listener leaves any open assistant window
running so you can close it yourself.

The physical button must still be tested on your keyboard. If Copilot continues
to open, report what happens: your keyboard may use a different gesture or
another keyboard manager may be intercepting it. This listener runs on your
normal Windows desktop, and does not override shortcuts in elevated apps or
secure Windows screens.

Windows hook implementation reference:
https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc


## PowerToys Copilot button mapping (preferred when PowerToys is installed)

The earlier standalone listener was stopped for this setup. Do not enable both.
Open PowerToys > Keyboard Manager, enable it, then choose Remap a shortcut.
Add a mapping, use Select to capture the physical Copilot button, and confirm
(the usual gesture is Left Win + Left Shift + F23; some keyboards send Win+C).
Choose Start App as the action, with these fields:

- App: C:\Adi stuff\Code\AI voice assistant\.venv\Scripts\python.exe
- Args: -B "C:\Adi stuff\Code\AI voice assistant\assistant.py" --listen-now
- Start in: C:\Adi stuff\Code\AI voice assistant
- Elevation: Normal
- Visibility: Normal / visible
- Target app: blank (global mapping)

Save with OK. Keep PowerToys running and Keyboard Manager enabled. Enable
PowerToys Run at startup in General if you want the mapping after sign-in.
The app starts recording the first turn immediately after launch. Speak when
its recording message appears. Later turns can use Copilot or Enter when the
assistant is ready, and q or Ctrl+C exits. The mapping must be saved by the user in the
PowerToys UI; its settings are outside the permitted project directory.

Official guide:
https://learn.microsoft.com/en-us/windows/powertoys/keyboard-manager


## Personal commands

Your existing Copilot button mapping continues to work. Close an older assistant
window and launch it again to use the updated code. Say "help" for commands.

| Say or type | Result |
| --- | --- |
| What time is it? | Current Windows local time |
| What is today's date? | Current Windows local date |
| Open calculator | Launch Windows Calculator |
| Open notepad | Launch Windows Notepad |
| Open YouTube / Google / Gmail / GitHub | Open that website in your default browser |
| Search the web for Python tutorials | Open a Google search in your browser |
| Take a note buy milk | Save the note locally |
| Remember that my exam is on Monday | Save that text as a note |
| Read my notes | Read the latest three notes, newest first; long notes are shortened |
| How many notes do I have? | Count saved notes |

These commands are handled locally without sending them to Gemini. Spoken input
still goes to ElevenLabs for transcription, and spoken replies go to ElevenLabs
for speech generation. Reading notes aloud sends the displayed note text to
ElevenLabs. General questions continue to use Gemini.

Notes are stored in this project's data/notes.sqlite3, excluded from Git, and
persist when you close the app. This is a local plaintext database; /reset clears
chat memory and does not erase saved notes. Each note supports up to 2,000
characters. The assistant does not delete or rewrite your existing notes.

### Add your own website

Edit shortcuts.json, adding another lowercase name and URL under websites, e.g.:
```json
{
  "websites": {
    "youtube": "https://www.youtube.com",
    "study portal": "https://example.com"
  }
}
```
Then say "open study portal". Keep any existing entries you want. Changes take
effect on the next open command. Website shortcuts accept only http/https URLs. Calculator and Notepad work out
of the box; additional local .exe shortcuts can be explicitly configured under
apps as described below. Model replies do not execute commands.

### Test commands without a microphone or API calls

```powershell
.\.venv\Scripts\python.exe -B assistant.py --command help
.\.venv\Scripts\python.exe -B assistant.py --command "what time is it"
```

--command never falls back to Gemini; an unknown command displays an error.
--text handles these commands too, then uses Gemini for other questions.
Opening a site or app with --command still performs that requested local action.


## Unexpected reply language

Speech recognition now defaults to English (STT_LANGUAGE=en in .env), and Gemini
is instructed to reply in English unless you explicitly request another language.
Set STT_LANGUAGE=auto only if you want automatic input language detection.
Close existing assistant windows and launch again for configuration changes.
The current eleven_multilingual_v2 speech model does not support the language_code
TTS parameter, so English is controlled through transcription and reply text.
If unexpected speech happens again, compare the printed You and Assistant lines
with the audio to distinguish transcription, reply generation, and pronunciation.


## Silence detection and repeated Copilot activation

This section supersedes earlier fixed-duration recording instructions.
Close any old assistant windows once after this update. The existing App, Args,
and Start in fields in PowerToys remain the same. Set its **If running** option
for this mapping to **Start another instance**. Each button press briefly starts
an activation process; it signals the existing assistant and exits. This is
required: Show Window alone does not send a new recording request.

- First press: open the assistant and start recording.
- When it displays "Press Copilot or Enter": press either to record the next turn.
- Presses while recording or responding are ignored; they do not queue recordings.
- The existing conversation memory stays in that window.
- q or Ctrl+C closes the session. The next Copilot press starts a fresh one.

This session reuse applies to the PowerToys --listen-now launcher. Diagnostic
commands and normal terminal launches run independently. Windows may prevent the
console from gaining foreground focus, particularly with Windows Terminal; the
activation signal still works when the assistant is ready.

Recording defaults in .env:
```dotenv
AUTO_STOP=1
MAX_RECORD_SECONDS=15
SILENCE_SECONDS=1.0
SPEECH_WAIT_SECONDS=4
SPEECH_THRESHOLD=300
```
The microphone is checked in 0.1-second blocks. After at least 0.2 seconds of
sound above the threshold, a full second of quiet finishes the recording.
Brief pauses do not end it. No clear speech within four seconds cancels locally
without uploading audio. A 15-second maximum prevents indefinite recording.
This measures volume, rather than recognizing speech locally: sustained noise
can keep a recording open. Use headphones and a quiet room for best results.

If quiet speech is missed, lower SPEECH_THRESHOLD, e.g. to 150. If room noise
keeps recording open, raise it, e.g. to 600. Increase SILENCE_SECONDS to 1.5 if
your pauses are being cut off. Reopen the assistant after changing .env.
Set AUTO_STOP=0 to restore the old RECORD_SECONDS fixed-duration behavior.
Run --mic-test to hear where a local recording starts and ends without uploads.


## Floating overlay (preferred launcher)

The overlay is a small, always-on-top panel near the bottom-right of the screen.
Drag its header to move it. It shows Listening, Transcribing, Thinking, Preparing
voice and Speaking. Listen records a turn; the text box and Send text let you
enter a request without a microphone. Reset chat clears session memory without
deleting notes. Hide (or Escape) hides the panel; Copilot restores it and records
a new turn when ready. Close ends the session. Hide stops the current turn and disables hands-free mode.

Change the PowerToys mapping to:

- App: C:\Adi stuff\Code\AI voice assistant\.venv\Scripts\pythonw.exe
- Args: -B "C:\Adi stuff\Code\AI voice assistant\overlay.py" --listen-now
- Start in: C:\Adi stuff\Code\AI voice assistant
- If running: Start another instance
- Elevation: Normal
- Keep the Copilot shortcut captured on the left unchanged.

pythonw.exe launches the GUI without a console window. The short activation
process also uses pythonw, so repeated button presses do not flash a terminal.
The overlay shares the same Windows session activation as the terminal version;
close an older terminal session once when switching launchers.

To show the overlay idle, without recording, run:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-overlay.ps1
```
The CLI assistant.py remains available for diagnostics and automated checks.
No new dependencies are required: the overlay uses Python's bundled Tkinter.
The UI stays responsive because recording and API calls run on a worker thread.
A close request cancels automatic capture, prevents subsequent uploads/actions
when detected, and ends the app. Busy button presses are ignored rather than
queued. Closed sessions do not keep conversation memory.


## Streamed voice and optional hands-free mode

Speech playback now starts as PCM audio arrives from ElevenLabs, instead of
waiting for the whole speech file. The Gemini text response is still generated
before speech starts. The same model and voice are retained. STREAM_SPEECH=1 is
the default; set it to 0 in .env to restore buffered playback. Failed or partial
streams are closed and reported without automatic retries or duplicate charges.

Hands-free is off on each new session. Enable the Hands-free checkbox or say
"start hands-free mode". After a successful reply finishes playing, the overlay
waits 0.5 seconds and records the next turn. It never records during its own
speech playback. Use headphones to reduce feedback.

Say "stop listening" to end the loop, or click Stop to cancel the active turn
and disable the loop. Unchecking Hands-free lets the current turn finish and
prevents the next turn. Silence/no clear speech or any error also switches the
loop off. Hide disables the loop and cancels the active turn; Copilot can restore
the panel later. An in-flight HTTP request cannot be instantly interrupted, but
its result is discarded after cancellation and the UI remains responsive.
Spoken stop commands require transcription, so the Stop button is the immediate
local control. Hands-free can use API quota on each spoken turn.

## Search notes

Say "find notes about exams" or "search my notes for Monday". Search matches the
literal text in saved notes and returns up to the three newest matches. Notes
are not sent to Gemini for search. If read aloud, matching text goes to ElevenLabs.

## Custom apps and routines

shortcuts.json now supports websites, apps and routines. Existing entries are
preserved. The included study routine opens Google Docs and Google when you say
"start study mode". It does not start a timer or change system focus settings.

To add an app, put its full existing local .exe path in apps. Example layout
(replace the example path with your installed app's real path):
```json
{
  "websites": {
    "google": "https://www.google.com",
    "docs": "https://docs.google.com"
  },
  "apps": {
    "my editor": "C:\\Program Files\\My Editor\\Editor.exe"
  },
  "routines": {
    "study": ["docs", "google"],
    "writing": ["my editor", "docs"]
  }
}
```
Say "open my editor" or "run routine writing". Only add apps you intend to open;
app entries launch a single executable with no arguments or shell. Routines
contain one to five configured names; Calculator and Notepad are also allowed.
All routine targets are validated before opening any, and a failed launch stops
the rest while reporting what was opened. Website/app launches are explicit
local commands, and are not executed from Gemini's generated text.

Close the old overlay and reopen through Copilot once to load this update.
The existing pythonw.exe / overlay.py PowerToys mapping needs no change.

## Personal API dashboard and commands

The assistant now connects to the separate Personal API server at http://127.0.0.1:8000. Keep that server running and open http://127.0.0.1:8000/dashboard for task, project, and Spotify controls. If the overlay is already open, close it and reopen it once through your usual launcher/Copilot setup to load the updated command handler.

Say: "show my tasks", "show high priority tasks", "add task Buy milk", "complete task 3", "show my projects", "project details for Personal API", "what song is playing", "pause my music", "resume my music", "play playlist Heart and soul", or "open dashboard".

Only exact supported actions run; ordinary questions still use Gemini. API failures are spoken rather than sent to Gemini as fallback. The basic add-task command saves the title; edit deadlines and priorities in the dashboard. Playlist names match exactly, ignoring case; use the playlist link if names are duplicated.

To check the connection without audio or cloud model calls, run from this assistant's folder:

```powershell
& '.\.venv\Scripts\python.exe' -B assistant.py --command 'show my tasks'
& '.\.venv\Scripts\python.exe' -B assistant.py --command 'what song is playing'
```

PERSONAL_API_URL is optional in .env and defaults to http://127.0.0.1:8000. Only loopback HTTP addresses are accepted. Spotify credentials stay in the API project; the assistant does not read them. Voice commands still use the existing ElevenLabs transcription and speech services. Typed --command checks bypass audio and Gemini.

Additional PAPI connection commands: show my calendar; show unread emails; show my emails; show my repositories; show my github activity. Set up Google and GitHub at http://127.0.0.1:8000/connections/setup first, and restart the overlay to load the updated phrase list. These commands read information; they do not send emails, create calendar events, or change repositories.


## Faster response defaults (19 October 2026)

- Silence detection ends a turn after 0.6 seconds of quiet, previously 1.0.
- Speech uses eleven_flash_v2_5 with the same selected voice, replacing
  eleven_multilingual_v2. Stream reads use smaller chunks for earlier delivery.
- Gemini 3.x requests use minimal thinking by default and request one or two
  concise sentences unless more detail is requested. The output token limit
  remains 1,024 so answers are not deliberately truncated for speed.
- A persistent HTTP session reuses connections across turns. Provider keys
  remain explicit per-request headers and are not shared as session defaults.
- Hands-free resumes 0.5 seconds after playback, previously 0.7.

One short before/after check measured reply generation at 3.074 vs 2.065 seconds,
first downloaded speech audio at 1.632 vs 0.693 seconds, and full speech download
at 1.786 vs 0.841 seconds. These were single requests, not a statistically reliable
benchmark. They exclude microphone capture, transcription and output-device
latency; cloud timing and answer length can vary.

Reopen the overlay to load these changes. To restore earlier behavior, set
SILENCE_SECONDS=1.0, ELEVENLABS_TTS_MODEL=eleven_multilingual_v2 and
GEMINI_THINKING_LEVEL=default in .env. For difficult questions where reasoning
quality matters more than speed, choose low, medium or high instead of minimal.
If your natural pauses are cut off, increase SILENCE_SECONDS to 0.8 or 1.0.

Provider references:
- https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5
- https://elevenlabs.io/docs/eleven-api/concepts/latency


## Spotify songs by title and artist

Say "Open Spotify and play Kiss of Life by Sade", "Play Kiss of Life by Sade on
Spotify", or "Play the song Kiss of Life by Sade". These requests route to the
Personal API before generic app-opening commands. Reopen an older overlay once
for the new routing. Your existing PowerToys mapping needs no change.

The API now searches for the requested title/artist, requires a matching playable
track, and sends its URI to the current Spotify device. It reports missing
matches, device problems and permissions instead of claiming playback succeeded.
Playlist, pause and resume commands continue to work. Desktop Spotify or the
connected browser player must be available for playback.


## Play music in the dashboard browser

Music-start commands now use the dashboard's browser player: "play music",
"resume music", "play playlist Heart and soul", and songs such as "play Kiss of
Life by Sade". A ready dashboard player is reused. Otherwise the assistant opens
/dashboard?voice_music=1#music, waits up to 35 seconds for the Spotify SDK to
connect, and sends that browser's device_id with the command. It does not fall
back to a different Spotify device. If the API server is stopped, the assistant
can start the sibling Personal API/start-papi.ps1 launcher automatically.

The dashboard and desktop Spotify can both be closed before the request. Spotify
must already be connected with browser-streaming permissions and Premium. The
browser must support Spotify protected playback. Some browsers require an actual
click on Play here to allow audio in a newly opened tab; the assistant cannot
bypass that restriction and explains the action when reported by the dashboard.
Closing a tab expires its device registration. Clicking Stop in the overlay
cancels waiting for the dashboard and prevents a later queued playback request.

Close/reopen an older overlay and refresh an already-open dashboard once after
this update. Your PowerToys mapping stays the same. Pause commands still pause
the current Spotify playback without unnecessarily opening another page.
