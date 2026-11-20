FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libjpeg62-turbo && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY posvirtual ./posvirtual
RUN useradd -m -u 10001 printer && mkdir -p /prints && chown printer:printer /prints
USER printer
EXPOSE 9100
ENTRYPOINT ["python", "-m", "posvirtual"]
CMD ["--host", "0.0.0.0", "--port", "9100", "--output", "/prints"]
