"""Transmeet server.

One process serves everything on a single port (and so a single domain):
  * the web UI (static files)
  * /ws/{room}   WebSocket used for WebRTC signalling (JSON text frames)
                 and for the caller's microphone audio (binary PCM frames)
  * /api/*       config, health and latency statistics

Video and audio between the two callers flow peer-to-peer over WebRTC. Only a
16 kHz mono copy of each microphone reaches the server, where it goes through
VAD -> Whisper -> LibreTranslate. The resulting captions are pushed back to
every participant in the language that participant asked for.
"""
import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .asr import Transcriber
from .translate import Translator
from .vad import SAMPLE_RATE, Segmenter, Utterance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("transmeet")

asr: Transcriber
mt: Translator
STATS: deque[dict] = deque(maxlen=1000)


async def _wait_for_translator() -> None:
    while not await mt.refresh():
        await asyncio.sleep(5)
    # LibreTranslate loads each language model on its first request, which can take
    # 10+ s. Do that now rather than on the first sentence someone says in a call.
    t = time.monotonic()
    codes = [l["code"] for l in mt.languages()]
    pivot = "en" if "en" in codes else codes[0]
    await asyncio.gather(*(mt.translate("Hello, how are you?", a, b)
                           for c in codes if c != pivot for a, b in ((pivot, c), (c, pivot))))
    mt.cache.clear()
    log.info("translation models warmed up in %.1fs", time.monotonic() - t)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global asr, mt
    mt = Translator()
    asr = await asyncio.to_thread(Transcriber)
    task = asyncio.create_task(_wait_for_translator())
    yield
    task.cancel()
    await mt.close()


app = FastAPI(title="Transmeet", lifespan=lifespan)


# --------------------------------------------------------------------------- rooms

class Peer:
    def __init__(self, ws: WebSocket, room: "Room", name: str, lang: str, caption_lang: str):
        self.id = uuid.uuid4().hex[:8]
        self.ws, self.room = ws, room
        self.name, self.lang, self.caption_lang = name, lang, caption_lang
        self.seg = Segmenter(config.SILENCE_MS, config.MAX_SEGMENT_S)
        self.send_lock = asyncio.Lock()
        self.final_lock = asyncio.Lock()     # keeps this speaker's finals in order
        self.seq = 0                         # number of the utterance in progress
        self.finalized = 0                   # highest utterance number already finalised
        self.interim_busy = False
        self.last_interim = 0.0
        self.speaking = False                # VAD state last reported to the room
        self.auto_lang: str | None = None     # last detected language when lang == "auto"
        self.lang_checks = 0                 # spoken-language checks done so far

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "lang": self.lang, "captionLang": self.caption_lang}

    async def send(self, msg: dict) -> None:
        async with self.send_lock:
            with contextlib.suppress(Exception):
                await self.ws.send_text(json.dumps(msg))


class Room:
    def __init__(self, rid: str):
        self.id = rid
        self.peers: dict[str, Peer] = {}

    async def broadcast(self, msg: dict, exclude: str | None = None) -> None:
        await asyncio.gather(*(p.send(msg) for p in list(self.peers.values()) if p.id != exclude))


ROOMS: dict[str, Room] = {}


# --------------------------------------------------------------------------- caption pipeline

def handle_audio(peer: Peer, payload: bytes) -> None:
    pcm = np.frombuffer(payload[: len(payload) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    for utt in peer.seg.push(pcm):
        peer.seq += 1
        asyncio.create_task(process_final(peer, peer.seq, utt))
    if peer.seg.in_speech != peer.speaking:
        # lets the UI show "hearing you…" / "Priya is speaking…" the moment speech starts
        peer.speaking = peer.seg.in_speech
        asyncio.create_task(peer.room.broadcast({"type": "speaking", "id": peer.id,
                                                 "speaking": peer.speaking}))
    if peer.seg.in_speech:
        maybe_interim(peer)


def maybe_interim(peer: Peer) -> None:
    """Schedule a quick partial transcription so captions appear while the person talks.
    Skipped when every Whisper worker is busy: finals always take priority on a small CPU."""
    if not config.INTERIM or peer.interim_busy or asr.busy >= config.ASR_WORKERS:
        return
    now = time.monotonic()
    if now - peer.last_interim < config.INTERIM_MS / 1000 or now - peer.seg.started_at < 1.0:
        return
    audio = peer.seg.current_audio()
    if audio is None:
        return
    src = peer.lang if peer.lang != "auto" else peer.auto_lang
    if src is None:
        return          # auto-detect has not heard a full sentence yet
    # On a slow model (e.g. Hindi on `small`) re-transcribing a long sentence would
    # delay its final caption, so interims stop once they get too expensive.
    if asr.estimate(len(audio) / SAMPLE_RATE, src) * 1000 > config.INTERIM_BUDGET_MS:
        return
    peer.last_interim = now
    peer.interim_busy = True
    asyncio.create_task(process_interim(peer, peer.seq + 1, audio, src))


async def process_interim(peer: Peer, n: int, audio: np.ndarray, src: str) -> None:
    try:
        text, _ = await asr.transcribe(audio, src, final=False)
        if not text or peer.finalized >= n:
            return      # the final caption for this utterance already went out
        translations = await translate_for_room(peer, text, src)
        if peer.finalized >= n:
            return
        await deliver(peer, n, text, src, translations, final=False, timings=None)
    finally:
        peer.interim_busy = False


async def process_final(peer: Peer, n: int, utt: Utterance) -> None:
    async with peer.final_lock:
        detect_s = 0.0
        src = peer.lang
        if src == "auto":
            t = time.monotonic()
            src, prob = await asr.pick_language(utt.audio)
            # very short or unclear sentences ("ok", "haan") are easy to misjudge:
            # keep the language this person has been speaking
            if peer.auto_lang and (prob < 0.6 or utt.audio.size < 1.5 * SAMPLE_RATE):
                src = peer.auto_lang
            peer.auto_lang = src
            detect_s = time.monotonic() - t
        text, asr_s = await asr.transcribe(utt.audio, src, final=True)
        asr_s += detect_s
        t_asr = time.monotonic()
        translations = await translate_for_room(peer, text, src) if text else {}
        t_mt = time.monotonic()
        peer.finalized = max(peer.finalized, n)
        ms = lambda s: round(s * 1000)  # noqa: E731
        timings = {
            "audioMs": ms(len(utt.audio) / SAMPLE_RATE),
            "vadMs": ms(utt.cut_at - utt.speech_end),             # pause needed to detect end of sentence
            "queueMs": ms(t_asr - utt.cut_at - asr_s),             # waiting for a free Whisper worker
            "asrMs": ms(asr_s),                                    # Whisper compute (+ language detection)
            "mtMs": ms(t_mt - t_asr),                              # LibreTranslate
            "totalMs": ms(t_mt - utt.speech_end),                  # end of speech -> caption sent
        }
        if not text:
            # still tell clients so a dangling interim caption is cleared
            await deliver(peer, n, "", src, {}, final=True, timings=timings)
            return
        STATS.append({**timings, "src": src, "model": asr.model_name(src),
                      "targets": sorted(k for k in translations if k != src)})
        log.info("[%s] %s (%s%s): %s | asr %dms mt %dms total %dms", peer.room.id, peer.name, src,
                 " auto" if peer.lang == "auto" else "",
                 text if config.LOG_TRANSCRIPTS else f"<{len(text)} chars>",
                 timings["asrMs"], timings["mtMs"], timings["totalMs"])
        await deliver(peer, n, text, src, translations, final=True, timings=timings)
        if peer.lang != "auto" and peer.lang_checks < 2 and utt.audio.size >= SAMPLE_RATE:
            peer.lang_checks += 1
            asyncio.create_task(check_language(peer, utt.audio))


async def check_language(peer: Peer, audio: np.ndarray) -> None:
    """A wrong "I speak" setting is the usual cause of nonsense captions: Whisper is
    told to expect Hindi, hears English, and writes Hindi-looking gibberish. Check the
    first sentences and tell the speaker if they seem to be speaking something else."""
    detected, prob = await asr.detect_language(audio)
    log.info("[%s] %s selected %s, sounds like %s (%.2f)", peer.room.id, peer.name,
             peer.lang, detected, prob)
    if detected != peer.lang and prob >= 0.7 and detected in config.LANGUAGES:
        peer.lang_checks = 99                # one hint is enough
        await peer.send({"type": "lang-hint", "selected": peer.lang, "detected": detected,
                         "probability": round(prob, 2)})


async def translate_for_room(speaker: Peer, text: str, src: str) -> dict[str, str | None]:
    targets = {p.caption_lang for p in speaker.room.peers.values()} - {src}
    results = await asyncio.gather(*(mt.translate(text, src, t) for t in targets))
    return {src: text, **dict(zip(targets, results))}


async def deliver(speaker: Peer, n: int, text: str, src: str, translations: dict, final: bool,
                  timings: dict | None) -> None:
    base = {"type": "caption", "seg": f"{speaker.id}-{n}", "speaker": speaker.id,
            "name": speaker.name, "final": final, "src": src, "text": text,
            "timings": timings}
    sends = []
    for p in list(speaker.room.peers.values()):
        tgt = p.caption_lang
        msg = {**base, "tgt": tgt,
               "translated": None if tgt == src else translations.get(tgt)}
        sends.append(p.send(msg))
    await asyncio.gather(*sends)


# --------------------------------------------------------------------------- websocket

ROOM_RE = re.compile(r"[^a-z0-9-]")


def lang_ok(code: str, allow_auto: bool = False) -> str:
    if allow_auto and code == "auto":
        return code
    return code if code in config.LANGUAGES else config.LANGUAGES[0]


@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    await ws.accept()
    rid = ROOM_RE.sub("", room_id.lower())[:40] or "lobby"
    peer: Peer | None = None
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if peer:
                    handle_audio(peer, msg["bytes"])
                continue
            data = json.loads(msg.get("text") or "{}")
            kind = data.get("type")

            if kind == "join" and peer is None:
                room = ROOMS.setdefault(rid, Room(rid))
                if len(room.peers) >= config.MAX_PEERS:
                    await ws.send_text(json.dumps({"type": "error", "code": "room_full",
                                                   "message": "This room already has two people."}))
                    break
                lang = lang_ok(data.get("lang", ""), allow_auto=True)
                peer = Peer(ws, room, str(data.get("name") or "Guest")[:40], lang,
                            lang_ok(data.get("captionLang", lang)))
                others = [p.info() for p in room.peers.values()]
                room.peers[peer.id] = peer
                await peer.send({"type": "joined", "id": peer.id, "room": rid, "peers": others})
                await room.broadcast({"type": "peer-joined", "peer": peer.info()}, exclude=peer.id)

            elif kind == "signal" and peer:
                target = peer.room.peers.get(data.get("to", ""))
                if target:
                    await target.send({"type": "signal", "from": peer.id, "data": data.get("data")})

            elif kind == "update" and peer:
                if "lang" in data:
                    peer.lang = lang_ok(data["lang"], allow_auto=True)
                    peer.lang_checks = 0
                if "captionLang" in data:
                    peer.caption_lang = lang_ok(data["captionLang"])
                await peer.room.broadcast({"type": "peer-updated", "peer": peer.info()})

            elif kind == "flush" and peer:
                for utt in peer.seg.flush():
                    peer.seq += 1
                    asyncio.create_task(process_final(peer, peer.seq, utt))

            elif kind == "ping":
                await ws.send_text('{"type":"pong"}')
    except Exception as e:  # noqa: BLE001 - a broken socket must never take the server down
        log.info("socket closed: %s", e)
    finally:
        if peer:
            room = peer.room
            room.peers.pop(peer.id, None)
            await room.broadcast({"type": "peer-left", "id": peer.id})
            if not room.peers:
                ROOMS.pop(room.id, None)
        with contextlib.suppress(Exception):
            await ws.close()


# --------------------------------------------------------------------------- http api

@app.get("/api/config")
async def get_config():
    return {
        "iceServers": config.ice_servers(),
        "languages": mt.languages(),
        "translator": mt.online,
        "model": config.WHISPER_MODEL,
        "modelByLang": config.WHISPER_MODEL_BY_LANG,
        "maxPeers": config.MAX_PEERS,
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "asr": config.WHISPER_MODEL, "translator": mt.online,
            "rooms": len(ROOMS), "peers": sum(len(r.peers) for r in ROOMS.values())}


@app.get("/api/stats")
async def stats():
    """Latency summary of recent final captions (milliseconds)."""
    rows = list(STATS)
    out: dict = {"count": len(rows), "model": config.WHISPER_MODEL, "beamSize": config.BEAM_SIZE,
                 "silenceMs": config.SILENCE_MS}
    for key in ("audioMs", "vadMs", "queueMs", "asrMs", "mtMs", "totalMs"):
        vals = np.array([r[key] for r in rows], dtype=float)
        out[key] = ({"mean": round(float(vals.mean())),
                     "p50": round(float(np.percentile(vals, 50))),
                     "p95": round(float(np.percentile(vals, 95)))} if len(vals) else None)
    if rows:
        rtf = [r["asrMs"] / max(r["audioMs"], 1) for r in rows]
        out["asrRealTimeFactor"] = round(float(np.mean(rtf)), 3)
    return JSONResponse(out)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
