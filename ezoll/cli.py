from __future__ import annotations

from pathlib import Path

import click

from .buergschaft import query_buergschaft
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


@main.command("buergschaft")
@click.option("--firma", default=None, help="Firmennummer (Default: EZOLL_FIRMA / 100)")
@click.option("--msgty", default=None, help="Message-Type (Default: CC015C)")
@click.option(
    "--datum-von",
    default=None,
    help="Datum von YYYYMMDD (Default: heute minus 6 Monate)",
)
@click.option(
    "--msgty-tabs",
    type=int,
    default=None,
    help="Tabs vom Datumsfeld zum MsgTy-Feld",
)
@click.option(
    "--watch",
    type=float,
    default=None,
    help="Optional: alle N Sekunden erneut abfragen",
)
def buergschaft_cmd(
    firma: str | None,
    msgty: str | None,
    datum_von: str | None,
    msgty_tabs: int | None,
    watch: float | None,
) -> None:
    """Bürgschafts-Gesamtbelastung laut Arbeitsschritte-PDF abfragen."""
    settings = load_settings()

    def run_once() -> str:
        with EzollClient(settings) as client:

            def on_step(label: str, snap) -> None:
                client.screenshot(label)
                click.echo(f"[{label}] screen={snap.saved_path}", err=True)

            result = query_buergschaft(
                client,
                firma=firma or settings.firma,
                msgty=msgty or settings.msgty,
                datum_von=datum_von or settings.datum_von,
                msgty_tabs=settings.msgty_tabs if msgty_tabs is None else msgty_tabs,
                on_step=on_step,
            )
            click.echo(
                f"{result.amount} EUR Bürgschaft  (Seiten geblättert: {result.pages})",
                err=True,
            )
            return result.amount

    if watch is None:
        click.echo(run_once())
        return

    import time

    while True:
        try:
            click.echo(run_once())
        except Exception as exc:  # noqa: BLE001 - Watch soll weiterlaufen
            click.echo(f"Fehler: {exc}", err=True)
        time.sleep(watch)


if __name__ == "__main__":
    main()
