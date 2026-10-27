"""End-to-end live latency benchmark against a RUNNING Transmeet server.

Two WebSocket clients join one room, exactly like two browsers would:
  A (speaker)  lang=<src>   streams a FLEURS wav as 100 ms PCM16 frames in real time
  B (listener) captionLang=<tgt>   waits for the final caption of A's speech

    python -m bench.latency --url ws://localhost:8000 --pairs en-hi,hi-en --n 10

latency = arrival of the final caption at B - moment the last audio frame was sent.
It therefore includes the server's SILENCE_MS wait, plus whatever silence the wav
itself ends with. The server's own timings (vad/asr/mt) come along in the message.
"""
import argparse
import asyncio
import json
import random
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import websockets

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
FRAME = 1600            # samples per websocket frame = 100 ms at 16 kHz
TAIL_S = 1.5            # silence streamed after each utterance
TIMEOUT_S = 20          # give up waiting for a final caption after this long


def load_pcm(path: str) -> bytes:
    with wave.open(str(ROOT / path)) as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2, "expected 16 kHz PCM16"
        return w.readframes(w.getnframes())          # already little-endian int16


async def stream_real_time(ws, pcm: bytes) -> float:
    """Send pcm in 100 ms frames at real-time pace; return the time the last frame went out."""
    t_next = time.monotonic()
    sent_at = t_next
    for i in range(0, len(pcm), FRAME * 2):
        await ws.send(pcm[i:i + FRAME * 2])          # the last frame may be shorter, that is fine
        sent_at = time.monotonic()
        t_next += 0.1                                # schedule against a clock so sleeps don't drift
        await asyncio.sleep(max(0.0, t_next - time.monotonic()))
    return sent_at


async def reader(ws, queue: asyncio.Queue) -> None:
    """Timestamp every caption message the moment it arrives."""
    try:
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") in ("caption", "error"):
                queue.put_nowait((time.monotonic(), msg))
    except websockets.ConnectionClosed:
        pass


async def join(url: str, room: str, name: str, lang: str, caption_lang: str):
    ws = await websockets.connect(f"{url}/ws/{room}", max_size=None, ping_interval=None)
    await ws.send(json.dumps({"type": "join", "name": name, "lang": lang, "captionLang": caption_lang}))
    while True:                                      # wait for the server's "joined" reply
        msg = json.loads(await ws.recv())
        if msg["type"] == "joined":
            return ws, msg["id"]
        if msg["type"] == "error":
            raise RuntimeError(msg["message"])


async def one_utterance(a_ws, a_id: str, queue: asyncio.Queue, pcm: bytes) -> dict:
    t_start = time.monotonic()
    t_end = await stream_real_time(a_ws, pcm)                    # t_speech_end
    await stream_real_time(a_ws, bytes(int(TAIL_S * 16000) * 2))  # 1.5 s of zeros, also real time
    interims: dict[str, int] = {}
    deadline = t_end + TIMEOUT_S
    while True:
        try:
            arrival, msg = await asyncio.wait_for(queue.get(), max(0.01, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            return {"status": "timeout"}
        if msg.get("type") == "error":
            raise RuntimeError(msg.get("message"))
        if msg["speaker"] != a_id or arrival < t_start:
            continue
        if not msg["final"]:
            interims[msg["seg"]] = interims.get(msg["seg"], 0) + 1
        elif arrival < t_end:
            continue            # final of an earlier piece: the VAD split the clip at a pause
        else:
            t = msg.get("timings") or {}
            return {"status": "empty" if not msg["text"] else "ok",
                    "latency_ms": (arrival - t_end) * 1000, "text": msg["text"],
                    "translated": msg.get("translated"), "interims": interims.get(msg["seg"], 0),
                    "timings": t}


async def run_pair(args, src: str, tgt: str, manifest: dict) -> dict:
    room = f"{args.room}-{src}-{tgt}"
    a_ws, a_id = await join(args.url, room, "bench-speaker", src, src)
    b_ws, _ = await join(args.url, room, "bench-listener", tgt, tgt)
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(reader(b_ws, queue))
    # The speaker also receives its own captions. They must be read, or the client
    # stops reading the socket, misses the server's pings and gets disconnected.
    drain = asyncio.create_task(reader(a_ws, asyncio.Queue()))
    ids = [i for i in manifest if src in manifest[i]][: args.n + args.warmup]
    rows = []
    try:
        for k, sid in enumerate(ids):
            r = await one_utterance(a_ws, a_id, queue, load_pcm(manifest[sid][src]["wav"]))
            warm = k < args.warmup                   # first utterance(s) only warm the server up
            r.update(id=sid, warmup=warm)
            rows.append(r)
            lat = f"{r['latency_ms']:.0f} ms" if "latency_ms" in r else r["status"]
            print(f"  {src}-{tgt} {k + 1}/{len(ids)}{' (warm-up)' if warm else ''}: {lat}")
    finally:
        task.cancel()
        drain.cancel()
        await a_ws.close()
        await b_ws.close()
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    rows = [r for r in rows if not r["warmup"]]
    ok = [r for r in rows if r["status"] == "ok"]
    out = {"n": len(rows), "ok": len(ok), "empty": sum(r["status"] == "empty" for r in rows),
           "timeouts": sum(r["status"] == "timeout" for r in rows),
           "no_translation": sum(r["translated"] is None for r in ok), "utterances": rows}
    if ok:
        lat = np.array([r["latency_ms"] for r in ok])
        out.update(mean_ms=lat.mean(), p50_ms=np.percentile(lat, 50), p95_ms=np.percentile(lat, 95))
        for key in ("vadMs", "asrMs", "mtMs", "totalMs"):
            out[f"server_{key}"] = float(np.mean([r["timings"].get(key, 0) for r in ok]))
        out["mean_interims"] = float(np.mean([r["interims"] for r in ok]))
    return out


def to_markdown(model: str, info: dict, results: dict) -> str:
    L = [f"# Live latency: Whisper `{model}`", "", f"Server: {info}", "",
         "| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | asr ms | mt ms | server total ms | interims/utt |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for pair, r in results.items():
        if r["ok"]:
            L.append(f"| {pair} | {r['ok']}/{r['n']} | {r['empty']} | {r['timeouts']} | {r['mean_ms']:.0f} | "
                     f"{r['p50_ms']:.0f} | {r['p95_ms']:.0f} | {r['server_vadMs']:.0f} | {r['server_asrMs']:.0f} | "
                     f"{r['server_mtMs']:.0f} | {r['server_totalMs']:.0f} | {r['mean_interims']:.1f} |")
        else:
            L.append(f"| {pair} | 0/{r['n']} | {r['empty']} | {r['timeouts']} | - | - | - | - | - | - | - | - |")
    L += ["", "e2e = final caption arrival at the listener - last audio frame sent (includes SILENCE_MS "
          "and any trailing silence in the wav)."]
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser(description="live end-to-end latency benchmark")
    ap.add_argument("--url", default="ws://localhost:8000")
    ap.add_argument("--room", default=f"bench-{random.randrange(16**6):06x}")
    ap.add_argument("--pairs", default="en-hi,hi-en")
    ap.add_argument("--n", type=int, default=10, help="utterances per pair")
    ap.add_argument("--warmup", type=int, default=1, help="extra utterances sent first and not counted")
    ap.add_argument("--manifest", type=Path, default=BENCH / "data" / "manifest.json")
    args = ap.parse_args()
    args.url = args.url.rstrip("/")

    # ask the HTTP API which model/settings the server runs (also checks it is up)
    http = args.url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    async with httpx.AsyncClient(timeout=10) as c:
        cfg = (await c.get(f"{http}/api/config")).json()
        stats = (await c.get(f"{http}/api/stats")).json()
    model = cfg["model"]
    info = {"model": model, "silenceMs": stats.get("silenceMs"), "beam": stats.get("beamSize"),
            "translator_online": cfg["translator"]}
    if not cfg["translator"]:
        print("warning: the server says LibreTranslate is offline, captions will have no translation")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = {}
    for pair in args.pairs.split(","):
        src, tgt = pair.strip().split("-")
        print(f"pair {pair} in room {args.room}-{src}-{tgt}")
        results[pair] = await run_pair(args, src, tgt, manifest)

    md = to_markdown(model, info, results)
    print("\n" + md)
    out = BENCH / "results"
    out.mkdir(exist_ok=True)
    name = model.replace("/", "_")
    (out / f"latency-{name}.md").write_text(md, encoding="utf-8")
    (out / f"latency-{name}.json").write_text(
        json.dumps({"model": model, "server": info, "url": args.url, "pairs": results},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}/latency-{name}.json and .md")


if __name__ == "__main__":
    asyncio.run(main())
