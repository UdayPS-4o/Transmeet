FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_DIR=/models

# openssl: self-signed certificate for HTTPS=true (see start.sh)
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# GPU=true adds the CUDA 12 / cuDNN 9 libraries CTranslate2 needs to run Whisper and
# NLLB on an NVIDIA GPU (the driver itself comes from the host). See docker-compose.demo.yml.
ARG GPU=false
RUN if [ "$GPU" = "true" ]; then pip install "nvidia-cublas-cu12==12.*" "nvidia-cudnn-cu12==9.*"; fi
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

# Bake the default Whisper models into the image so the first call works offline
# and starts fast. Any other size you configure is downloaded on first start into
# the /models volume. The Hindi model is a Whisper `small` fine-tuned on Indian
# Hindi speech (see docs/BENCHMARKS.md), already converted to CTranslate2.
ARG WHISPER_PRELOAD="base small songzewu/vasista22-whisper-hindi-small-ct2"
RUN for m in ${WHISPER_PRELOAD}; do \
      python -c "from faster_whisper.utils import download_model; download_model('$m', cache_dir='/models')"; \
    done

# NLLB translation model(s) for MT_ENGINE=nllb (none needed with LibreTranslate)
ARG MT_PRELOAD=""
RUN for m in ${MT_PRELOAD}; do \
      python -c "from huggingface_hub import snapshot_download; snapshot_download('$m', cache_dir='/models', allow_patterns=['*.bin', '*.json', '*.model', '*.txt'])"; \
    done

# The default Piper voice of each language, so translated speech works offline.
# Other voices listed in TTS_VOICES are fetched the first time someone picks them.
ARG TTS_PRELOAD="en_US-lessac-medium hi_IN-priyamvada-medium es_ES-davefx-medium fr_FR-siwis-medium de_DE-thorsten-medium"
COPY app/tts.py app/config.py app/__init__.py ./app/
RUN for v in ${TTS_PRELOAD}; do \
      python -c "import sys; from huggingface_hub import hf_hub_download; from app.tts import voice_files; \
[hf_hub_download('rhasspy/piper-voices', f, cache_dir='/models/piper') for f in voice_files(sys.argv[1])]" "$v"; \
    done

COPY app ./app
COPY start.sh .
# finish the baked models (e.g. add the tokenizer the Hindi model lacks) so that start-up
# never needs the internet: the demo can run on a Wi-Fi network with no internet access
RUN python -c "import sys; from app.asr import prepare_model; [prepare_model(m) for m in sys.argv[1:]]" ${WHISPER_PRELOAD}

# 8000: plain HTTP (always); 8443: HTTPS when HTTPS=true (see start.sh)
EXPOSE 8000 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# One process: rooms live in memory and Whisper already uses every CPU core.
CMD ["sh", "start.sh"]
