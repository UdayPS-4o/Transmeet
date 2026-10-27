"""Machine translation through a self-hosted LibreTranslate server."""
import logging
import re
from collections import OrderedDict

import httpx

from . import config

log = logging.getLogger("transmeet.mt")

# Fallback names, used only until LibreTranslate answers /languages.
NAMES = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "ar": "Arabic", "bn": "Bengali", "ur": "Urdu", "tr": "Turkish",
    "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian", "id": "Indonesian", "vi": "Vietnamese",
}


class Translator:
    def __init__(self) -> None:
        headers = {"Content-Type": "application/json"}
        self.client = httpx.AsyncClient(base_url=config.LT_URL, timeout=15.0, headers=headers)
        self.cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self.available: set[str] = set()
        self.names = dict(NAMES)

    @property
    def online(self) -> bool:
        return bool(self.available)

    async def refresh(self) -> bool:
        """Ask LibreTranslate which languages it has loaded."""
        try:
            r = await self.client.get("/languages")
            r.raise_for_status()
            langs = r.json()
        except Exception as e:  # noqa: BLE001 - any failure just means "not ready yet"
            log.info("LibreTranslate not reachable yet (%s)", e.__class__.__name__)
            return False
        self.available = {l["code"] for l in langs}
        self.names.update({l["code"]: l["name"] for l in langs})
        log.info("LibreTranslate ready: %s", ",".join(sorted(self.available)))
        return True

    def languages(self) -> list[dict]:
        codes = [c for c in config.LANGUAGES if not self.available or c in self.available]
        return [{"code": c, "name": self.names.get(c, c)} for c in codes]

    async def translate(self, text: str, source: str, target: str) -> str | None:
        if not text or source == target:
            return text
        key = (source, target, text)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        body = {"q": text, "source": source, "target": target, "format": "text"}
        if config.LT_API_KEY:
            body["api_key"] = config.LT_API_KEY
        try:
            r = await self.client.post("/translate", json=body)
            r.raise_for_status()
            # Argos sometimes appends a "." after a native full stop (e.g. Hindi "।.")
            out = re.sub(r"([।。？！])\.$", r"\1", r.json()["translatedText"].strip())
        except Exception as e:  # noqa: BLE001
            log.warning("translate %s->%s failed: %s", source, target, e)
            return None
        self.cache[key] = out
        if len(self.cache) > 2000:
            self.cache.popitem(last=False)
        return out

    async def close(self) -> None:
        await self.client.aclose()
