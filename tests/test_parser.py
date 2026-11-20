import socket
import pytest
from pathlib import Path
from posvirtual.escpos import EscPosParser, Block, Style
from posvirtual.render import font_for, render_receipt


def test_divide_por_corte_e_fecha_resto(tmp_path):
    p = EscPosParser()
    assert not p.feed(b"\x1b\x40ABC\n\x1d")
    receipts=p.feed(b"\x56\x00SEGUNDO\n")
    assert len(receipts)==1
    assert receipts[0].blocks[0].text=="ABC"
    tail=p.finish()
    assert tail.blocks[0].text=="SEGUNDO"
    out=tmp_path/'teste.pdf'
    dims=render_receipt(receipts[0],out)
    assert dims[0] == 640
    assert out.read_bytes().startswith(b"%PDF")


def test_status_online_escpos():
    p=EscPosParser()
    assert not p.feed(b"\x10\x04")
    assert not p.feed(b"\x04")
    assert p.status_replies==[b"\x12"]
    assert p.finish() is None


def test_qr_e_raster_parciais(tmp_path):
    p=EscPosParser()
    data=b"https://test.local"
    n=len(data)+3
    receipt=(b"inicio\n" + b"\x1d\x28\x6b" + bytes([n,0]) + b"\x31\x50\x30" + data
             + b"\x1d\x28\x6b\x03\x00\x31\x51\x30"
             + b"\x1d\x76\x30\x00\x01\x00\x02\x00\xff\x81" + b"\x1d\x56\x00")
    jobs=[]
    for b in receipt:
        jobs += p.feed(bytes([b]))
    assert len(jobs)==1
    assert [x.kind for x in jobs[0].blocks] == ["text","qr","raster"]
    width,height = render_receipt(jobs[0], tmp_path/'qr.pdf')
    assert width==640 and height>100


def test_58mm(tmp_path):
    p=EscPosParser(); p.feed(b"Cupom 58mm\n")
    out=tmp_path/'58.pdf'; width,_=render_receipt(p.finish(),out,58)
    assert width==464


def test_limite_de_raster():
    p=EscPosParser()
    with pytest.raises(ValueError):
        p.feed(b"\x1d\x76\x30\x00\xff\xff\xff\xff")


def test_preserva_corte_antes_de_comando_invalido():
    p = EscPosParser()
    events = p.iter_receipts(b"PRIMEIRO\n\x1d\x56\x00\x1d\x76\x30\x00\xff\xff\xff\xff")
    assert next(events).blocks[0].text == "PRIMEIRO"
    with pytest.raises(ValueError, match="raster muito grande"):
        next(events)
    assert p.finish() is None


def test_fonte_empacotada_monospacada():
    font = font_for(Block("text", Style(), text="Impressão"))
    assert font.getname() == ("DejaVu Sans Mono", "Book")
    assert font.getlength("áéç") == font.getlength("123")


def test_renderiza_code128(tmp_path):
    parser = EscPosParser()
    receipt, = parser.feed(b"\x1dkI\x0812345678\x1d\x56\x00")
    assert receipt.blocks[0].barcode_type == "Code128"
    pdf = tmp_path / "code128.pdf"
    assert render_receipt(receipt, pdf)[0] == 640
    assert pdf.read_bytes().startswith(b"%PDF")
