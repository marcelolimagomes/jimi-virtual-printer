import asyncio
import json
from posvirtual.server import PrinterServer


def test_servidor_tcp_gera_pdf_e_status(tmp_path):
    async def scenario():
        printer=PrinterServer(tmp_path)
        server=await asyncio.start_server(printer.handle,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        first = b'\x10\x04\x01Teste TCP\n\x1d\x56\x00'
        writer.write(first)
        await writer.drain()
        status=await asyncio.wait_for(reader.readexactly(1),timeout=3)
        assert status == b'\x12'
        async def first_receipt():
            while not (paths := list(tmp_path.glob('*_cupom_001.json'))):
                await asyncio.sleep(0.01)
            return json.loads(paths[0].read_text())

        saved = await asyncio.wait_for(first_receipt(), timeout=3)
        assert saved['result'] == 'ok'
        assert (tmp_path / saved['raw_file']).read_bytes() == first
        assert (tmp_path / saved['pdf_file']).read_bytes().startswith(b'%PDF')

        second = b'Sem corte\n'
        writer.write(second)
        await writer.drain()
        writer.write_eof()
        assert await asyncio.wait_for(reader.read(), timeout=3) == b''
        writer.close()
        await writer.wait_closed()
        server.close(); await server.wait_closed()
        assert (tmp_path / saved['raw_file']).read_bytes() == first + second
    asyncio.run(scenario())
    assert len(list(tmp_path.glob('*.pdf')))==2
    assert len(list(tmp_path.glob('*.json')))==2
    assert len(list(tmp_path.glob('*.bin')))==1
    assert all(json.loads(path.read_text())['result']=='ok' for path in tmp_path.glob('*.json'))
