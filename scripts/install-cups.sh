#!/usr/bin/env bash
# Cria uma fila CUPS-PDF adicional, usando o PPD que o pacote instalou em PDF.
# Requer Ubuntu/Debian com CUPS 2.x e privilegios sudo.
set -euo pipefail
QUEUE="${1:-POStech_Virtual}"
if [[ ! "$QUEUE" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Nome da fila invalido: $QUEUE" >&2; exit 2
fi
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y cups cups-client printer-driver-cups-pdf
sudo systemctl start cups 2>/dev/null || sudo service cups start
if sudo test -r /etc/cups/ppd/PDF.ppd; then
  PPD=/etc/cups/ppd/PDF.ppd
else
  echo "Nao ha /etc/cups/ppd/PDF.ppd. Verifique lpstat -p e encontre o PPD CUPS-PDF." >&2
  exit 3
fi
# -P para criar fila independente; o output Out no cups-pdf.conf e GLOBAL.
sudo lpadmin -p "$QUEUE" -E -v 'cups-pdf:/' -P "$PPD" \
  -D 'POStech Virtual - PDF via CUPS (emulacao)' -L 'Ubuntu / CI'
sudo cupsaccept "$QUEUE"
sudo cupsenable "$QUEUE"
echo "Fila criada: $QUEUE. Verifique: lpstat -p \"$QUEUE\"; lpoptions -p \"$QUEUE\" -l"
echo "Arquivos CUPS-PDF: normalmente em ~/PDF (usuario de envio)."
echo "ATENCAO: CUPS-PDF utiliza sua propria conversao PDF; nao interpreta ESC/POS."
