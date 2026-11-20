# POS Virtual — protótipo de impressora térmica virtual Ubuntu/CI

**Versão:** 0.1.1 (prova de conceito)

**Perfil de referência:** POStech ÍRIS POS200C (não oficial, compatibilidade PARCIAL com ESC/POS).

**Licença:** código de demonstração, sem associação com a POStech.

## Objetivo e caminhos de impressão

Existem dois meios independentes de enviar uma impressão:

| Entrada | Como o aplicativo enxerga | Como vira PDF | Diretório |
|---|---|---|---|
| **CUPS 2.x / IPP** | Fila de sistema `POStech_Virtual`, aparece no diálogo de impressão / `lpstat`, acessível via IPP local | CUPS-PDF converte PDFs/PostScript/documentos | `~/PDF` do usuário do job (padrão do pacote) |
| **ESC/POS / TCP RAW** | Impressora de rede com IP e porta **9100**, ex.: `127.0.0.1:9100` | Interpretador de subset ESC/POS + renderizador Pillow para PDF | `POSVIRTUAL_OUTPUT` (`~/PDF` por padrão; `/prints` no Docker) |

**Importante:** as portas/interfaces são distintas. A fila CUPS-PDF não aceita automaticamente ESC/POS em formato bruto, e a porta TCP 9100 não interpreta PDF/PostScript. O nome da fila não faz com que o Linux crie um dispositivo USB com VID/PID POStech. Clientes exclusivamente USB exigem um módulo adicional de emulação USB gadget/USB/IP/driver.

## Requisitos

- Ubuntu 24.04/26.04, Debian 12+ ou Linux com Python 3.11+. A fonte DejaVu Sans Mono acompanha o motor.
- Para TCP: Python, Pillow, qrcode e reportlab.
- Para CUPS: `cups`, `cups-client`, `printer-driver-cups-pdf` (distribuição com CUPS 2.x/PPD clássico). Não usar sobre CUPS 3 sem adaptar a implementação.
- Para Docker: Docker Engine + Docker Compose.

## Modo 1: porta TCP 9100 em Ubuntu, sem sudo

```bash
sudo apt-get install -y python3-venv
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p "$HOME/PDF"
python -m posvirtual --host 127.0.0.1 --port 9100 --output "$HOME/PDF" --paper-mm 80
```

Segundo terminal:

```bash
python scripts/test-escpos.py
ls -lah "$HOME/PDF"/*.pdf
```

Configure a aplicação de origem como impressora de rede TCP/IP `127.0.0.1`, porta `9100`, linguagem **ESC/POS**, papel **80mm**, se essas opções existirem. Se o emissor estiver em outro host, use o IP do Ubuntu, vincule o servidor a `0.0.0.0` e proteja o acesso com firewall/VPN/rede isolada.

**O que se grava:** um `.pdf` e um `.json` por cupom, além do `.bin` original por conexão. Cada corte ESC/POS publica seu cupom com o socket ainda aberto. O RAW continua recebendo os bytes da conexão até seu fim. O encerramento salva o cupom restante, mesmo sem corte. Use o JSON como sinal de processamento do cupom e verifique `result` antes de consumir o PDF.

## Modo 2: criar impressora normal do Ubuntu (CUPS)

```bash
sudo bash scripts/install-cups.sh POStech_Virtual
lpstat -p POStech_Virtual -l
lpoptions -p POStech_Virtual -l
printf 'Impressao teste via CUPS\n' | lp -d POStech_Virtual
find "$HOME/PDF" -maxdepth 1 -type f -name '*.pdf' -ls
```

O instalador instala CUPS e CUPS-PDF, duplica o PPD da fila `PDF` padrão e cria `POStech_Virtual`, apontando para o backend `cups-pdf:/`. **Isto não instala um driver oficial POStech**. A fila é reconhecida pelo CUPS como impressora local normal, mas o conteúdo é processado pelo CUPS-PDF (não pelo parser ESC/POS).

Para verificar o destino e personalizar a saída da fila CUPS, inspecione `/etc/cups/cups-pdf.conf`, diretiva `Out`. Alterar a diretiva é **global** para filas CUPS-PDF, não apenas `POStech_Virtual`. Em Ubuntu, caminhos diferentes do padrão podem exigir autorização no perfil AppArmor de `cupsd` e revisão de permissões; evite desabilitar o AppArmor. O formato e tamanho do papel dependem do PPD, devendo ser validados via `lpoptions -p POStech_Virtual -l`. O fluxo CUPS-PDF padrão pode produzir páginas de tamanho fixo, não cupons de altura variável.

> Para simular fielmente bobinas de 80mm, use a entrada TCP ESC/POS do MVP; um segundo marco do projeto é implementar uma **Printer Application IPP** (PAPPL) e filtro específico, para receber arquivos do sistema e gerar páginas contínuas com a geometria de 80mm.

## Docker / CI/CD

### Pacote Debian e pipeline Woodpecker

O pacote `posvirtual_0.1.1-1_all.deb` instala o motor TCP, sua fonte e a unidade systemd. Em Debian 12, instale as dependências de build pela distribuição e gere o pacote e seu checksum:

```bash
sudo apt-get install build-essential debhelper dh-python dpkg-dev python3-pil python3-pytest python3-qrcode python3-reportlab
scripts/build-deb.sh
```

O workflow `.woodpecker.yml` roda testes, build Debian e smoke test do pacote instalado em eventos `push`, `pull_request` e `tag`. O workflow GitHub Actions `ci.yml` faz a mesma validação e deixa o `.deb` e o checksum disponíveis como artefato daquela execução; cupons RAW não são enviados.

Instale o pacote com `apt-get install ./posvirtual_0.1.1-1_all.deb`. Em hosts com systemd, o serviço escuta em `127.0.0.1:9100` e grava em `/var/lib/posvirtual`. Se já houver uma instância do protótipo usando a porta, libere a porta antes de iniciar o serviço do pacote. Para a fila gráfica CUPS, use o Modo 2.

### Publicar uma versão no GitHub

O número do release corresponde à versão Debian completa de `debian/changelog`. Para a versão atual, crie e envie a tag `v0.1.1-1`:

```bash
git tag v0.1.1-1
git push origin v0.1.1-1
```

O workflow `.github/workflows/release.yml` reconstrói e valida o pacote, depois publica `posvirtual_0.1.1-1_all.deb` e `posvirtual_0.1.1-1_all.deb.sha256` nos assets do GitHub Release. O pacote e o checksum podem ser baixados com:

```bash
gh release download v0.1.1-1 --pattern 'posvirtual_0.1.1-1_all.deb*'
sha256sum -c posvirtual_0.1.1-1_all.deb.sha256
```

Em um step ou container E2E, execute em primeiro plano e aponte o emissor para o endereço do processo. Use `127.0.0.1` para um emissor no mesmo container. Para containers distintos, use `--host 0.0.0.0` e o nome do serviço na rede privada da campanha.

```bash
posvirtual --host 127.0.0.1 --port 9100 --output "$PWD/artifacts/prints"
```

O workflow manual `.woodpecker/virtual-printer-deb.yml` do JimiFood recebe `POSVIRTUAL_DEB_SMOKE=1`, `POSVIRTUAL_DEB_URL` (URL HTTPS acessível ao agente) e `POSVIRTUAL_DEB_SHA256` (hexadecimal do artefato). Ele instala o pacote em `node:22-bookworm` e verifica os cortes com a conexão aberta, o RAW e a leitura de Code 128. Para repetir após instalar o pacote em um container:

```bash
apt-get install -y --no-install-recommends poppler-utils zbar-tools
python3 /usr/libexec/posvirtual/smoke-deb.py artifacts/posvirtual-print-smoke
```

### Docker Compose

```bash
mkdir -p artifacts
sudo chown 10001:10001 artifacts
docker compose up -d --build
python scripts/test-escpos.py
find ./artifacts -type f -maxdepth 1 -print
```

O compose expõe **somente no loopback** do host `127.0.0.1:9100`. A pasta `./artifacts` no host mapeia para `/prints` no container (UID 10001). Na primeira execução, pode ser necessário ajustar a propriedade da pasta para o UID 10001:

```bash
mkdir -p artifacts
sudo chown 10001:10001 artifacts
```

Os arquivos de impressão em `artifacts/` são evidência local e permanecem fora do Git e dos artefatos publicados.

**Teste rápido de qualidade:**

```bash
python -m pytest -q
```

## Comandos ESC/POS no protótipo

| Recurso | Suporte | Observação |
|---|---|---|
| `ESC @` | Sim | Reinicia estilo |
| Texto, `LF`, `CR`, `ESC a`, `ESC E`, `ESC !`, `GS !` | Parcial | Alinhamento, fonte A/B, negrito e tamanho; variações de fonte não pixel-perfect |
| `ESC t` | Parcial | CP437, CP850, CP860, CP1252 e algumas adicionais |
| `GS v 0` | Sim | Imagem raster básica; limites de segurança |
| `GS ( k` | Parcial | QR Code (modelo/armazenamento/impressão); outros 2D não |
| `GS k` | Parcial | Code128, EAN13/EAN8, Code39, ITF. Código inválido ou erro do backend de renderização gera `result: error` no JSON. |
| `GS V` | Sim | Corte se torna delimitação de cupom |
| `DLE EOT 1–4` | Parcial | Responde status `0x12` (online/papel disponível) |
| `GS I` | Parcial | Retorna identificação simplificada; não reproduz ID USB real |
| `ESC *` | **Não** | Captura no RAW; dados raster em colunas ignorados no PDF |
| `GS ( L`, ASB, comandos privados POStech | **Não** | Necessário identificar comandos efetivamente utilizados pelo PDV |
| USB virtual e conectores OPOS/JPOS | **Não** | Exigem transporte/protocolo especializado |

Limitações adicionais: o servidor não implementa descobrimento mDNS/Bonjour, suporte universal a autenticação IPP, impressão duplex, gaveta física, sensores reais, altura além de 20 mil pixels/cupom, nem convergência automática de dados de impressão CUPS/RAW em um único pipeline de renderização. O PDF ESC/POS é uma imagem raster e pode não permitir copiar texto. O arquivo RAW pode conter dados sensíveis e não deve ser publicado como artefato de CI sem mascaramento/restrição de acesso.

## Política de testes recomendada

1. **Unitários:** decodificação incremental de bytes, sequências partidas, corte, QR, imagem, status.
2. **Integração:** abrir socket TCP:9100, transmitir bytes, aguardar PDF+JSON+RAW; não verificar só o ACK do socket.
3. **Contrato:** comparar imagem rasterizada do PDF com snapshot de referência (golden image) e tolerância explícita de pixels.
4. **E2E:** iniciar o ERP/PDV com endereço de impressora da rede/container; imprimir venda, cancelamento, comprovante, pedido de cozinha, abertura/fechamento.
5. **Negativos:** erro de protocolo, impressão com job parcial, cupons múltiplos, perda de conexão, papel ausente simulado, muitos trabalhos simultâneos.
6. **CUPS:** executar `lpstat`, verificar nome/estado, envio por `lp`/IPP e PDF na pasta por usuário.

## Evolução proposta

**MVP (entregue):** servidor ESC/POS TCP + PDF/JSON/RAW, testes e scripts para fila CUPS-PDF.

**V1:** expansão ESC/POS com bitmap em colunas, QR completo, Data Matrix/PDF417, tabela de caracteres, comandos de fabricante, estados de sensores e testes visuais.

**V2:** serviço IPP Everywhere/Printer Application (PAPPL), atributos de fabricante e bobina dinâmica de 80mm, fila única que aceita formatos de documento e ESC/POS por rotas apropriadas.

**V3 (se necessário):** dispositivo serial PTY, emulação USB Gadget/USB/IP em host compatível, integração OPOS/JPOS, mDNS/DNS-SD e gestão de múltiplas impressoras (Balcão/Cozinha/Expedição).

## Referências

- POStech ÍRIS POS200C: https://www.postech.com.br/produto/46/impressora-iris-pos200c
- CUPS API: https://www.cups.org/doc/api-filter.html
- CUPS admin: https://www.cups.org/doc/admin.html
- CUPS-PDF: https://www.cups-pdf.de/documentation.shtml
- OpenPrinting e Printer Applications: https://openprinting.github.io/cups/drivers.html
- ESC/POS status: https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/dle_eot.html

## Executar automaticamente no Ubuntu com systemd --user

Se o diretório do projeto estiver em `~/posvirtual-prototype`, o serviço de exemplo poderá ser usado assim:

```bash
mkdir -p "$HOME/.config/systemd/user" "$HOME/PDF"
cp systemd/posvirtual.service.example "$HOME/.config/systemd/user/posvirtual.service"
systemctl --user daemon-reload
systemctl --user enable --now posvirtual
systemctl --user status posvirtual
journalctl --user -u posvirtual -f
```

Se instalar em outro diretório, adapte `WorkingDirectory` e `ExecStart`. O serviço `--user` depende de existir uma sessão de usuário (para iniciar mesmo sem login, o administrador pode habilitar *linger* com `loginctl enable-linger` para o usuário apropriado). Não use root e não exponha o serviço publicamente.

## Aplicativo dentro de containers

- Se emissor e impressora estiverem no **mesmo Compose**, aponte a aplicação para `posvirtual:9100` pelo DNS interno do Docker.
- Se emissor estiver no **host Ubuntu**, aponte para `127.0.0.1:9100` (porta publicada no Compose).
- Se emissor estiver em **outro container ou host**, não use `127.0.0.1` como se fosse o host da impressora; configure rede adequada e isolamento.

Em um futuro build PyInstaller para Windows, inclua `posvirtual/assets` no mesmo caminho do bundle e colete `reportlab.graphics.barcode`. O motor resolve a fonte relativa ao módulo.
