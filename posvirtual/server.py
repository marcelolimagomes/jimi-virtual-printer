"""Servidor TCP/9100, um cupom por corte GS V ou por fechamento de conexão."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import uuid
from . import APP_NAME, APP_WEBSITE, __version__
from .escpos import EscPosParser, Receipt
from .paths import default_output_dir
from .render import render_receipt

LOG = logging.getLogger("posvirtual")


def _open_new(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "wb")


def _write_metadata(path: Path, data: dict):
    temp = path.with_suffix(".json.tmp")
    output = _open_new(temp)
    try:
        with output:
            output.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class PrinterServer:
    def __init__(self, output_dir: Path, paper_mm: int = 80, max_bytes: int = 8_000_000):
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.paper_mm = paper_mm
        self.max_bytes = max_bytes
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        cid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
        peer = writer.get_extra_info("peername")
        parser = EscPosParser()
        raw_path = self.output_dir / f"{cid}.bin"
        raw = None
        total_bytes = receipt_number = 0
        failure = None
        try:
            try:
                while chunk := await asyncio.wait_for(reader.read(65536), timeout=20):
                    total_bytes += len(chunk)
                    if total_bytes > self.max_bytes:
                        raise ValueError(f"conexão excedeu {self.max_bytes} bytes")
                    if raw is None:
                        raw = _open_new(raw_path)
                    raw.write(chunk)
                    raw.flush()
                    completed = []
                    try:
                        for receipt in parser.iter_receipts(chunk):
                            completed.append((receipt, sorted(parser.unknown_commands)))
                        if parser.status_replies:
                            writer.writelines(parser.status_replies)
                            await writer.drain()
                            parser.status_replies.clear()
                    finally:
                        for receipt, unknown in completed:
                            receipt_number += 1
                            await self._save_receipt(cid, peer, receipt_number, receipt, unknown)
            except asyncio.TimeoutError:
                LOG.warning("Timeout de conexão %s", cid)
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                LOG.exception("Falha no fluxo %s", cid)

            try:
                tail = parser.finish()
                if tail:
                    await self._save_receipt(
                        cid, peer, receipt_number + 1, tail, sorted(parser.unknown_commands), failure
                    )
            except Exception as exc:
                failure = failure or f"{type(exc).__name__}: {exc}"
                LOG.exception("Falha ao finalizar %s", cid)
            if failure:
                _write_metadata(self.output_dir / f"{cid}_erro.json", {
                    "connection_error": failure, "raw_file": raw_path.name if raw is not None else None,
                })
        finally:
            try:
                if raw is not None:
                    raw.close()
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _save_receipt(
        self, cid: str, peer, number: int, receipt: Receipt, unknown_commands: list[str],
        connection_error: str | None = None,
    ):
        base = f"{cid}_cupom_{number:03d}"
        pdf_path = self.output_dir / f"{base}.pdf"
        meta = {
            "receipt_id": base,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "transport": "tcp-raw-escpos",
            "emulated_model": "POStech IRIS POS200C (subset)",
            "paper_mm": self.paper_mm,
            "connection_id": cid,
            "raw_file": f"{cid}.bin",
            "source": str(peer),
            "blocks": len(receipt.blocks),
            "unsupported_commands": unknown_commands,
            "connection_error": connection_error,
        }
        try:
            width, height = await asyncio.to_thread(render_receipt, receipt, pdf_path, self.paper_mm)
            meta.update(result="ok", pdf_file=pdf_path.name, pixels={"width": width, "height": height})
            LOG.info("PDF criado: %s", pdf_path)
        except Exception as exc:
            meta.update(result="error", render_error=f"{type(exc).__name__}: {exc}")
            LOG.exception("Falha ao renderizar %s", base)
        _write_metadata(self.output_dir / f"{base}.json", meta)

    async def serve(
        self,
        host: str,
        port: int,
        stop_event: threading.Event | None = None,
        started_event: threading.Event | None = None,
    ):
        server = await asyncio.start_server(self.handle, host, port)
        bound_port = server.sockets[0].getsockname()[1]
        LOG.info("Emulador ESC/POS em %s:%s, pasta: %s", host, bound_port, self.output_dir)
        if started_event is not None:
            started_event.set()
        async with server:
            if stop_event is None:
                await server.serve_forever()
            else:
                await asyncio.to_thread(stop_event.wait)


def main():
    parser = argparse.ArgumentParser(
        prog="POSvirtual",
        description=f"{APP_NAME} da Taskblu: impressora virtual ESC/POS com saída PDF.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} — {APP_WEBSITE}")
    parser.add_argument("--host",default=os.environ.get("POSVIRTUAL_HOST","127.0.0.1"))
    parser.add_argument("--port",type=int,default=int(os.environ.get("POSVIRTUAL_PORT","9100")))
    parser.add_argument("--paper-mm",type=int, choices=[58,80],default=int(os.environ.get("POSVIRTUAL_PAPER_MM","80")))
    parser.add_argument("--output",type=Path,default=default_output_dir())
    parser.add_argument("--max-bytes",type=int, default=8_000_000)
    parser.add_argument("--log-file",type=Path,help="gravar logs em arquivo (útil em execução sem console)")
    opts = parser.parse_args()
    log_format = "%(asctime)s %(levelname)s %(message)s"
    if opts.log_file:
        opts.log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=opts.log_file, encoding="utf-8", level=logging.INFO, format=log_format
        )
    else:
        logging.basicConfig(level=logging.INFO,format=log_format)
    asyncio.run(PrinterServer(opts.output,opts.paper_mm,opts.max_bytes).serve(opts.host,opts.port))

if __name__ == "__main__": main()
