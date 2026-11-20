"""Geração de PDF de bobina térmica 80/58mm via rasterização a 203,2 DPI.

PDF corresponde ao aspecto visual de cupom, não garante extração de texto.
"""
from __future__ import annotations
from math import ceil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import qrcode
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.shapes import Rect, String
from .escpos import Receipt, Block

DPI = 203.2
FONT_PATH = Path(__file__).with_name("assets") / "DejaVuSansMono.ttf"


def font_for(block: Block):
    size = (20 if not block.style.font else 16) * min(block.style.sy, 4)
    return ImageFont.truetype(str(FONT_PATH), size=size)


def _wrap(text: str, font, maxwidth: int, draw, sx=1):
    # quebra em caracteres para preservar alinhamento em recibos monoespaçados
    if not text: return [""]
    result = []
    for original in text.split("\n"):
        current = ""
        for c in original:
            probe = current + c
            if current and draw.textlength(probe, font=font) * sx > maxwidth:
                result.append(current)
                current = c
            else:
                current = probe
        result.append(current)
    return result


def _barcode(block: Block, printable_width: int):
    # ReportLab codifica os símbolos e os dígitos verificadores. Pillow rasteriza
    # as formas usando a mesma fonte empacotada que o restante do cupom.
    kind = "Standard39" if block.barcode_type == "Code39" else block.barcode_type
    drawing = createBarcodeDrawing(
        kind, value=block.text,
        barHeight=max(20, block.barcode_height) / 2.0,
        humanReadable=True, barWidth=max(0.5, block.barcode_width * .45),
    ).expandUserNodes()
    scale = min(2, printable_width / drawing.width)
    width = min(printable_width, ceil(drawing.width * scale))
    height = ceil(drawing.height * scale)
    image = Image.new("RGB", (width, height), "white")
    painter = ImageDraw.Draw(image)
    offset_x, offset_y = drawing.transform[4:6]
    group, = drawing.getContents()
    for element in group.getContents():
        x = (element.x + offset_x) * scale
        y = height - (element.y + offset_y) * scale
        if isinstance(element, Rect):
            if element.fillColor is not None:
                left, right = round(x), round(x + element.width * scale)
                top, bottom = round(y - element.height * scale), round(y)
                if right > left and bottom > top:
                    painter.rectangle((left, top, right - 1, bottom - 1), fill="black")
        elif isinstance(element, String):
            anchor = {"start": "ls", "middle": "ms", "end": "rs"}[element.textAnchor]
            font = ImageFont.truetype(str(FONT_PATH), size=max(1, round(element.fontSize * scale)))
            painter.text((x, y), element.text, fill="black", font=font, anchor=anchor)
        else:
            raise ValueError(f"Forma inesperada no código de barras: {type(element).__name__}")
    return image


def render_receipt(receipt: Receipt, path: Path, paper_mm: int = 80) -> tuple[int, int]:
    if paper_mm not in (58, 80): raise ValueError("paper_mm deve ser 58 ou 80")
    paper_width = int(round(paper_mm / 25.4 * DPI))
    printable = int(round((72 if paper_mm == 80 else 48) / 25.4 * DPI))
    margin = (paper_width - printable) // 2
    # Criar faixas individuais facilita gerenciamento da altura dinâmica.
    strips = []
    for block in receipt.blocks:
        if block.kind == "feed":
            strips.append(Image.new("RGB", (paper_width, max(1, min(block.count, 150)*27)), "white"))
            continue
        if block.kind == "raster" and block.image is not None:
            im = block.image.convert("RGB")
            if im.width > printable:
                scale = printable / im.width
                im = im.resize((printable, max(1, round(im.height * scale))), Image.Resampling.NEAREST)
            height = im.height + 6
            strip = Image.new("RGB", (paper_width, height), "white")
            x = margin + (printable - im.width)//2 if block.style.align == 1 else margin + (printable - im.width if block.style.align == 2 else 0)
            strip.paste(im, (x, 2))
            strips.append(strip)
            continue
        if block.kind == "qr":
            qr = qrcode.QRCode(border=2, box_size=5, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(block.text)
            qr.make(fit=True)
            im = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            if im.width > printable: im.thumbnail((printable, printable))
            strip = Image.new("RGB", (paper_width, im.height+8), "white")
            x = margin + (printable-im.width)//2 if block.style.align == 1 else margin
            if block.style.align == 2: x = margin+printable-im.width
            strip.paste(im, (x,4))
            strips.append(strip)
            continue
        if block.kind == "barcode":
            im = _barcode(block, printable)
            strip = Image.new("RGB", (paper_width, im.height+6), "white")
            x = margin + ((printable-im.width)//2 if block.style.align == 1 else (printable-im.width if block.style.align == 2 else 0))
            strip.paste(im, (x,2))
            strips.append(strip)
            continue
        if block.kind != "text": continue
        f = font_for(block)
        sx = min(block.style.sx, 4)
        sample = Image.new("RGB", (paper_width, 30), "white")
        measure = ImageDraw.Draw(sample)
        lines = _wrap(block.text, f, printable, measure, sx=sx)
        hline = max(26, round(f.size * 1.35))
        strip = Image.new("RGB", (paper_width, hline*len(lines)), "white")
        d = ImageDraw.Draw(strip)
        for j, line in enumerate(lines):
            if sx == 1:
                width = d.textlength(line, font=f)
                x = margin + (int((printable-width)/2) if block.style.align == 1 else int(printable-width) if block.style.align == 2 else 0)
                d.text((max(margin,x), j*hline), line, font=f, fill="black",
                       stroke_width=1 if block.style.bold else 0, stroke_fill="black")
                if block.style.underline:
                    d.line((x,j*hline+hline-3,x+width,j*hline+hline-3), fill="black", width=1)
            else:
                w = max(1, int(d.textlength(line, font=f)+4))
                src = Image.new("RGB", (w,hline), "white")
                sd = ImageDraw.Draw(src)
                sd.text((0,0),line,font=f, fill="black",stroke_width=1 if block.style.bold else 0)
                stretched = src.resize((w*sx,hline), Image.Resampling.NEAREST)
                x = margin + ((printable-stretched.width)//2 if block.style.align == 1 else printable-stretched.width if block.style.align == 2 else 0)
                strip.paste(stretched,(max(margin,x),j*hline))
        strips.append(strip)
    total_height = 12 + sum(x.height for x in strips)
    if total_height > 20000:
        raise ValueError("recibo muito longo para o renderizador MVP (20.000 pixels)")
    result = Image.new("RGB", (paper_width, max(30,total_height)), "white")
    y = 6
    for strip in strips:
        result.paste(strip, (0,y))
        y += strip.height
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(".pdf.tmp")
    try:
        result.save(temp, format="PDF", resolution=DPI)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return result.size
