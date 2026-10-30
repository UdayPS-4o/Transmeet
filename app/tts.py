"""Text-to-speech with Piper, so a listener can *hear* the translation, not only read it.

Piper voices are small VITS models exported to ONNX (~60 MB each). On CPU they
synthesise a sentence in a fraction of its spoken length, so the translated
voice starts a few hundred milliseconds after the caption. Voices are downloaded
from the rhasspy/piper-voices repository on Hugging Face the first time they are
used (the Docker image bakes in the default voice of each language).
"""
import asyncio
import io
import json
import logging
import threading
import time
import wave
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import onnxruntime                 # already installed for faster-whisper's VAD
from huggingface_hub import hf_hub_download

from . import config

log = logging.getLogger("transmeet.tts")

VOICE_REPO = "rhasspy/piper-voices"
# Piper voices are named <lang>_<REGION>-<name>-<quality>; the speaker's gender is not
# in the name, so these labels let the UI offer "female / male" instead of model names.
VOICE_LABELS = {
    "en_US-lessac-medium": "Female", "en_US-ryan-medium": "Male", "en_US-amy-medium": "Female",
    "hi_IN-priyamvada-medium": "Female", "hi_IN-rohan-medium": "Male", "hi_IN-pratham-medium": "Male",
    "es_ES-davefx-medium": "Male", "es_MX-claude-high": "Female", "es_AR-daniela-high": "Female",
    "fr_FR-siwis-medium": "Female", "fr_FR-tom-medium": "Male",
    "de_DE-thorsten-medium": "Male", "de_DE-kerstin-low": "Female",
    "te_IN-padmavathi-medium": "Female", "te_IN-venkatesh-medium": "Male", "te_IN-maya-medium": "Female",
    "ml_IN-meera-medium": "Female", "ml_IN-arjun-medium": "Male",
    "ur_PK-aegis_female-medium": "Female", "ur_PK-fasih-medium": "Male",
}


def voice_files(name: str) -> tuple[str, str]:
    """Repository paths of a voice's model and config, e.g.
    hi_IN-priyamvada-medium -> hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx"""
    locale, speaker, quality = name.split("-", 2)
    base = f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}.onnx"
    return base, base + ".json"


class Speaker:
    def __init__(self) -> None:
        self.voices: dict[str, object] = {}           # voice name -> loaded PiperVoice
        self.failed: set[str] = set()
        self.load_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=config.TTS_WORKERS, thread_name_prefix="tts")
        self.cache: OrderedDict[tuple, bytes] = OrderedDict()
        self.enabled = config.TTS
        if self.enabled:
            try:
                import piper  # noqa: F401
            except ImportError:
                log.warning("piper-tts is not installed: spoken translations are off")
                self.enabled = False

    def catalog(self) -> dict[str, list[dict]]:
        """Voices offered per language, for the UI: {"hi": [{"id": ..., "label": "Female"}, ...]}"""
        if not self.enabled:
            return {}
        return {lang: [{"id": v, "label": VOICE_LABELS.get(v, v.split("-")[1].title())}
                       for v in names if v not in self.failed]
                for lang, names in config.TTS_VOICES.items() if lang in config.LANGUAGES}

    def warm_up(self) -> None:
        """Load the default voice of every language so the first sentence is not delayed."""
        for lang, names in config.TTS_VOICES.items():
            if lang in config.LANGUAGES and names:
                t = time.perf_counter()
                if self._voice(names[0]) is not None:
                    self._synth(names[0], "ok", 1.0)
                    log.info("Piper voice %s ready in %.1fs", names[0], time.perf_counter() - t)

    def _voice(self, name: str):
        if name in self.voices:
            return self.voices[name]
        if name in self.failed:
            return None
        with self.load_lock:
            if name in self.voices:
                return self.voices[name]
            try:
                from piper import PiperConfig, PiperVoice
                onnx, cfg = voice_files(name)
                kw = {"repo_id": VOICE_REPO, "cache_dir": config.TTS_DIR}
                model = hf_hub_download(filename=onnx, **kw)
                with open(hf_hub_download(filename=cfg, **kw), encoding="utf-8") as f:
                    voice_cfg = PiperConfig.from_dict(json.load(f))
                # PiperVoice.load() would let ONNX Runtime take every core, which slows down
                # Whisper transcribing the next sentence; a couple of threads is plenty.
                opts = onnxruntime.SessionOptions()
                opts.intra_op_num_threads = config.TTS_THREADS
                opts.inter_op_num_threads = 1
                session = onnxruntime.InferenceSession(model, sess_options=opts,
                                                       providers=["CPUExecutionProvider"])
                self.voices[name] = PiperVoice(session=session, config=voice_cfg)
            except Exception as e:  # noqa: BLE001 - a missing voice must not break captions
                log.warning("Piper voice %s unavailable: %s", name, e)
                self.failed.add(name)
                return None
        return self.voices[name]

    def pick(self, lang: str, voice: str | None) -> str | None:
        names = [v for v in config.TTS_VOICES.get(lang, []) if v not in self.failed]
        if not names:
            return None
        return voice if voice in names else names[0]

    async def speak(self, text: str, lang: str, voice: str | None = None,
                    rate: float = 1.0) -> tuple[bytes, float] | None:
        """WAV bytes of `text` read aloud in `lang`, and seconds spent synthesising.
        None when there is no voice for that language (the browser then falls back to
        its own speechSynthesis)."""
        name = self.pick(lang, voice) if self.enabled else None
        if not name or not text.strip():
            return None
        rate = min(2.0, max(0.5, rate))
        key = (name, round(rate, 2), text)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key], 0.0
        t = time.perf_counter()
        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(self.pool, self._synth, name, text, rate)
        if wav is None:
            return None
        self.cache[key] = wav
        if len(self.cache) > 300:
            self.cache.popitem(last=False)
        return wav, time.perf_counter() - t

    def _synth(self, name: str, text: str, rate: float) -> bytes | None:
        voice = self._voice(name)
        if voice is None:
            return None
        from piper import SynthesisConfig
        # length_scale stretches every phoneme: 0.8 = 25 % faster speech
        syn = SynthesisConfig(length_scale=1.0 / rate)
        pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, syn_config=syn))
        if not pcm:
            return None          # nothing pronounceable (e.g. only symbols): let the browser try
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(voice.config.sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()
