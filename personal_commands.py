"""Explicit local commands for configured websites/apps, routines and notes."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import urlencode, urlsplit
import webbrowser
from personal_api_client import PersonalAPIError, handle_api_command


class CommandError(Exception):
    """Safe command failure shown to the user."""


HELP = (
    "Try: what time is it; today's date; open calculator; open notepad; "
    "open YouTube; open Google; search the web for Python tutorials; "
    "take a note buy milk; read my notes; find notes about exams; or start study mode. "
    "Also try: open dashboard; show my tasks; add task Buy milk; complete task 3; "
    "show my projects; what song is playing; pause my music; resume my music; or play playlist followed by its name. "
    "You can add website names in shortcuts.json. Other questions go to Gemini."
)


class PersonalCommands:
    def __init__(self, root: Path):
        self.root = Path(root)

    def websites(self) -> dict[str, str]:
        try:
            settings = json.loads((self.root / "shortcuts.json").read_text(encoding="utf-8"))
            sites = settings["websites"]
            if not isinstance(sites, dict) or len(sites) > 100:
                raise ValueError
            result = {}
            for name, url in sites.items():
                if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,49}", name):
                    raise ValueError
                if not isinstance(url, str) or len(url) > 2048:
                    raise ValueError
                parsed = urlsplit(url)
                if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None):
                    raise ValueError
                result[name] = url
            return result
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError("Check shortcuts.json: websites must map lowercase names to http or https URLs.") from None

    def routine(self, name: str) -> str:
        sites = self.websites()
        apps = self.applications()
        try:
            settings = json.loads((self.root / "shortcuts.json").read_text(encoding="utf-8"))
            routines = settings.get("routines", {})
            targets = routines.get(name)
            if targets is None:
                return "That routine is not configured. Add it under routines in shortcuts.json."
            if (not isinstance(targets, list) or not 1 <= len(targets) <= 5
                    or any(not isinstance(target, str) or target not in {*sites, *apps, "calculator", "notepad"}
                           for target in targets)):
                raise ValueError
        except (OSError, ValueError, AttributeError, TypeError):
            raise CommandError("Check shortcuts.json: each routine needs one to five configured website or app names.") from None
        opened = []
        for target in targets:
            try:
                self.open_target(target)
                opened.append(target)
            except CommandError:
                prefix = "Opened " + ", ".join(opened) + ", but " if opened else ""
                raise CommandError(prefix + f"could not open {target}. The routine stopped.") from None
        return f"Started {name}: opened " + ", ".join(opened) + "."

    def applications(self) -> dict[str, str]:
        try:
            settings = json.loads((self.root / "shortcuts.json").read_text(encoding="utf-8"))
            apps = settings.get("apps", {})
            if not isinstance(apps, dict) or len(apps) > 50:
                raise ValueError
            for name, executable in apps.items():
                if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,49}", name)
                        or not isinstance(executable, str)):
                    raise ValueError
                path = Path(executable)
                if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
                        or path.suffix.lower() != ".exe" or not path.is_file()):
                    raise ValueError
            return apps
        except (OSError, ValueError, AttributeError, TypeError):
            raise CommandError("Check shortcuts.json: apps must map lowercase names to existing local .exe paths, without arguments.") from None

    @staticmethod
    def open_url(url: str, label: str) -> str:
        try:
            opened = webbrowser.open(url, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            raise CommandError("Could not open your browser. Check your default browser setting.")
        return f"Opened {label}."

    def open_target(self, name: str) -> str:
        applications = {"calculator": "calc.exe", "notepad": "notepad.exe"}
        if name in applications:
            app = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / applications[name]
            try:
                subprocess.Popen([str(app)], shell=False)
            except OSError:
                raise CommandError(f"Could not open {name} on this computer.") from None
            return f"Opened {name}."
        sites = self.websites()
        apps = self.applications()
        if name in apps:
            try:
                subprocess.Popen([apps[name]], shell=False)
            except OSError:
                raise CommandError(f"Could not open {name} on this computer.") from None
            return f"Opened {name}."
        if name in sites:
            return self.open_url(sites[name], name)
        return "I can open calculator, notepad, or these configured shortcuts: " + ", ".join([*apps, *sites]) + "."

    def notes(self, text: str | None = None, count_only: bool = False, query: str | None = None) -> str:
        directory = self.root / "data"
        database = directory / "notes.sqlite3"
        if text is not None and len(text) > 2000:
            raise CommandError("That note is too long. Keep each note under 2,000 characters.")
        if text is None and not database.exists():
            return "You have no saved notes yet. Say: take a note, followed by your note."
        try:
            directory.mkdir(exist_ok=True)
            # Transactions make simultaneous saves from separate assistant windows safe.
            connection = sqlite3.connect(database, timeout=5)
            try:
                with connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, created TEXT NOT NULL, text TEXT NOT NULL)")
                    if text is not None:
                        connection.execute("INSERT INTO notes (created, text) VALUES (?, ?)",
                                           (datetime.now().astimezone().isoformat(timespec="seconds"), text))
                        return "Note saved on this computer."
                    count = connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
                    if count_only:
                        return f"You have {count} saved {'note' if count == 1 else 'notes'}."
                    if query is not None:
                        # Escape SQL wildcards so search terms match literally.
                        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                        rows = connection.execute("SELECT text FROM notes WHERE text LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 3", (pattern,)).fetchall()
                    else:
                        rows = connection.execute("SELECT text FROM notes ORDER BY id DESC LIMIT 3").fetchall()
                    if not rows:
                        return "No matching notes found." if query is not None else "You have no saved notes yet."
                    entries = [f"{index}. {row[0][:250]}{'…' if len(row[0]) > 250 else ''}"
                               for index, row in enumerate(rows, 1)]
                    label = "matching notes" if query is not None else "notes"
                    return f"Your latest {len(rows)} {label}, newest first: " + " ".join(entries)
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            raise CommandError("Could not access your local notes. Check the project's data folder.") from None

    def handle(self, text: str, cancel_event=None) -> str | None:
        original = text.strip()
        normalized = re.sub(r"\s+", " ", original.casefold()).rstrip(".!?")
        if normalized in {"help", "commands", "what can you do", "show commands"}:
            return HELP
        try:
            api_reply = handle_api_command(original, cancel_event=cancel_event)
        except PersonalAPIError as exc:
            raise CommandError(str(exc)) from None
        if api_reply is not None:
            return api_reply
        if normalized in {"time", "what time is it", "what is the time", "what's the time", "tell me the time"}:
            return "The time is " + datetime.now().astimezone().strftime("%I:%M %p").lstrip("0") + "."
        if normalized in {"date", "today's date", "what is today's date", "what's today's date", "what is the date", "what's the date", "what day is it"}:
            return "Today is " + datetime.now().astimezone().strftime("%A, %d %B %Y") + "."
        if normalized in {"read my notes", "show my notes", "list my notes"}:
            return self.notes()
        if normalized in {"how many notes do i have", "count my notes"}:
            return self.notes(count_only=True)
        match = re.fullmatch(r"(?:find notes about|search my notes for)\s+(.+)", original, re.IGNORECASE | re.DOTALL)
        if match:
            term = match.group(1).strip().rstrip(".!?")
            if not term or len(term) > 200:
                raise CommandError("Use a note search term between 1 and 200 characters.")
            return self.notes(query=term)
        if normalized in {"start study mode", "start my study routine"}:
            return self.routine("study")
        match = re.fullmatch(r"(?:run|start) routine (.+)", normalized)
        if match:
            return self.routine(match.group(1))
        match = re.fullmatch(r"(?:take a note|save a note|remember that|note)(?:\s*[:,]\s*|\s+)(.+)", original, re.IGNORECASE | re.DOTALL)
        if match:
            note = match.group(1).strip()
            if not note:
                raise CommandError("Say take a note, followed by the text you want to save.")
            return self.notes(note)
        if normalized in {"take a note", "save a note", "remember that", "note"}:
            return "Say take a note, followed by the text you want to save."
        match = re.fullmatch(r"(?:open|launch) (.+)", normalized)
        if match:
            return self.open_target(match.group(1))
        match = re.fullmatch(r"(?:search (?:the )?web for|google search for)\s+(.+)", original, re.IGNORECASE | re.DOTALL)
        if match:
            query = match.group(1).strip()
            return self.open_url("https://www.google.com/search?" + urlencode({"q": query}), "your web search")
        return None
