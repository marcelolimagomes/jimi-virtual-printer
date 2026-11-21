"""Windows system-tray frontend for the POSvirtual printer and PDF watcher."""
from __future__ import annotations

import asyncio
import ctypes
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import socket
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from . import APP_COPYRIGHT, APP_DESCRIPTION, APP_NAME, APP_OWNER, APP_SUPPORT_URL, __version__
from .server import PrinterServer

LOG = logging.getLogger("posvirtual.win_tray")
RECEIPT_RE = re.compile(r".+_cupom_\d+\.json$")
DEFAULT_HOST = os.environ.get("POSVIRTUAL_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("POSVIRTUAL_PORT", "9100"))
DEFAULT_PAPER_MM = int(os.environ.get("POSVIRTUAL_PAPER_MM", "80"))


def _icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((9, 20, 55, 50), radius=5, fill="#156f82")
    draw.rounded_rectangle((17, 8, 47, 28), radius=3, fill="#eaf8f8", outline="#156f82", width=3)
    draw.rectangle((16, 34, 48, 58), fill="#ffffff", outline="#156f82", width=3)
    draw.line((22, 41, 42, 41), fill="#156f82", width=2)
    draw.line((22, 47, 39, 47), fill="#156f82", width=2)
    draw.ellipse((46, 25, 51, 30), fill="#ffffff")
    return image


class WindowsTrayAgent:
    """Watch output files, start the local printer server, and expose tray actions."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.latest_pdf: Path | None = None
        self.seen_metadata = {path.name for path in self.output_dir.glob("*.json")}
        self.seen_direct_pdfs: set[str] = set()
        self.pending_pdfs: dict[str, tuple[tuple[int, int], int]] = {}
        self.stop_event = threading.Event()
        self.server_stop = threading.Event()
        self.server_ready = threading.Event()
        self.server_thread: threading.Thread | None = None
        self.server_error: Exception | None = None
        self.server_owned = False
        self.external_server = False
        self.icon: pystray.Icon | None = None

        existing_pdfs = [path for path in self.output_dir.glob("*.pdf") if path.is_file()]
        if existing_pdfs:
            self.latest_pdf = max(existing_pdfs, key=lambda path: path.stat().st_mtime_ns)
            self.seen_direct_pdfs.update(
                str(path) for path in existing_pdfs if "_cupom_" not in path.name
            )

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                "Abrir PDF mais recente", self._open_latest,
                enabled=lambda _item: self.latest_pdf is not None,
            ),
            pystray.MenuItem("Histórico de PDFs", self._show_history),
            pystray.MenuItem(
                lambda _item: (
                    f"Porta {DEFAULT_PORT} já em uso" if self.external_server else
                    "Parar servidor de impressão" if self.server_owned else
                    "Iniciar servidor de impressão"
                ),
                self._toggle_server,
                enabled=lambda _item: not self.external_server,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sobre POSvirtual", self._show_about),
            pystray.MenuItem("Suporte Taskblu — www.taskblu.com", self._open_support),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Encerrar agente", self._quit),
        )

    @staticmethod
    def _server_is_listening() -> bool:
        probe_host = "127.0.0.1" if DEFAULT_HOST in ("0.0.0.0", "::") else DEFAULT_HOST
        try:
            with socket.create_connection((probe_host, DEFAULT_PORT), timeout=0.25):
                return True
        except OSError:
            return False

    def _serve(self):
        try:
            printer = PrinterServer(self.output_dir, DEFAULT_PAPER_MM)
            asyncio.run(
                printer.serve(
                    DEFAULT_HOST,
                    DEFAULT_PORT,
                    stop_event=self.server_stop,
                    started_event=self.server_ready,
                )
            )
        except Exception as exc:
            self.server_error = exc
            self.server_ready.set()
            LOG.exception("Servidor de impressão encerrou com erro")
            if self.icon is not None:
                self._notify("Falha no servidor de impressão", str(exc))
        finally:
            self.server_owned = False
            if self.icon is not None:
                self.icon.update_menu()

    def _start_server(self):
        if self._server_is_listening():
            self.external_server = True
            LOG.info("Já há um serviço usando a porta %s", DEFAULT_PORT)
            if self.icon is not None:
                self.icon.update_menu()
            return
        self.external_server = False
        self.server_stop.clear()
        self.server_ready.clear()
        self.server_error = None
        self.server_thread = threading.Thread(target=self._serve, name="posvirtual-server", daemon=True)
        self.server_thread.start()
        ready = self.server_ready.wait(timeout=3)
        if not ready or self.server_error is not None:
            if not ready:
                self.server_stop.set()
                self.server_thread.join(timeout=3)
            self.server_owned = False
            detail = str(self.server_error or "Tempo limite ao abrir a porta TCP.")
            LOG.error("Não foi possível iniciar o servidor: %s", detail)
            self._notify("Servidor não iniciado", detail)
            return
        self.server_owned = True
        LOG.info("Servidor iniciado em %s:%s", DEFAULT_HOST, DEFAULT_PORT)
        if self.icon is not None:
            self.icon.update_menu()

    def _stop_server(self):
        if not self.server_owned:
            return
        self.server_stop.set()
        if self.server_thread is not None:
            self.server_thread.join(timeout=3)
        self.server_owned = False
        if self.icon is not None:
            self.icon.update_menu()

    def _toggle_server(self, _icon, _item):
        if self.external_server:
            return
        if self.server_owned:
            self._stop_server()
        else:
            self._start_server()

    def _notify(self, title: str, body: str):
        if self.icon is None or not self.icon.HAS_NOTIFICATION:
            LOG.warning("Notificação indisponível: %s — %s", title, body)
            return
        try:
            self.icon.notify(body, title=title)
        except (OSError, NotImplementedError):
            LOG.exception("Falha ao exibir notificação do Windows")

    def _set_latest_pdf(self, path: Path):
        self.latest_pdf = path
        if self.icon is not None:
            self.icon.update_menu()

    def _handle_metadata(self, metadata_path: Path):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            LOG.exception("Não foi possível ler os metadados de %s", metadata_path)
            return
        if not isinstance(metadata, dict):
            LOG.warning("Metadados inválidos em %s", metadata_path)
            return

        receipt_id = str(metadata.get("receipt_id") or metadata_path.stem)
        if metadata.get("result") != "ok":
            self._notify("Falha na impressão", str(metadata.get("render_error") or receipt_id))
            return
        pdf_name = metadata.get("pdf_file")
        if not isinstance(pdf_name, str) or Path(pdf_name).name != pdf_name:
            LOG.warning("Nome de PDF inválido em %s", metadata_path)
            return
        pdf_path = self.output_dir / pdf_name
        if not pdf_path.is_file():
            LOG.warning("PDF não encontrado para %s", receipt_id)
            return
        self._set_latest_pdf(pdf_path)
        self._notify("Impressão recebida", "O PDF está pronto. Abra ‘Abrir PDF mais recente’ na bandeja.")

    def _watch_output(self):
        while not self.stop_event.wait(0.8):
            try:
                entries = list(self.output_dir.iterdir())
            except OSError:
                LOG.exception("Não foi possível acessar %s", self.output_dir)
                continue

            for path in entries:
                if path.is_file() and RECEIPT_RE.fullmatch(path.name) and path.name not in self.seen_metadata:
                    self.seen_metadata.add(path.name)
                    self._handle_metadata(path)
                elif path.is_file() and path.suffix.lower() == ".pdf" and "_cupom_" not in path.name:
                    key = str(path)
                    if key not in self.seen_direct_pdfs and key not in self.pending_pdfs:
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        self.pending_pdfs[key] = ((stat.st_size, stat.st_mtime_ns), 0)

            for key, (previous, stable_count) in list(self.pending_pdfs.items()):
                path = Path(key)
                try:
                    stat = path.stat()
                except OSError:
                    self.pending_pdfs.pop(key, None)
                    continue
                current = (stat.st_size, stat.st_mtime_ns)
                stable_count = stable_count + 1 if current == previous and stat.st_size > 0 else 0
                if stable_count >= 2:
                    self.pending_pdfs.pop(key, None)
                    self.seen_direct_pdfs.add(key)
                    self._set_latest_pdf(path)
                    self._notify(
                        "Impressão recebida",
                        "O PDF está pronto. Abra ‘Abrir PDF mais recente’ na bandeja.",
                    )
                else:
                    self.pending_pdfs[key] = (current, stable_count)

    def _open_latest(self, _icon, _item):
        path = self.latest_pdf
        if path is not None:
            self._open_pdf(path)

    def _open_pdf(self, path: Path):
        if not path.is_file():
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError:
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

    def _show_history(self, _icon, _item):
        threading.Thread(
            target=self._show_history_window,
            name="posvirtual-pdf-history",
            daemon=True,
        ).start()

    def _show_history_window(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            LOG.exception("Tk não está disponível para mostrar o histórico de PDFs")
            self._notify("Histórico indisponível", "Não foi possível abrir a janela do histórico.")
            return

        try:
            root = tk.Tk()
            root.title("Histórico de PDFs — POSvirtual")
            root.geometry("760x440")
            root.minsize(600, 320)

            frame = ttk.Frame(root, padding=12)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            history = self._pdf_history()
            if not history:
                ttk.Label(frame, text="Nenhum PDF foi gerado nesta pasta.").grid(
                    row=0, column=0, sticky="w"
                )
                ttk.Button(frame, text="Fechar", command=root.destroy).grid(
                    row=1, column=0, sticky="e", pady=(10, 0)
                )
            else:
                tree = ttk.Treeview(frame, columns=("date", "file"), show="headings", selectmode="browse")
                tree.heading("date", text="Data e hora")
                tree.heading("file", text="Arquivo PDF")
                tree.column("date", width=160, stretch=False)
                tree.column("file", width=520, stretch=True)
                scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
                tree.configure(yscrollcommand=scrollbar.set)
                tree.grid(row=0, column=0, sticky="nsew")
                scrollbar.grid(row=0, column=1, sticky="ns")

                path_by_item = {}
                for index, (modified, path) in enumerate(history):
                    item = tree.insert(
                        "", "end", iid=f"pdf-{index}",
                        values=(datetime.fromtimestamp(modified).strftime("%d/%m/%Y %H:%M:%S"), path.name),
                    )
                    path_by_item[item] = path
                tree.selection_set("pdf-0")

                def open_selected(_event=None):
                    selected = tree.selection()
                    if selected:
                        self._open_pdf(path_by_item[selected[0]])

                tree.bind("<Double-1>", open_selected)
                buttons = ttk.Frame(frame)
                buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
                ttk.Button(buttons, text="Abrir selecionado", command=open_selected).pack(side="left")
                ttk.Button(buttons, text="Fechar", command=root.destroy).pack(side="right")

            root.lift()
            root.mainloop()
        except Exception:
            LOG.exception("Não foi possível abrir a janela do histórico")
            self._notify("Histórico indisponível", "Não foi possível abrir a janela do histórico.")

    @staticmethod
    def _show_about(_icon, _item):
        message = (
            f"{APP_NAME} {__version__}\n"
            f"{APP_DESCRIPTION}\n\n"
            f"Propriedade: {APP_OWNER}\n"
            "Suporte: www.taskblu.com\n"
            f"{APP_COPYRIGHT}"
        )
        ctypes.windll.user32.MessageBoxW(None, message, f"Sobre {APP_NAME}", 0x40)

    @staticmethod
    def _open_support(_icon, _item):
        webbrowser.open(APP_SUPPORT_URL)

    def _quit(self, icon, _item):
        self.stop_event.set()
        self._stop_server()
        icon.stop()

    def run(self):
        log_path = self.output_dir.parent / "logs" / "tray-agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_path,
            encoding="utf-8",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        self.icon = pystray.Icon(
            "com.taskblu.posvirtual",
            icon=_icon_image(),
            title="POSvirtual — Taskblu",
            menu=self._menu(),
        )
        watcher = threading.Thread(target=self._watch_output, name="posvirtual-output-watch", daemon=True)

        def setup(icon):
            icon.visible = True
            self._start_server()
            watcher.start()

        try:
            self.icon.run(setup=setup)
        finally:
            self.stop_event.set()
            if watcher.is_alive():
                watcher.join(timeout=2)
            self._stop_server()
