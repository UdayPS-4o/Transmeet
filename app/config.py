"""Runtime configuration, read once from environment variables."""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# --- Speech recognition (faster-whisper / CTranslate2) ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")          # tiny | base | small | medium ...
# Per-language overrides, e.g. "hi=small": small models are poor at some languages,
# so a bigger model can be used just for those speakers while others stay fast.
WHISPER_MODEL_BY_LANG = dict(
    item.split("=", 1) for item in _list("WHISPER_MODEL_BY_LANG", "") if "=" in item)
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")      # int8 is the fastest choice on CPU
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")         # cpu | cuda
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "0"))    # 0 = let CTranslate2 decide
ASR_WORKERS = int(os.getenv("ASR_WORKERS", "1"))            # parallel transcriptions
BEAM_SIZE = int(os.getenv("BEAM_SIZE", "1"))                # 1 = greedy (fast); 5 = Whisper default
MODEL_DIR = os.getenv("MODEL_DIR", "/models")

# --- Voice activity detection / segmentation ---
SILENCE_MS = int(os.getenv("SILENCE_MS", "600"))            # pause that ends an utterance
MAX_SEGMENT_S = float(os.getenv("MAX_SEGMENT_S", "10"))     # force-cut long monologues
INTERIM = _bool("INTERIM", True)                            # live "typing" captions while speaking
INTERIM_MS = int(os.getenv("INTERIM_MS", "1200"))

# --- Machine translation (LibreTranslate) ---
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
