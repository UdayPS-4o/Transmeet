"""Runtime configuration, read once from environment variables."""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# --- Speech recognition (faster-whisper / CTranslate2) ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")          # tiny | base | small | medium ...
# Per-language overrides: a model name or a Hugging Face repo of a CTranslate2 Whisper
# model. Hindi uses Whisper small fine-tuned on Indian Hindi speech (IIT Madras SPRING
# Lab; FLEURS WER 16 % vs 56 % for stock small, and faster). English uses small, which
# is more robust to accents than base (FLEURS WER 4.7 % vs 7.3 %). Others stay on base.
HINDI_MODEL = "songzewu/vasista22-whisper-hindi-small-ct2"
WHISPER_MODEL_BY_LANG = dict(
    item.split("=", 1) for item in _list("WHISPER_MODEL_BY_LANG", f"hi={HINDI_MODEL},en=small")
    if "=" in item)
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")      # int8 is the fastest choice on CPU
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")         # cpu | cuda
# Two workers so both people in a call are transcribed at the same time instead of
# queueing behind each other. Measured on 4 vCPU: 2 threads per transcription is
# almost as fast as 4 (these models don't scale further), so 2 workers x 2 threads
# fills the CPU with no extra latency.
ASR_WORKERS = int(os.getenv("ASR_WORKERS", "2"))            # parallel transcriptions
_cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 2)
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "0")) or max(1, _cpus // ASR_WORKERS)
BEAM_SIZE = int(os.getenv("BEAM_SIZE", "1"))                # 1 = greedy (fast); 5 = Whisper default
MODEL_DIR = os.getenv("MODEL_DIR", "/models")

# --- Voice activity detection / segmentation ---
SILENCE_MS = int(os.getenv("SILENCE_MS", "600"))            # pause that ends an utterance
MAX_SEGMENT_S = float(os.getenv("MAX_SEGMENT_S", "10"))     # force-cut long monologues
INTERIM = _bool("INTERIM", True)                            # live "typing" captions while speaking
INTERIM_MS = int(os.getenv("INTERIM_MS", "1200"))
INTERIM_BUDGET_MS = int(os.getenv("INTERIM_BUDGET_MS", "1000"))  # skip interims costlier than this

# Raise quiet speech (laptop mics, soft voices) to a steady level before Whisper.
NORMALIZE_AUDIO = _bool("NORMALIZE_AUDIO", True)

# --- Spoken translations (Piper TTS) ---
TTS = _bool("TTS", True)
# Voices per language; the first is the default, "|" separates alternatives.
# Names are Piper voices from huggingface.co/rhasspy/piper-voices. Blank = these defaults.
_TTS_DEFAULT = ("en=en_US-lessac-medium|en_US-ryan-medium,"
                "hi=hi_IN-priyamvada-medium|hi_IN-rohan-medium,"
                "es=es_ES-davefx-medium|es_MX-claude-high,"
                "fr=fr_FR-siwis-medium,de=de_DE-thorsten-medium,"
                # more Indian languages, used when they are in LANGUAGES (Tamil has no Piper
                # voice yet, so the browser's voice is used for it)
                "te=te_IN-padmavathi-medium|te_IN-venkatesh-medium,ml=ml_IN-meera-medium|ml_IN-arjun-medium,"
                "mr=mr_IN-google-medium,bn=bn_BD-google-medium,ur=ur_PK-aegis_female-medium|ur_PK-fasih-medium,"
                "ne=ne_NP-chitwan-medium")
TTS_VOICES = {
    lang: [v for v in voices.split("|") if v]
    for lang, voices in (item.strip().split("=", 1) for item in
                         (os.getenv("TTS_VOICES") or _TTS_DEFAULT).split(",") if "=" in item)}
TTS_WORKERS = int(os.getenv("TTS_WORKERS", "1"))
TTS_THREADS = int(os.getenv("TTS_THREADS", "2"))            # CPU threads per synthesis
TTS_DIR = os.getenv("TTS_DIR", os.path.join(MODEL_DIR, "piper"))

# --- Machine translation ---
# "libretranslate" (separate container, CPU) or "nllb" (Meta NLLB-200 in this process,
# better quality and 200 languages incl. Tamil/Telugu/Bengali/Marathi; GPU or CPU).
MT_ENGINE = os.getenv("MT_ENGINE", "libretranslate").strip().lower()
MT_MODEL = os.getenv("MT_MODEL", "JustFrederik/nllb-200-distilled-600M-ct2-int8")  # HF repo or path
MT_DEVICE = os.getenv("MT_DEVICE", WHISPER_DEVICE)
MT_COMPUTE = os.getenv("MT_COMPUTE", "")                    # blank: int8_float16 on GPU, int8 on CPU
MT_THREADS = int(os.getenv("MT_THREADS", "2"))
MT_BEAM = int(os.getenv("MT_BEAM", "2"))
LT_URL = os.getenv("LT_URL", "http://libretranslate:5000").rstrip("/")
LT_API_KEY = os.getenv("LT_API_KEY", "")
LANGUAGES = _list("LANGUAGES", "en,hi,es,fr,de")

# --- Privacy ---
LOG_TRANSCRIPTS = _bool("LOG_TRANSCRIPTS", False)            # write caption text to server logs

# --- Calls / WebRTC ---
MAX_PEERS = int(os.getenv("MAX_PEERS", "2"))
STUN_URLS = _list("STUN_URLS", "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302")
TURN_URLS = _list("TURN_URLS", "")
TURN_USERNAME = os.getenv("TURN_USERNAME", "")
TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "")


def ice_servers() -> list[dict]:
    servers = [{"urls": STUN_URLS}] if STUN_URLS else []
    if TURN_URLS:
        servers.append({"urls": TURN_URLS, "username": TURN_USERNAME, "credential": TURN_CREDENTIAL})
    return servers
