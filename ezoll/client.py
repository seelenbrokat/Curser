from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Frame,
    Page,
    Playwright,
    sync_playwright,
)

from .config import ARTIFACTS, Settings


@dataclass
class ScreenSnapshot:
    text: str
    saved_path: Path | None = None


class EzollClient:
    """Steuert die aXesTS-Weboberfläche von eZollOnline lokal per Playwright."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "EzollClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        launch_kwargs: dict = {
            "headless": not self.settings.headed,
            "slow_mo": 40 if self.settings.headed else 0,
        }
        if self.settings.channel:
            launch_kwargs["channel"] = self.settings.channel
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(locale="de-AT")
        self._context.set_default_timeout(self.settings.timeout_ms)
        self.page = self._context.new_page()

    def close(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._context = None
        self._browser = None
        self._pw = None
        self.page = None

    def login(self) -> None:
        assert self.page is not None
        page = self.page
        page.goto(self.settings.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        user_box = self._first_locator(
            [
                'input[name*="user" i]',
                'input[id*="user" i]',
                'input[placeholder*="Benutzer" i]',
                'input[type="text"]',
            ]
        )
        pass_box = self._first_locator(
            [
                'input[type="password"]',
                'input[name*="pass" i]',
                'input[id*="pass" i]',
            ]
        )
        if user_box is None or pass_box is None:
            self.screenshot("login-fields-missing")
            raise RuntimeError(
                "Login-Felder nicht gefunden. Screenshot unter artifacts/ gespeichert."
            )

        user_box.fill(self.settings.user)
        pass_box.fill(self.settings.password)

        login_btn = self._first_locator(
            [
                'button:has-text("Login")',
                'input[type="submit"][value*="Login" i]',
                'input[type="button"][value*="Login" i]',
                'a:has-text("Login")',
                'button:has-text("Anmelden")',
            ]
        )
        if login_btn is not None:
            login_btn.click()
        else:
            pass_box.press("Enter")

        page.wait_for_timeout(2500)
        self._assert_not_ip_blocked()
        self.screenshot("after-login")

    def focus_terminal(self) -> Frame | Page:
        """Versucht, den 5250-Terminal-Frame zu fokussieren."""
        assert self.page is not None
        page = self.page
        page.bring_to_front()

        # aXesTS nutzt oft Frames/Framesets – wir nehmen den Frame mit dem meisten Text.
        candidates: list[Frame | Page] = [page, *page.frames]
        best: Frame | Page = page
        best_score = -1
        for frame in candidates:
            try:
                score = len(frame.locator("body").inner_text(timeout=1000))
            except Exception:
                score = 0
            if score > best_score:
                best = frame
                best_score = score

        try:
            best.locator("body").click(timeout=2000, position={"x": 40, "y": 40})
        except Exception:
            page.mouse.click(200, 200)
        return best

    def send_keys(self, keys: str) -> None:
        """
        Sendet Tasten an das Terminal.

        Beispiele:
          "F3"  "Enter"  "Tab"  "PF12"
          "text:ABC123"  -> tippt Klartext
          "keys:Control+a" -> Playwright-Key-Kombi
        """
        assert self.page is not None
        target = self.focus_terminal()
        page = self.page

        for token in self._split_key_tokens(keys):
            if token.startswith("text:"):
                page.keyboard.type(token[5:], delay=40)
            elif token.startswith("keys:"):
                page.keyboard.press(token[5:])
            elif token.upper() in SPECIAL_KEYS:
                page.keyboard.press(SPECIAL_KEYS[token.upper()])
            elif re.fullmatch(r"F\d{1,2}", token, flags=re.I):
                page.keyboard.press(token.upper())
            elif re.fullmatch(r"PF\d{1,2}", token, flags=re.I):
                page.keyboard.press("F" + token[2:])
            else:
                page.keyboard.type(token, delay=40)
            page.wait_for_timeout(250)
            # Nach Navigation kurz warten, falls der Frame neu geladen wird.
            try:
                target.wait_for_timeout(100)
            except Exception:
                pass

    def read_screen(self, save: bool = True) -> ScreenSnapshot:
        assert self.page is not None
        texts: list[str] = []
        for frame in [self.page, *self.page.frames]:
            try:
                text = frame.locator("body").inner_text(timeout=1500).strip()
            except Exception:
                continue
            if text:
                texts.append(text)

        # Deduplizieren, längste Variante zuerst behalten.
        unique: list[str] = []
        for text in sorted(texts, key=len, reverse=True):
            if not any(text in other for other in unique):
                unique.append(text)
        combined = "\n\n----- FRAME -----\n\n".join(unique).strip()

        saved: Path | None = None
        if save:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            saved = ARTIFACTS / f"screen-{stamp}.txt"
            saved.write_text(combined + "\n", encoding="utf-8")
            self.screenshot(f"screen-{stamp}")
        return ScreenSnapshot(text=combined, saved_path=saved)

    def extract_value(self, pattern: str, flags: int = re.I | re.M) -> str | None:
        """Liest den aktuellen Screen und gibt den ersten Regex-Treffer (Gruppe 1 oder Match) zurück."""
        snap = self.read_screen(save=True)
        match = re.search(pattern, snap.text, flags)
        if not match:
            return None
        return match.group(1) if match.lastindex else match.group(0)

    def watch(
        self,
        pattern: str,
        interval_sec: float = 30.0,
        once: bool = False,
    ) -> Iterable[str | None]:
        while True:
            value = self.extract_value(pattern)
            yield value
            if once:
                break
            time.sleep(interval_sec)

    def run_macro(self, steps: Iterable[str]) -> ScreenSnapshot:
        """
        Führt eine einfache Makro-Liste aus.

        Zeilen:
          KEY F3
          TYPE ABC
          WAIT 1.5
          ENTER
        """
        for raw in steps:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "KEY":
                self.send_keys(arg)
            elif cmd == "TYPE":
                self.send_keys(f"text:{arg}")
            elif cmd == "ENTER":
                self.send_keys("Enter")
            elif cmd == "WAIT":
                time.sleep(float(arg or "1"))
            elif cmd == "SCREEN":
                self.read_screen(save=True)
            else:
                raise ValueError(f"Unbekannter Makro-Befehl: {line}")
        return self.read_screen(save=True)

    def screenshot(self, name: str) -> Path:
        assert self.page is not None
        path = ARTIFACTS / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def _assert_not_ip_blocked(self) -> None:
        assert self.page is not None
        body = ""
        try:
            body = self.page.locator("body").inner_text(timeout=2000)
        except Exception:
            return
        lowered = body.lower()
        if "unexpected client ip" in lowered or "disconnected" in lowered:
            # Manche Sessions zeigen Disconnected nur kurz – Screenshot trotzdem.
            self.screenshot("possible-ip-block")
            # Nicht hart abbrechen: lokal kann der Login trotzdem weitergehen.
            print(
                "Hinweis: Seite meldet möglicherweise IP-/Session-Problem. "
                "Bitte Browserfenster prüfen."
            )

    def _first_locator(self, selectors: list[str]):
        assert self.page is not None
        for selector in selectors:
            loc = self.page.locator(selector).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
            # Auch in Frames suchen
            for frame in self.page.frames:
                floc = frame.locator(selector).first
                try:
                    if floc.count() > 0 and floc.is_visible():
                        return floc
                except Exception:
                    continue
        return None

    @staticmethod
    def _split_key_tokens(keys: str) -> list[str]:
        # Kommagetrennt, außer bei text:/keys:
        if keys.startswith("text:") or keys.startswith("keys:"):
            return [keys]
        return [part.strip() for part in keys.split(",") if part.strip()]


SPECIAL_KEYS = {
    "ENTER": "Enter",
    "RETURN": "Enter",
    "TAB": "Tab",
    "ESC": "Escape",
    "ESCAPE": "Escape",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PAGEDOWN": "PageDown",
    "UP": "ArrowUp",
    "DOWN": "ArrowDown",
    "LEFT": "ArrowLeft",
    "RIGHT": "ArrowRight",
}
