from __future__ import annotations

from pathlib import Path

import click

from .client import EzollClient
from .config import load_settings


@click.group()
def main() -> None:
    """Lokale eZollOnline / AS400 Automation."""


@main.command("login-test")
def login_test() -> None:
    """Nur einloggen und Screen speichern (zum Prüfen der Verbindung)."""
    settings = load_settings()
    with EzollClient(settings) as client:
        client.login()
        snap = client.read_screen(save=True)
        click.echo("Login abgeschlossen.")
        if snap.saved_path:
            click.echo(f"Screen gespeichert: {snap.saved_path}")
        click.echo("--- SCREEN ---")
        click.echo(snap.text[:4000] if snap.text else "(leer)")
        if settings.headed:
            click.echo("Browser bleibt 20s offen …")
            assert client.page is not None
            client.page.wait_for_timeout(20_000)


@main.command("send")
@click.argument("keys")
@click.option("--login/--no-login", default=True, help="Zuerst einloggen")
def send_cmd(keys: str, login: bool) -> None:
    """Tasten senden, z.B.: python -m ezoll send "F3" oder 'text:ABC,Enter'."""
    settings = load_settings()
    with EzollClient(settings) as client:
        if login:
            client.login()
        client.send_keys(keys)
        snap = client.read_screen(save=True)
        click.echo(snap.text[:4000] if snap.text else "(leer)")
        if snap.saved_path:
            click.echo(f"\nGespeichert: {snap.saved_path}")


@main.command("screen")
@click.option("--login/--no-login", default=True)
def screen_cmd(login: bool) -> None:
    """Aktuellen Terminal-Text auslesen und speichern."""
    settings = load_settings()
    with EzollClient(settings) as client:
        if login:
            client.login()
        snap = client.read_screen(save=True)
        click.echo(snap.text)
        if snap.saved_path:
            click.echo(f"\nGespeichert: {snap.saved_path}", err=True)


@main.command("extract")
@click.option(
    "--pattern",
    required=True,
    help=r'Regex, z.B. "Betrag\\s*[:=]\\s*([\\d.,]+)"',
)
@click.option("--login/--no-login", default=True)
def extract_cmd(pattern: str, login: bool) -> None:
    """Einen Wert per Regex aus dem aktuellen Screen holen."""
    settings = load_settings()
    with EzollClient(settings) as client:
        if login:
            client.login()
        value = client.extract_value(pattern)
        if value is None:
            raise SystemExit("Kein Treffer für das Muster.")
        click.echo(value)


@main.command("watch")
@click.option(
    "--pattern",
    required=True,
    help=r'Regex mit optionaler Gruppe, z.B. "Status\\s*[:=]\\s*(\\S+)"',
)
@click.option("--interval", default=30.0, show_default=True, help="Sekunden zwischen Reads")
@click.option("--once", is_flag=True, help="Nur einmal auslesen")
@click.option("--login/--no-login", default=True)
def watch_cmd(pattern: str, interval: float, once: bool, login: bool) -> None:
    """Wiederholt einen Wert auslesen und auf stdout ausgeben."""
    settings = load_settings()
    with EzollClient(settings) as client:
        if login:
            client.login()
        for value in client.watch(pattern, interval_sec=interval, once=once):
            click.echo(value if value is not None else "(kein Treffer)")


@main.command("macro")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--login/--no-login", default=True)
def macro_cmd(file: Path, login: bool) -> None:
    """Makrodatei ausführen (siehe macros/beispiel.macro)."""
    settings = load_settings()
    steps = file.read_text(encoding="utf-8").splitlines()
    with EzollClient(settings) as client:
        if login:
            client.login()
        snap = client.run_macro(steps)
        click.echo(snap.text[:4000] if snap.text else "(leer)")
        if snap.saved_path:
            click.echo(f"\nGespeichert: {snap.saved_path}")


if __name__ == "__main__":
    main()
