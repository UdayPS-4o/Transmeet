"""Speech-to-text with faster-whisper (Whisper running on CTranslate2)."""
import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from faster_whisper import WhisperModel

from . import config

log = logging.getLogger("transmeet.asr")

# Whisper was trained on subtitled video and sometimes "hears" these in noise.
HALLUCINATIONS = re.compile(
    r"^(thank you\.?|thanks for watching!?|please subscribe.*|you|bye\.?|\.+|"
    r"subtitles by .*|amara\.org.*)$", re.IGNORECASE)


class Transcriber:
    def __init__(self) -> None:
        self.models: dict[str, WhisperModel] = {}
        for name in {config.WHISPER_MODEL, *config.WHISPER_MODEL_BY_LANG.values()}:
            t = time.perf_counter()
            self.models[name] = WhisperModel(
                name,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE,
                cpu_threads=config.WHISPER_THREADS,
                num_workers=config.ASR_WORKERS,
                download_root=config.MODEL_DIR,
            )
            lang = next((l for l, m in config.WHISPER_MODEL_BY_LANG.items() if m == name), "en")
            self._run(np.zeros(16000, dtype=np.float32), lang, final=True)   # warm-up
            log.info("Whisper '%s' (%s/%s) ready in %.1fs", name, config.WHISPER_DEVICE,
                     config.WHISPER_COMPUTE, time.perf_counter() - t)
        self.pool = ThreadPoolExecutor(max_workers=config.ASR_WORKERS, thread_name_prefix="asr")
        self.busy = 0

    @staticmethod
    def model_name(language: str) -> str:
        return config.WHISPER_MODEL_BY_LANG.get(language, config.WHISPER_MODEL)

    async def transcribe(self, audio: np.ndarray, language: str, final: bool) -> tuple[str, float]:
        """Returns (text, seconds spent computing). Time spent waiting for a free
        worker is not included, so callers can separate queueing from compute."""
        self.busy += 1
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.pool, self._timed, audio, language, final)
        finally:
            self.busy -= 1

    def _timed(self, audio: np.ndarray, language: str, final: bool) -> tuple[str, float]:
        t = time.perf_counter()
        text = self._run(audio, language, final)
        return text, time.perf_counter() - t

    def _run(self, audio: np.ndarray, language: str, final: bool) -> str:
        seconds = len(audio) / 16000
        segments, _ = self.models[self.model_name(language)].transcribe(
            audio,
            # Nobody says more than ~40 tokens per second (Devanagari is token-hungry).
            # The cap stops rare decoding loops from tying up the CPU for many seconds.
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
        )
        parts = []
        for s in segments:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            parts.append(s.text.strip())
        text = collapse_repeats(" ".join(p for p in parts if p).strip())
        return "" if HALLUCINATIONS.match(text) else text


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
