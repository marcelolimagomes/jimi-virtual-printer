"""Agente de bandeja Linux para cupons publicados pela impressora virtual."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from . import (
    APP_COPYRIGHT, APP_DESCRIPTION, APP_NAME, APP_OWNER, APP_SUPPORT_URL, APP_WEBSITE, __version__,
)
from .paths import default_output_dir

LOG = logging.getLogger("posvirtual.tray")
RECEIPT_RE = re.compile(r".+_cupom_\d+\.json$")


def _desktop_modules():
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "A bandeja requer python3-gi, gir1.2-ayatanaappindicator3-0.1 "
            "e libnotify-bin. Instale-os pela distribuição."
        ) from exc
    return AyatanaAppIndicator3, Gio, GLib, Gtk


class TrayAgent:
    def __init__(self, output_dir: Path):
        self.AyatanaAppIndicator3, self.Gio, self.GLib, self.Gtk = _desktop_modules()
        self.output_dir = output_dir.expanduser().resolve()
        self.latest_pdf: Path | None = None
        self.seen: set[str] = set()
        self.seen_pdfs: set[str] = set()
        self.pending_pdfs: set[str] = set()

        self.indicator = self.AyatanaAppIndicator3.Indicator.new(
            "com.taskblu.posvirtual", "printer", self.AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_title("POSvirtual — Taskblu")
        self.indicator.set_status(self.AyatanaAppIndicator3.IndicatorStatus.ACTIVE)

        self.menu = self.Gtk.Menu()
        self.open_item = self.Gtk.MenuItem(label="Abrir PDF mais recente")
        self.open_item.set_sensitive(False)
        self.open_item.connect("activate", self._open_latest)
        self.menu.append(self.open_item)
        history_item = self.Gtk.MenuItem(label="Histórico de PDFs")
        history_item.connect("activate", self._show_history)
        self.menu.append(history_item)
        about_item = self.Gtk.MenuItem(label="Sobre POSvirtual")
        about_item.connect("activate", self._show_about)
        self.menu.append(about_item)
        support_item = self.Gtk.MenuItem(label="Suporte Taskblu — www.taskblu.com")
        support_item.connect("activate", lambda _item: webbrowser.open(APP_SUPPORT_URL))
        self.menu.append(support_item)
        self.menu.append(self.Gtk.SeparatorMenuItem())
        quit_item = self.Gtk.MenuItem(label="Encerrar agente")
        quit_item.connect("activate", lambda _item: self.Gtk.main_quit())
        self.menu.append(quit_item)
        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        existing_pdfs = [path for path in self.output_dir.glob("*.pdf") if path.is_file()]
        if existing_pdfs:
            self.latest_pdf = max(existing_pdfs, key=lambda path: path.stat().st_mtime_ns)
            self.open_item.set_sensitive(True)
        directory = self.Gio.File.new_for_path(str(self.output_dir))
        try:
            self.monitor = directory.monitor_directory(self.Gio.FileMonitorFlags.WATCH_MOVES, None)
        except self.GLib.Error as exc:
            raise OSError(f"não foi possível observar {self.output_dir}: {exc.message}") from exc
        self.monitor.connect("changed", self._on_directory_changed)
        LOG.info("Observando %s", self.output_dir)

    def _on_directory_changed(self, _monitor, file, other_file, _event):
        # _write_metadata() publica por rename de .json.tmp para .json. O PDF
        # sem metadados cobre também a saída direta do CUPS-PDF.
        for candidate in (file, other_file):
            if candidate is None:
                continue
            name = candidate.get_basename()
            if name and RECEIPT_RE.fullmatch(name) and name not in self.seen:
                self.seen.add(name)
                self._handle_metadata(self.output_dir / name)
            elif name and name.lower().endswith(".pdf") and "_cupom_" not in name:
                path = self.output_dir / name
                key = str(path)
                if key not in self.seen_pdfs and key not in self.pending_pdfs:
                    self.pending_pdfs.add(key)
                    self.GLib.timeout_add(300, self._wait_for_pdf, path, None, 0)

    def _wait_for_pdf(self, path: Path, previous: tuple[int, int] | None, stable: int):
        try:
            info = path.stat()
        except FileNotFoundError:
            self.pending_pdfs.discard(str(path))
            return False
        except OSError:
            self.pending_pdfs.discard(str(path))
            LOG.exception("Não foi possível acessar %s", path)
            return False
        current = (info.st_size, info.st_mtime_ns)
        stable = stable + 1 if current == previous and info.st_size > 0 else 0
        if stable >= 2:
            key = str(path)
            self.pending_pdfs.discard(key)
            if key not in self.seen_pdfs:
                self.seen_pdfs.add(key)
                self.latest_pdf = path
                self.open_item.set_sensitive(True)
                self._notify(
                    "Impressão recebida",
                    "O PDF está pronto. Abra ‘Abrir PDF mais recente’ no menu da bandeja.",
                )
            return False
        # A impressão ainda está sendo gravada; aguarde os próximos bytes.
        self.GLib.timeout_add(300, self._wait_for_pdf, path, current, stable)
        return False

    def _handle_metadata(self, metadata_path: Path):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            LOG.exception("Não foi possível ler os metadados de %s", metadata_path)
            return

        receipt_id = str(metadata.get("receipt_id") or metadata_path.stem)
        if metadata.get("result") != "ok":
            detail = metadata.get("render_error") or "o PDF não foi gerado"
            self._notify("Falha na impressão", f"{receipt_id}: {detail}")
            return

        pdf_name = metadata.get("pdf_file")
        if not isinstance(pdf_name, str) or Path(pdf_name).name != pdf_name:
            LOG.warning("Nome de PDF inválido no arquivo %s", metadata_path)
            self._notify("Impressão recebida", f"{receipt_id}, mas o PDF não pôde ser localizado")
            return

        pdf_path = self.output_dir / pdf_name
        if not pdf_path.is_file():
            LOG.warning("PDF não encontrado para %s: %s", receipt_id, pdf_path)
            self._notify("Impressão recebida", f"{receipt_id}, mas o PDF não pôde ser localizado")
            return

        self.latest_pdf = pdf_path
        self.open_item.set_sensitive(True)
        self._notify(
            "Impressão recebida",
            "O PDF está pronto. Abra ‘Abrir PDF mais recente’ no menu da bandeja.",
        )

    @staticmethod
    def _notify(title: str, body: str):
        try:
            subprocess.Popen(
                ["notify-send", "--app-name=POSvirtual — Taskblu", "--icon=printer", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            LOG.exception("Não foi possível enviar a notificação do desktop")

    def _open_latest(self, _item):
        if self.latest_pdf is None or not self.latest_pdf.is_file():
            return
        self._open_pdf(self.latest_pdf)

    def _open_pdf(self, path: Path):
        if not path.is_file():
            return
        uri = self.Gio.File.new_for_path(str(path)).get_uri()
        try:
            self.Gio.AppInfo.launch_default_for_uri(uri, None)
        except self.GLib.Error:
            LOG.exception("Não foi possível abrir %s", path)
            self._notify("Não foi possível abrir o PDF", path.name)

    def _pdf_history(self):
        history = []
        for path in self.output_dir.glob("*.pdf"):
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            history.append((modified, path))
        return sorted(history, key=lambda entry: entry[0], reverse=True)

    def _show_history(self, _item):
        Gtk = self.Gtk
        dialog = Gtk.Dialog(title="Histórico de PDFs — POSvirtual", modal=True)
        dialog.set_default_size(760, 440)
        dialog.add_button("Abrir selecionado", Gtk.ResponseType.OK)
        dialog.add_button("Fechar", Gtk.ResponseType.CANCEL)
        content = dialog.get_content_area()
        history = self._pdf_history()

        if not history:
            content.add(Gtk.Label(label="Nenhum PDF foi gerado nesta pasta."))
        else:
            rows = Gtk.ListStore(str, str, str)
            for modified, path in history:
                date_time = datetime.fromtimestamp(modified).strftime("%d/%m/%Y %H:%M:%S")
                rows.append((date_time, path.name, str(path)))

            tree = Gtk.TreeView(model=rows)
            tree.set_headers_visible(True)
            tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
            tree.append_column(Gtk.TreeViewColumn("Data e hora", Gtk.CellRendererText(), text=0))
            tree.append_column(Gtk.TreeViewColumn("Arquivo PDF", Gtk.CellRendererText(), text=1))
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.add(tree)
            content.pack_start(scroll, True, True, 0)

            def activate_row(view, row, _column):
                dialog.response(Gtk.ResponseType.OK)

            tree.connect("row-activated", activate_row)
            dialog.show_all()
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                model, selected = tree.get_selection().get_selected()
                if selected is not None:
                    self._open_pdf(Path(model.get_value(selected, 2)))
            dialog.destroy()
            return

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _show_about(self, _item):
        dialog = self.Gtk.AboutDialog(transient_for=None, modal=True)
        dialog.set_program_name(APP_NAME)
        dialog.set_version(__version__)
        dialog.set_comments(APP_DESCRIPTION)
        dialog.set_website(APP_WEBSITE)
        dialog.set_website_label("Suporte e informações no site Taskblu")
        dialog.set_copyright(APP_COPYRIGHT)
        dialog.set_authors([APP_OWNER])
        dialog.run()
        dialog.destroy()

    def run(self):
        self.Gtk.main()


def main():
    parser = argparse.ArgumentParser(
        description="POSvirtual da Taskblu: notificações de impressão e abertura do PDF pela bandeja."
    )
    parser.add_argument("--version", action="version", version=f"POSvirtual {__version__} — {APP_WEBSITE}")
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output_dir(),
        help="diretório de PDFs e metadados (padrão: POSVIRTUAL_OUTPUT ou pasta do usuário)",
    )
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if os.name == "nt":
            try:
                from .win_tray import WindowsTrayAgent
            except ImportError as exc:
                raise RuntimeError(
                    "No Windows, instale as dependências em packaging/windows/requirements.txt."
                ) from exc

            WindowsTrayAgent(options.output).run()
        else:
            TrayAgent(options.output).run()
    except RuntimeError as exc:
        print(f"posvirtual-tray: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"posvirtual-tray: não foi possível observar {options.output}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
