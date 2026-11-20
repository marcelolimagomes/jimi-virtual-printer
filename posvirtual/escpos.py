"""Parser ESC/POS incremental, limitado e intencionalmente explícito.

Contrato: feed(chunk) retorna cupons encerrados por corte (GS V).
finish() devolve cupom pendente no fim da conexão. Alguns comandos de fabricante
não são interpretados. O fluxo binário original deve ser salvo pelo chamador.
"""
from dataclasses import dataclass, field, replace
from collections.abc import Iterator
from typing import Optional
from PIL import Image

MAX_RASTER_BYTES = 4 * 1024 * 1024
MAX_BUFFER_BYTES = 5 * 1024 * 1024
MAX_LINES = 3000

CODEPAGES = {0: "cp437", 2: "cp850", 3: "cp860", 16: "cp1252", 17: "cp866", 18: "cp852", 19: "cp858"}


@dataclass(frozen=True)
class Style:
    align: int = 0
    bold: bool = False
    underline: bool = False
    font: int = 0
    sx: int = 1
    sy: int = 1
    codepage: str = "cp437"


@dataclass
class Block:
    kind: str  # text | raster | qr | barcode | feed
    style: Style
    text: str = ""
    image: Optional[Image.Image] = None
    count: int = 0
    barcode_type: str = "Code128"
    barcode_height: int = 70
    barcode_width: int = 2


@dataclass
class Receipt:
    blocks: list[Block] = field(default_factory=list)


class EscPosParser:
    def __init__(self):
        self.pending = bytearray()
        self.line = bytearray()
        self.blocks: list[Block] = []
        self.style = Style()
        self.qr_data: bytes = b""
        self.barcode_height = 70
        self.barcode_width = 2
        self._count = 0
        self.unknown_commands: set[str] = set()
        self.status_replies: list[bytes] = []

    def _push(self, block: Block):
        self._count += 1
        if self._count > MAX_LINES:
            raise ValueError("limite de blocos ESC/POS ultrapassado")
        self.blocks.append(block)

    def _flush_line(self, force=False):
        if self.line or force:
            text = self.line.decode(self.style.codepage, errors="replace")
            self._push(Block("text", self.style, text=text))
            self.line.clear()

    def _style(self, **changes):
        if self.line:
            self._flush_line()
        self.style = replace(self.style, **changes)

    def _receipt(self):
        self._flush_line()
        if not self.blocks:
            return None
        receipt = Receipt(self.blocks)
        self.blocks = []
        self._count = 0
        return receipt

    @staticmethod
    def _raster_to_image(data: bytes, byte_width: int, height: int):
        # ESC/POS: 1=preto; PIL mode 1: 0=preto -> inverter bits.
        pixels = Image.new("1", (byte_width * 8, height), 1)
        out = bytearray()
        for b in data:
            out.append(b ^ 0xFF)
        return Image.frombytes("1", pixels.size, bytes(out), "raw", "1")

    def feed(self, chunk: bytes) -> list[Receipt]:
        return list(self.iter_receipts(chunk))

    def iter_receipts(self, chunk: bytes) -> Iterator[Receipt]:
        """Entrega cortes completos mesmo quando um comando posterior falha."""
        self.pending.extend(chunk)
        if len(self.pending) > MAX_BUFFER_BYTES:
            raise ValueError("buffer ESC/POS acima do limite")
        i = 0
        p = self.pending
        while i < len(p):
            b = p[i]
            n = len(p) - i
            if b == 0x0A:
                self._flush_line(force=True)
                i += 1
            elif b == 0x0D:
                i += 1
            elif b == 0x09:
                self.line.extend(b"    ")
                i += 1
            elif b == 0x10:
                if n < 3: break
                if p[i+1] == 0x04:
                    if 1 <= p[i+2] <= 4:
                        self.status_replies.append(b"\x12")  # impressora online, papel OK
                    i += 3
                else:
                    self.unknown_commands.add("DLE non-EOT")
                    i += 1
            elif b == 0x1B:
                if n < 2: break
                op = p[i+1]
                if op == 0x40:  # ESC @ resetar formatação
                    self._flush_line()
                    self.style = Style()
                    i += 2
                elif op in (0x61, 0x45, 0x2D, 0x4D, 0x74, 0x64, 0x21, 0x4A, 0x70):
                    needed = 5 if op == 0x70 else 3
                    if n < needed: break
                    x = p[i+2]
                    if op == 0x61: self._style(align=min(x, 2))
                    elif op == 0x45: self._style(bold=bool(x & 1))
                    elif op == 0x2D: self._style(underline=bool(x))
                    elif op == 0x4D: self._style(font=x & 1)
                    elif op == 0x74: self._style(codepage=CODEPAGES.get(x, self.style.codepage))
                    elif op == 0x64:
                        self._flush_line()
                        self._push(Block("feed", self.style, count=x))
                    elif op == 0x21: self._style(bold=bool(x & 8), font=bool(x & 1), sx=2 if x & 0x20 else 1, sy=2 if x & 0x10 else 1)
                    elif op == 0x4A:
                        self._flush_line()
                        self._push(Block("feed", self.style, count=max(1, x // 24)))
                    # ESC p: pulso da gaveta; sem efeito físico
                    i += needed
                elif op == 0x2A:  # ESC * modo de imagem em colunas (não implementado)
                    if n < 5: break
                    m, xL, xH = p[i+2:i+5]
                    num = xL + 256*xH
                    data_size = num * (3 if m in (32, 33) else 1)
                    if n < 5+data_size: break
                    self.unknown_commands.add("ESC * raster column ignored")
                    i += 5+data_size
                else:
                    self.unknown_commands.add(f"ESC 0x{op:02X} (parametros desconhecidos)")
                    i += 2  # extensões de fabricante devem ser implementadas explicitamente
            elif b == 0x1D:
                if n < 2: break
                op = p[i+1]
                if op in (0x21, 0x68, 0x77, 0x48, 0x66, 0x61, 0x72):
                    if n < 3: break
                    x = p[i+2]
                    if op == 0x21: self._style(sx=(x & 15)+1, sy=((x>>4)&15)+1)
                    elif op == 0x68: self.barcode_height = max(16, x)
                    elif op == 0x77: self.barcode_width = max(1, x)
                    elif op == 0x72: self.status_replies.append(b"\x00")
                    i += 3
                elif op == 0x56:  # GS V: corte -> finaliza cupom
                    if n < 3: break
                    mode = p[i+2]
                    needed = 4 if mode in (65, 66) else 3
                    if n < needed: break
                    receipt = self._receipt()
                    i += needed
                    if receipt:
                        yield receipt
                elif op == 0x76:  # GS v 0 m xL xH yL yH DATA
                    if n < 8: break
                    if p[i+2] != 0x30:
                        self.unknown_commands.add("GS v variant unsupported")
                        i += 3
                        continue
                    width_bytes = p[i+4] + p[i+5]*256
                    height = p[i+6] + p[i+7]*256
                    size = width_bytes * height
                    if size > MAX_RASTER_BYTES: raise ValueError("raster muito grande")
                    if n < 8+size: break
                    self._flush_line()
                    if size:
                        im = self._raster_to_image(bytes(p[i+8:i+8+size]), width_bytes, height)
                        self._push(Block("raster", self.style, image=im))
                    i += 8+size
                elif op == 0x28:  # GS ( k: QR codes
                    if n < 5: break
                    size = p[i+3] + p[i+4]*256
                    if size > MAX_RASTER_BYTES: raise ValueError("GS ( k muito grande")
                    if n < 5+size: break
                    cmd = bytes(p[i+5:i+5+size])
                    if op == 0x28 and p[i+2] == 0x6B:
                        if cmd[:3] == b"\x31\x50\x30": self.qr_data = cmd[3:]
                        elif cmd[:3] == b"\x31\x51\x30" and self.qr_data:
                            self._flush_line()
                            self._push(Block("qr", self.style, text=self.qr_data.decode("utf-8", errors="replace")))
                        elif cmd[:2] not in (b"\x31\x41", b"\x31\x43", b"\x31\x45"):
                            self.unknown_commands.add("GS ( k function unsupported")
                    i += 5+size
                elif op == 0x6B:  # GS k m ...: codigos barras
                    if n < 3: break
                    typ = p[i+2]
                    if typ >= 65:
                        if n < 4: break
                        size = p[i+3]
                        if n < 4+size: break
                        data = bytes(p[i+4:i+4+size]); i += 4+size
                    else:
                        end = p.find(0x00, i+3)
                        if end < 0: break
                        data = bytes(p[i+3:end]); i = end+1
                    self._flush_line()
                    typname = {67:"EAN13", 68:"EAN8", 73:"Code128", 69:"Code39", 70:"I2of5"}.get(typ, "Code128")
                    self._push(Block("barcode", self.style, text=data.decode("latin1"), barcode_type=typname, barcode_height=self.barcode_height, barcode_width=self.barcode_width))
                elif op == 0x49:  # GS I n: identificação simplificada
                    if n < 3: break
                    self.status_replies.append(b"POS200C\x00")
                    i += 3
                else:
                    self.unknown_commands.add(f"GS 0x{op:02X} (parametros desconhecidos)")
                    i += 2
            elif b < 0x20:
                # Comandos ASCII de controle não reconhecidos
                self.unknown_commands.add(f"CTRL 0x{b:02X}")
                i += 1
            else:
                self.line.append(b)
                i += 1
        if i:
            del p[:i]

    def finish(self) -> Optional[Receipt]:
        # Bytes finais incompletos sao descartados, mas persistidos no arquivo .bin
        self.pending.clear()
        return self._receipt()
