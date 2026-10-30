"""Offline accuracy benchmark: ASR (WER/CER) and machine translation (BLEU/chrF).

Uses the same Transcriber / Translator classes as the server, but no WebSocket.
Run from the repo root after `python -m bench.fetch_fleurs`:

    WHISPER_MODEL=base LT_URL=http://localhost:5000 python -m bench.accuracy

Part (a) transcribes every wav with the source language given.
Part (b) translates both the FLEURS reference text and the ASR output (the cascade
the real app uses) and scores it against the FLEURS text of the target language.
"""
import argparse
import asyncio
import json
import os
import re
import time
import unicodedata
import wave
from pathlib import Path

import jiwer
import numpy as np
import sacrebleu

# app.config reads its settings when it is imported, so set the defaults first.
os.environ.setdefault("LT_URL", "http://localhost:5000")
os.environ.setdefault("MODEL_DIR", str(Path.home() / ".cache" / "huggingface" / "hub"))
from app import config  # noqa: E402
from app.asr import Transcriber  # noqa: E402
from app.translate import Translator, make_translator  # noqa: E402

BENCH = Path(__file__).resolve().parent
GAIN = 1.0                                   # set from --gain-db
ROOT = BENCH.parent


def load_wav(path: str) -> np.ndarray:
    """16 kHz mono PCM16 wav -> float32 in [-1, 1], the same thing the server feeds Whisper."""
    with wave.open(str(ROOT / path)) as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2, "expected 16 kHz PCM16"
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def normalise(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace (applied to reference and hypothesis)."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"['’]", "", text)          # don't -> dont
    # replace every other punctuation char (Unicode category P*, incl. the Hindi danda) by a space
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.split())


async def run_asr(asr: Transcriber, manifest: dict, langs: list[str], n: int) -> dict:
    out = {}
    for lang in langs:
        rows, refs, hyps = [], [], []
        total_asr = total_audio = 0.0
        ids = [i for i in manifest if lang in manifest[i]][:n]
        for k, sid in enumerate(ids, 1):
            audio = load_wav(manifest[sid][lang]["wav"]) * GAIN
            hyp, dt = await asr.transcribe(audio, lang, final=True)   # dt = Whisper compute seconds
            total_asr += dt
            total_audio += len(audio) / 16000
            ref = manifest[sid][lang]["text"]
            rows.append({"id": sid, "ref": ref, "hyp": hyp, "asr_s": round(dt, 3)})
            refs.append(normalise(ref))
            hyps.append(normalise(hyp))
            print(f"\r  ASR {lang}: {k}/{len(ids)}", end="", flush=True)
        print()
        res = {"n": len(ids), "wer": jiwer.wer(refs, hyps),
               "mean_asr_s": total_asr / len(ids), "mean_audio_s": total_audio / len(ids),
               "rtf": total_asr / total_audio, "utterances": rows}
        if lang == "hi":
            res["cer"] = jiwer.cer(refs, hyps)
        out[lang] = res
    return out


async def run_mt(mt: Translator, manifest: dict, asr: dict, pairs: list[tuple[str, str]], n: int) -> dict:
    out = {}
    for src, tgt in pairs:
        ids = [i for i in manifest if src in manifest[i] and tgt in manifest[i]
               and any(r["id"] == i for r in asr[src]["utterances"])][:n]
        hyp_asr = {r["id"]: r["hyp"] for r in asr[src]["utterances"]}
        refs = [manifest[i][tgt]["text"] for i in ids]
        res, failures = {}, 0
        for cond, sources in (("reference", [manifest[i][src]["text"] for i in ids]),
                              ("cascade", [hyp_asr[i] for i in ids])):
            hyps, times = [], []
            for text in sources:
                mt.cache.clear()                  # otherwise repeated sentences would time as 0 ms
                t = time.perf_counter()
                tr = await mt.translate(text, src, tgt)
                if text:                          # empty ASR output is never sent to the MT server
                    times.append((time.perf_counter() - t) * 1000)
                failures += tr is None
                hyps.append(tr or "")
            # the default 13a tokeniser leaves the Hindi danda glued to the last word
            tok = "intl" if tgt == "hi" else "13a"
            res[cond] = {"bleu": sacrebleu.corpus_bleu(hyps, [refs], tokenize=tok).score,
                         "chrf": sacrebleu.corpus_chrf(hyps, [refs]).score,
                         "mean_mt_ms": float(np.mean(times)) if times else 0.0,
                         "hyps": hyps}
        out[f"{src}-{tgt}"] = {"n": len(ids), "failures": failures, "refs": refs, **res}
    return out


def to_markdown(model: str, info: dict, asr: dict, mt: dict) -> str:
    L = [f"# Accuracy: Whisper `{model}`", "",
         f"Settings: {info}", "", "## ASR (WER on normalised text)", "",
         "| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |", "|---|---|---|---|---|---|---|"]
    for lang, r in asr.items():
        cer = f"{r['cer'] * 100:.1f}" if "cer" in r else "-"
        L.append(f"| {lang} | {r['n']} | {r['wer'] * 100:.1f} | {cer} | {r['mean_asr_s']:.2f} | "
                 f"{r['mean_audio_s']:.1f} | {r['rtf']:.3f} |")
    if mt:
        L += ["", "## Machine translation (LibreTranslate)", "",
              "| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |",
              "|---|---|---|---|---|---|---|---|---|"]
        for pair, r in mt.items():
            a, b = r["reference"], r["cascade"]
            L.append(f"| {pair} | {r['n']} | {a['bleu']:.1f} | {a['chrf']:.1f} | {b['bleu']:.1f} | "
                     f"{b['chrf']:.1f} | {a['mean_mt_ms']:.0f} | {b['mean_mt_ms']:.0f} | {r['failures']} |")
        L += ["", "ref = translating the FLEURS source text; cascade = translating the ASR output."]
    return "\n".join(L) + "\n"


async def wait_for_translator(mt: Translator, timeout: float = 120) -> bool:
    end = time.monotonic() + timeout
    while not await mt.refresh():
        if time.monotonic() > end:
            return False
        await asyncio.sleep(3)
    return True


async def main() -> None:
    ap = argparse.ArgumentParser(description="ASR + MT accuracy benchmark")
    ap.add_argument("--pairs", default="en-hi,hi-en,en-es,es-en")
    ap.add_argument("--n", type=int, default=1000, help="max utterances per language")
    ap.add_argument("--manifest", type=Path, default=BENCH / "data" / "manifest.json")
    ap.add_argument("--name", help="results file name (default: the Whisper model)")
    ap.add_argument("--gain-db", type=float, default=0.0,
                    help="scale every clip, e.g. -26 to imitate a quiet far-field laptop mic")
    args = ap.parse_args()

    global GAIN
    GAIN = 10 ** (args.gain_db / 20)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    langs = sorted({l for v in manifest.values() for l in v}, key=["en", "hi", "es", "fr", "de"].index)
    wanted = [tuple(p.split("-")) for p in args.pairs.split(",") if p]
    pairs = [p for p in wanted if p[0] in langs and p[1] in langs]
    if len(pairs) < len(wanted):
        print(f"note: some pairs skipped, manifest only has {langs}")

    print(f"loading Whisper '{config.WHISPER_MODEL}' {config.WHISPER_MODEL_BY_LANG or ''} ({config.WHISPER_COMPUTE}, beam {config.BEAM_SIZE}) ...")
    asr = Transcriber()
    asr_res = await run_asr(asr, manifest, langs, args.n)

    mt_res = {}
    if pairs:
        mt = make_translator()
        if await wait_for_translator(mt):
            missing = {l for p in pairs for l in p} - mt.available
            if missing:
                print(f"LibreTranslate lacks {missing}, skipping MT")
            else:
                await mt.translate("warm up", "en", "es")      # first request is slow
                mt_res = await run_mt(mt, manifest, asr_res, pairs, args.n)
        else:
            print(f"LibreTranslate not reachable at {config.LT_URL}, skipping MT")
        await mt.close()

    model = (args.name or config.WHISPER_MODEL).replace("/", "_")
    info = {"device": config.WHISPER_DEVICE, "mt": config.MT_ENGINE, "mt_model": config.MT_MODEL,
            "compute": config.WHISPER_COMPUTE, "beam": config.BEAM_SIZE, "cpus": os.cpu_count(),
            "by_lang": config.WHISPER_MODEL_BY_LANG, "normalize": config.NORMALIZE_AUDIO,
            "gain_db": args.gain_db,
            "threads": config.WHISPER_THREADS, "lt_url": config.LT_URL}
    md = to_markdown(config.WHISPER_MODEL, info, asr_res, mt_res)
    print("\n" + md)
    out = BENCH / "results"
    out.mkdir(exist_ok=True)
    (out / f"accuracy-{model}.md").write_text(md, encoding="utf-8")
    (out / f"accuracy-{model}.json").write_text(
        json.dumps({"model": config.WHISPER_MODEL, "settings": info, "asr": asr_res, "mt": mt_res},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}/accuracy-{model}.json and .md")


if __name__ == "__main__":
    asyncio.run(main())
