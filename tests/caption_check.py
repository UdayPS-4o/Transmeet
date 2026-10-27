"""Does Transmeet caption what was actually said, and only that?

Streams a tests/mic_scenario.py recording to a running server exactly like the
browser does (16 kHz PCM16, 100 ms frames, real time). A second client
receives the captions. Every final caption is then matched against the
sentences that were really spoken:

  correct   - matches a spoken sentence (word error rate <= 35 %)
  garbled   - overlaps a sentence in time but the words are mostly wrong
  invented  - nothing was said then (keyboard, cough, hum or silence); a hallucination

    python tests/caption_check.py --url ws://localhost:8000 --wav mic_en.wav [--caption-lang hi]
"""
import argparse
import asyncio
import json
import random
import re
import time
import unicodedata
import wave

import jiwer
import websockets

FRAME = 1600


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"[^\w\s']", " ", s)
    return " ".join(s.split())


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--caption-lang", default=None)
    ap.add_argument("--speaker-lang", default=None,
                    help="what the speaker selects as 'I speak' (default: the real language); "
                         "set it wrong to test the wrong-language hint")
    args = ap.parse_args()
    meta = json.load(open(args.wav.rsplit(".", 1)[0] + ".json", encoding="utf-8"))
    lang = meta["lang"]
    with wave.open(args.wav) as w:
        pcm = w.readframes(w.getnframes())

    room = f"check-{int(time.time())}-{random.randint(1000, 9999)}"
    speaker = await websockets.connect(f"{args.url}/ws/{room}", max_size=None)
    listener = await websockets.connect(f"{args.url}/ws/{room}", max_size=None)
    said = args.speaker_lang or lang
    await speaker.send(json.dumps({"type": "join", "name": "speaker", "lang": said, "captionLang": said}))
    await listener.send(json.dumps({"type": "join", "name": "listener", "lang": args.caption_lang or lang,
                                    "captionLang": args.caption_lang or lang}))
    finals, interims, hints = [], 0, []
    t0 = None

    async def drain(ws, keep: bool):
        nonlocal interims
        async for raw in ws:
            m = json.loads(raw)
            if m.get("type") == "lang-hint":
                hints.append(m)
            if keep and m.get("type") == "caption":
                if m["final"] and m["text"]:
                    finals.append({"at": round(time.monotonic() - t0, 2), "text": m["text"],
                                   "translated": m.get("translated"), "timings": m.get("timings")})
                elif not m["final"]:
                    interims += 1

    t0 = time.monotonic()
    tasks = [asyncio.create_task(drain(speaker, False)), asyncio.create_task(drain(listener, True))]
    nxt = time.monotonic()
    for i in range(0, len(pcm), FRAME * 2):
        await speaker.send(pcm[i:i + FRAME * 2])
        nxt += 0.1
        await asyncio.sleep(max(0, nxt - time.monotonic()))
    await asyncio.sleep(8)                     # let the last caption arrive
    for t in tasks:
        t.cancel()
    await speaker.close()
    await listener.close()

    spoken = [e for e in meta["events"] if e["kind"] == "speech"]
    used = set()
    rows = []
    for f in finals:
        # sentences that ended before this caption arrived (captions come after speech)
        cands = [(i, s) for i, s in enumerate(spoken) if s["start"] <= f["at"]]
        best = min(cands, key=lambda c: jiwer.wer(norm(c[1]["text"]), norm(f["text"]) or "x"), default=None)
        wer = jiwer.wer(norm(best[1]["text"]), norm(f["text"]) or "x") if best else 1.0
        # was anything being said in the few seconds before this caption?
        recent = [s for s in spoken if s["start"] - 1 <= f["at"] and f["at"] - s["end"] <= 12]
        if best and wer <= 0.35:
            verdict = "correct"
            used.add(best[0])
        elif recent:
            verdict = "garbled"
        else:
            verdict = "invented"
        rows.append({**f, "verdict": verdict, "expected": best[1]["text"] if best else None, "wer": round(wer, 2)})

    print(f"\n=== {args.wav}  ({lang}{' -> ' + args.caption_lang if args.caption_lang else ''}) ===")
    for r in rows:
        print(f"[{r['at']:6.1f}s] {r['verdict']:8s} WER {r['wer']:.2f} | heard: {r['text']}")
        if r["verdict"] != "correct" and r["expected"]:
            print(f"{'':27s}| said:  {r['expected']}")
        if r["translated"]:
            print(f"{'':27s}| shown: {r['translated']}")
    counts = {k: sum(r["verdict"] == k for r in rows) for k in ("correct", "garbled", "invented")}
    missed = [s["text"] for i, s in enumerate(spoken) if i not in used]
    print(f"\nspoken sentences: {len(spoken)}, captioned correctly: {len(used)}, "
          f"garbled: {counts['garbled']}, invented: {counts['invented']}, interims: {interims}")
    for m in missed:
        print(f"  not captioned correctly: {m}")
    for h in hints:
        print(f"wrong-language hint sent to speaker: selected {h['selected']}, sounds like {h['detected']} "
              f"({h['probability']:.0%})")
    if args.speaker_lang not in (None, "auto", lang):
        ok = any(h["detected"] == lang for h in hints)
        print("PASS (speaker was warned)" if ok else "FAIL (no warning)")
        return
    ok = counts["invented"] == 0 and len(used) == len(spoken)
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
