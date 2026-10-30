"""Speech-to-text with faster-whisper (Whisper running on CTranslate2)."""
import asyncio
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model
from huggingface_hub import hf_hub_download

from . import config

log = logging.getLogger("transmeet.asr")

# Whisper was trained on subtitled video and sometimes "hears" these in noise.
HALLUCINATIONS = re.compile(
    r"^(thank you\.?|thanks for watching!?|please subscribe.*|you|bye\.?|\.+|"
    r"subtitles by .*|amara\.org.*)$", re.IGNORECASE)


def prepare_model(name: str) -> str:
    """Folder of a CTranslate2 Whisper model (a size like "small", a Hugging Face repo, or a
    local path), downloaded into MODEL_DIR if needed. Some community conversions, such as
    the Indian-Hindi model, ship without tokenizer.json; faster-whisper would then fetch
    one from the internet each time the container starts, so Hindi would not load offline.
    The standard multilingual Whisper tokenizer is copied in once instead."""
    path = name if os.path.isdir(name) else download_model(name, cache_dir=config.MODEL_DIR)
    tokenizer = os.path.join(path, "tokenizer.json")
    if not os.path.exists(tokenizer):
        shutil.copyfile(hf_hub_download("openai/whisper-tiny", "tokenizer.json",
                                        cache_dir=config.MODEL_DIR), tokenizer)
    return path


class Transcriber:
    def __init__(self) -> None:
        self.models: dict[str, WhisperModel] = {}
        for name in {config.WHISPER_MODEL, *config.WHISPER_MODEL_BY_LANG.values()}:
            t = time.perf_counter()
            self.models[name] = WhisperModel(
                prepare_model(name),
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE,
                cpu_threads=config.WHISPER_THREADS,
                num_workers=config.ASR_WORKERS,
                download_root=config.MODEL_DIR,
            )
            # warm up this model itself: looking it up by language could pick a model
            # that is not loaded yet (e.g. "en" -> small while base is loading)
            lang = next((l for l, m in config.WHISPER_MODEL_BY_LANG.items() if m == name), "en")
            self._run(np.zeros(16000, dtype=np.float32), lang, final=True, model=name)
            log.info("Whisper '%s' (%s/%s, %d workers x %d threads) ready in %.1fs", name,
                     config.WHISPER_DEVICE, config.WHISPER_COMPUTE, config.ASR_WORKERS,
                     config.WHISPER_THREADS, time.perf_counter() - t)
        self.pool = ThreadPoolExecutor(max_workers=config.ASR_WORKERS, thread_name_prefix="asr")
        self.busy = 0
        self.rtf = {name: 0.3 for name in self.models}     # running estimate of compute s per audio s

    @staticmethod
    def model_name(language: str) -> str:
        return config.WHISPER_MODEL_BY_LANG.get(language, config.WHISPER_MODEL)

    async def transcribe(self, audio: np.ndarray, language: str, final: bool,
                         hotwords: str = "") -> tuple[str, float]:
        """Returns (text, seconds spent computing). Time spent waiting for a free
        worker is not included, so callers can separate queueing from compute.
        `hotwords` are names and terms the room expects (e.g. "Priya, Transmeet, IIT"),
        which nudges Whisper towards spelling them correctly."""
        self.busy += 1
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.pool, self._timed, audio, language, final,
                                              hotwords)
        finally:
            self.busy -= 1

    async def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Which language does this sound like? Uses the default (fastest) model.
        Whisper pads every input to 30 s, so this costs ~0.5 s on CPU whatever the length."""
        loop = asyncio.get_running_loop()
        lang, prob, _ = await loop.run_in_executor(
            self.pool, lambda: self.models[config.WHISPER_MODEL].detect_language(audio))
        return lang, prob

    async def pick_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Most likely language among the ones this server offers (for "Auto-detect")."""
        loop = asyncio.get_running_loop()
        _, _, probs = await loop.run_in_executor(
            self.pool, lambda: self.models[config.WHISPER_MODEL].detect_language(audio))
        return best_offered(probs)

    def estimate(self, seconds: float, language: str) -> float:
        """Expected compute time (s) to transcribe `seconds` of audio in `language`."""
        return self.rtf[self.model_name(language)] * seconds

    def _timed(self, audio: np.ndarray, language: str, final: bool,
               hotwords: str = "") -> tuple[str, float]:
        t = time.perf_counter()
        text = self._run(audio, language, final, hotwords)
        took = time.perf_counter() - t
        if len(audio) >= 16000:
            name = self.model_name(language)
            self.rtf[name] += 0.2 * (took / (len(audio) / 16000) - self.rtf[name])
        return text, took

    def _run(self, audio: np.ndarray, language: str, final: bool, hotwords: str = "",
             model: str | None = None) -> str:
        seconds = len(audio) / 16000
        if config.NORMALIZE_AUDIO:
            audio = normalize(audio)
        segments, _ = self.models[model or self.model_name(language)].transcribe(
            audio,
            # Stop decoding loops from tying up the CPU. Reference Hindi text averages
            # ~12 tokens/s (FLEURS), but Whisper's misspelt Devanagari needs more:
            # caps of 20/s and 30/s raised Hindi WER from 50% to 61% / 54%, so 40/s.
            max_new_tokens=min(440, int(40 * seconds) + 16),
            language=language or None,
            task="transcribe",
            beam_size=config.BEAM_SIZE,
            # one retry at a higher temperature for finals; interims stay greedy
            temperature=[0.0, 0.4] if final else 0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            hotwords=hotwords or None,
        )
        parts = []
        for s in segments:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            parts.append(s.text.strip())
        text = collapse_repeats(" ".join(p for p in parts if p).strip())
        return "" if HALLUCINATIONS.match(text) else text


def best_offered(probs: list[tuple[str, float]] | None) -> tuple[str, float]:
    """Most likely language among the ones this server offers. Whisper often hears Hindi
    as Urdu (same spoken language, different script), so unless Urdu is offered too,
    Urdu's probability is counted as Hindi."""
    scores = dict(probs or [])
    if "hi" in config.LANGUAGES and "ur" not in config.LANGUAGES:
        scores["hi"] = scores.get("hi", 0) + scores.pop("ur", 0)
    best = max(config.LANGUAGES, key=lambda l: scores.get(l, 0))
    return best, scores.get(best, 0.0)


def normalize(audio: np.ndarray, target_rms: float = 0.06, max_gain: float = 12.0) -> np.ndarray:
    """Bring speech to about -24 dBFS RMS. Far-field laptop mics and soft voices often
    arrive at -40 dBFS or lower, where Whisper drops words and small models start to
    invent text. Gain is capped (+21.6 dB) so near-silence is not blown up into noise,
    and the peak is kept below full scale."""
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    if rms < 1e-4:
        return audio
    gain = min(max_gain, target_rms / rms)
    peak = float(np.max(np.abs(audio))) * gain
    if peak > 0.98:
        gain *= 0.98 / peak
    return (audio * gain).astype(np.float32) if abs(gain - 1.0) > 0.05 else audio


def collapse_repeats(text: str, keep: int = 2) -> str:
    """Whisper (especially small models on non-English audio) can get stuck
    emitting the same token or phrase over and over. Collapse any run of an
    identical 1-3 word unit repeated more than `keep` times."""
    words = text.split()
    for n in (1, 2, 3):
        out: list[str] = []
        i = 0
        while i < len(words):
            unit = words[i:i + n]
            j = i + n
            reps = 1
            while words[j:j + n] == unit:
                reps += 1
                j += n
            if reps == 1:
                out.append(words[i])
                i += 1
            else:
                out.extend(unit * min(reps, keep))
                i = j
        words = out
    return " ".join(words)
