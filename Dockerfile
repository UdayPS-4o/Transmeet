FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_DIR=/models

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the default Whisper models into the image so the first call works offline
# and starts fast. Any other size you configure is downloaded on first start into
# the /models volume.
ARG WHISPER_PRELOAD="base small"
RUN for m in ${WHISPER_PRELOAD}; do \
      python -c "from faster_whisper import WhisperModel; WhisperModel('$m', device='cpu', compute_type='int8', download_root='/models')"; \
    done

COPY app ./app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# One worker: rooms live in memory and Whisper already uses every CPU core.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
