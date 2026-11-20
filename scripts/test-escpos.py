#!/usr/bin/env python3
"""Envia dois cupons na mesma conexao (delimitados por GS V)."""
import argparse
import socket

parser = argparse.ArgumentParser()
parser.add_argument('--host',default='127.0.0.1')
parser.add_argument('--port',type=int,default=9100)
args = parser.parse_args()

def qr(data: bytes):
    size = len(data)+3
    return b'\x1d\x28\x6b' + bytes([size & 0xff,size>>8]) + b'\x31\x50\x30' + data + b'\x1d\x28\x6b\x03\x00\x31\x51\x30'

job = (b'\x1b\x40\x1b\x61\x01\x1b\x45\x01TESTE POStech VIRTUAL\n'
       b'\x1b\x45\x00\x1b\x61\x00Pedido: #0001\nProduto        QTD    Total\n'
       b'Cafe             2    12.00\nBolo             1    15.50\n'
       b'-------------------------\n\x1b\x45\x01TOTAL: R$ 27,50\n\x1b\x45\x00'
       + qr(b'https://example.org/pedido/0001') + b'\n\x1d\x56\x00'
       + b'\x1b\x40\x1b\x61\x01SEGUNDO CUPOM\n\x1b\x61\x00Mesa: 05\n\x1d\x56\x00')
with socket.create_connection((args.host,args.port),timeout=5) as s:
    s.sendall(job)
print('ESC/POS enviado: 2 cupons')
