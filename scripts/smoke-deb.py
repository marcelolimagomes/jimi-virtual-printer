#!/usr/bin/env python3
"""Exercise the installed package, retaining only synthetic print evidence."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep


def wait_for(read, description):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        result = read()
        if result:
            return result
        sleep(0.05)
    raise RuntimeError(f"Timeout: {description}")


def read_receipt(output, number):
    path, = wait_for(
        lambda: list(output.glob(f"*_cupom_{number:03d}.json")), f"receipt {number}"
    )
    job = json.loads(path.read_text())
    assert job["result"] == "ok", job
    assert job["paper_mm"] == 80 and job["pixels"]["width"] == 640, job
    assert job["connection_error"] is None, job
    assert (output / job["pdf_file"]).read_bytes().startswith(b"%PDF"), job
    return job


def smoke(output):
    output.mkdir(mode=0o700, parents=True)
    log = output / "server.log"
    with log.open("wb") as stream, subprocess.Popen(
        ["/usr/bin/posvirtual", "--host", "127.0.0.1", "--port", "0", "--output", str(output)],
        stdout=stream, stderr=subprocess.STDOUT,
    ) as printer:
        try:
            ready = wait_for(
                lambda: re.search(r"Emulador ESC/POS em 127\.0\.0\.1:(\d+)", log.read_text()),
                "TCP listener",
            )
            first = b"\x10\x04\x01Teste JimiFood\n\x1dkI\x0812345678\x1d\x56\x00"
            second = b"Segundo corte\n\x1d\x56\x00"
            tail = b"Ultimo cupom sem corte\n"
            with socket.create_connection(("127.0.0.1", int(ready[1])), timeout=10) as client:
                client.sendall(first)
                assert client.recv(1) == b"\x12"
                first_job = read_receipt(output, 1)
                raw = output / first_job["raw_file"]
                assert raw.read_bytes() == first

                client.sendall(second)
                second_job = read_receipt(output, 2)
                assert raw.read_bytes() == first + second
                client.sendall(tail)
                client.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b""
            third_job = read_receipt(output, 3)
            assert all(job["raw_file"] == raw.name for job in (second_job, third_job))
            assert raw.read_bytes() == first + second + tail
            assert len(list(output.glob("*.bin"))) == 1
            assert len(list(output.glob("*.pdf"))) == len(list(output.glob("*.json"))) == 3
            with TemporaryDirectory(prefix="posvirtual-smoke-") as directory:
                prefix = Path(directory) / "code128"
                subprocess.run(
                    ["pdftoppm", "-singlefile", "-r", "203.2", "-png",
                     str(output / first_job["pdf_file"]), str(prefix)],
                    check=True,
                )
                data = subprocess.check_output(
                    ["zbarimg", "--quiet", "--raw", str(prefix.with_suffix(".png"))]
                )
                assert data.strip() == b"12345678", data
            print("PASS: 3 PDFs de 80 mm, cortes publicados com TCP aberto, RAW íntegro e Code 128 legível.")
        finally:
            printer.terminate()
            try:
                printer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                printer.kill()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Uso: {sys.argv[0]} <novo-diretório-de-evidências>")
    os.umask(0o077)
    smoke(Path(sys.argv[1]).resolve())
