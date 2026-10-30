"""Machine translation with Meta's NLLB-200 running in-process on CTranslate2.

An alternative to LibreTranslate (MT_ENGINE=nllb). One model covers 200 languages,
including Tamil, Telugu, Bengali, Marathi and other Indian languages that Argos has no
model for, and it translates Hindi noticeably better (see docs/BENCHMARKS.md). The
distilled 600M / 1.3B models run in real time on a laptop GPU, or on CPU with int8.

Note: the NLLB-200 weights are licensed CC-BY-NC-4.0 (non-commercial use only).
"""
import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("transmeet.nllb")

# ISO 639-1 (what Whisper and the UI use) -> NLLB / FLORES-200 code
CODES = {
    "en": "eng_Latn", "hi": "hin_Deva", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "ru": "rus_Cyrl", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "zh": "zho_Hans", "ar": "arb_Arab", "tr": "tur_Latn", "nl": "nld_Latn", "pl": "pol_Latn",
    "uk": "ukr_Cyrl", "id": "ind_Latn", "vi": "vie_Latn", "th": "tha_Thai", "fa": "pes_Arab",
    # Indian languages
    "bn": "ben_Beng", "ur": "urd_Arab", "ta": "tam_Taml", "te": "tel_Telu", "mr": "mar_Deva",
    "gu": "guj_Gujr", "kn": "kan_Knda", "ml": "mal_Mlym", "pa": "pan_Guru", "or": "ory_Orya",
    "as": "asm_Beng", "ne": "npi_Deva", "sa": "san_Deva", "sd": "snd_Arab",
}
NAMES = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "ar": "Arabic", "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian",
    "id": "Indonesian", "vi": "Vietnamese", "th": "Thai", "fa": "Persian", "bn": "Bengali",
    "ur": "Urdu", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati",
    "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia", "as": "Assamese",
    "ne": "Nepali", "sa": "Sanskrit", "sd": "Sindhi",
}
# NLLB is trained on single sentences; longer input is split so nothing gets dropped.
SENTENCE_END = re.compile(r"(?<=[.!?।॥？！。])\s+")


class NLLBTranslator:
    """Same interface as translate.Translator, so main.py can use either."""

    def __init__(self) -> None:
        self.cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self.available: set[str] = set()
        self.names = dict(NAMES)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt")
        self.model = self.sp = None

    @property
    def online(self) -> bool:
        return bool(self.available)

    def _load(self) -> None:
        import ctranslate2
        import sentencepiece
        from huggingface_hub import snapshot_download
        t = time.perf_counter()
        path = config.MT_MODEL
        if not os.path.isdir(path):
            path = snapshot_download(path, cache_dir=config.MODEL_DIR,
                                     allow_patterns=["*.bin", "*.json", "*.model", "*.txt"])
        compute = config.MT_COMPUTE or ("int8_float16" if config.MT_DEVICE == "cuda" else "int8")
        self.model = ctranslate2.Translator(path, device=config.MT_DEVICE, compute_type=compute,
                                            inter_threads=1, intra_threads=config.MT_THREADS)
        self.sp = sentencepiece.SentencePieceProcessor(
            model_file=os.path.join(path, "sentencepiece.bpe.model"))
        self.available = {c for c in config.LANGUAGES if c in CODES}
        log.info("NLLB %s (%s/%s) ready in %.1fs: %s", config.MT_MODEL, config.MT_DEVICE, compute,
                 time.perf_counter() - t, ",".join(sorted(self.available)))

    async def refresh(self) -> bool:
        if self.model is None:
            try:
                await asyncio.get_running_loop().run_in_executor(self.pool, self._load)
            except Exception as e:  # noqa: BLE001 - captions still work untranslated
                log.warning("NLLB failed to load: %s", e)
                return False
        return True

    def languages(self) -> list[dict]:
        codes = [c for c in config.LANGUAGES if c in CODES]
        return [{"code": c, "name": self.names.get(c, c)} for c in codes]

    def _translate(self, text: str, source: str, target: str) -> str:
        parts = [p for p in SENTENCE_END.split(text) if p.strip()]
        batch = [[CODES[source], *self.sp.encode(p, out_type=str), "</s>"] for p in parts]
        results = self.model.translate_batch(
            batch, target_prefix=[[CODES[target]]] * len(batch), beam_size=config.MT_BEAM,
            max_decoding_length=256, repetition_penalty=1.1)
        return " ".join(self.sp.decode(r.hypotheses[0][1:]) for r in results).strip()

    async def translate(self, text: str, source: str, target: str) -> str | None:
        if not text or source == target:
            return text
        if self.model is None or source not in CODES or target not in CODES:
            return None
        key = (source, target, text)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        try:
            out = await asyncio.get_running_loop().run_in_executor(
                self.pool, self._translate, text, source, target)
        except Exception as e:  # noqa: BLE001
            log.warning("translate %s->%s failed: %s", source, target, e)
            return None
        self.cache[key] = out
        if len(self.cache) > 2000:
            self.cache.popitem(last=False)
        return out

    async def close(self) -> None:
        self.pool.shutdown(wait=False)
