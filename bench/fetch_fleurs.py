"""Download a few FLEURS test utterances per language for the benchmarks.

FLEURS (google/fleurs on Hugging Face) is n-way parallel: the same sentence id
is read aloud in every language, so one id gives us a reference translation in
all the other languages. We use plain HTTP instead of the `datasets` library:

    data/<locale>/test.tsv                columns: id, wav file, raw text, normalised text, ...
    data/<locale>/audio/test.tar.gz       ~250-300 MB per language, 16 kHz mono wavs
                                          (stored as 32-bit FLOAT, which the stdlib `wave`
                                          module cannot read, so we convert to PCM16)

Run from the repo root:  python -m bench.fetch_fleurs --n 25
"""
import argparse
import csv
import json
import os
import struct
import tarfile
import wave
from pathlib import Path

import httpx
import numpy as np
from huggingface_hub import hf_hub_download, hf_hub_url

REPO = "google/fleurs"
LOCALES = {"en": "en_us", "hi": "hi_in", "es": "es_419", "fr": "fr_fr", "de": "de_de"}
BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent


def read_tsv(iso: str) -> list[tuple[str, str, str]]:
    """Return (id, wav file name, raw transcription) for every row of the test split."""
    path = hf_hub_download(REPO, f"data/{LOCALES[iso]}/test.tsv", repo_type="dataset")
    rows = []
    # QUOTE_NONE: the transcriptions contain quote characters that must not be parsed
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(r) >= 3 and r[2].strip():
                rows.append((r[0], r[1], r[2].strip()))   # column 3 = raw text, as asked
    return rows


def pick_ids(tables: dict[str, list], n: int) -> dict[str, dict[str, tuple[str, str]]]:
    """Choose n ids present in every language -> {iso: {id: (wav name, text)}}.

    An id can have several recordings (different speakers); we keep one per language.
    The tar files list their wavs in file-name order, so we prefer ids whose wavs sit
    early in every tar. That lets us stop downloading early, and since the names are
    random hashes the choice is still an unbiased sample of sentences.
    """
    first, rank = {}, {}
    for iso, rows in tables.items():
        order = {name: i for i, name in enumerate(sorted(r[1] for r in rows))}
        best = {}
        for sid, wav, text in rows:
            if sid not in best or wav < best[sid][0]:
                best[sid] = (wav, text)
        first[iso] = best
        rank[iso] = {sid: order[w] for sid, (w, _) in best.items()}
    common = set.intersection(*(set(b) for b in first.values()))
    ids = sorted(common, key=lambda s: (max(rank[i][s] for i in tables), s))[:n]
    if len(ids) < n:
        print(f"warning: only {len(ids)} ids exist in all languages")
    return {iso: {s: first[iso][s] for s in ids} for iso in tables}


def to_pcm16(raw: bytes) -> tuple[bytes, int]:
    """Walk the RIFF chunks and return (int16 PCM bytes, sample rate).

    FLEURS wavs are IEEE-float32 (format tag 3); PCM16 files (tag 1) pass through.
    """
    pos, fmt, data = 12, None, b""
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])      # tag, channels, rate, _, _, bits
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)                       # chunks are padded to even sizes
    tag, channels, rate, _, _, bits = fmt
    if channels != 1:
        raise ValueError("expected mono audio")
    if tag == 3 and bits == 32:
        x = np.frombuffer(data[: len(data) // 4 * 4], dtype="<f4")
        return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes(), rate
    if tag == 1 and bits == 16:
        return data, rate
    raise ValueError(f"unsupported wav format tag={tag} bits={bits}")


class StreamFile:
    """Minimal file-like wrapper so tarfile can read an httpx streaming response."""

    def __init__(self, response: httpx.Response):
        self.chunks = response.iter_bytes(1 << 16)
        self.buf = bytearray()
        self.total = 0                      # compressed bytes downloaded so far

    def read(self, size: int = -1) -> bytes:
        while size < 0 or len(self.buf) < size:
            chunk = next(self.chunks, None)
            if chunk is None:
                break
            self.buf += chunk
            self.total += len(chunk)
        if size < 0:
            size = len(self.buf)
        out, self.buf = bytes(self.buf[:size]), self.buf[size:]
        return out


def download_wavs(iso: str, wanted: dict[str, tuple[str, str]], out_dir: Path) -> None:
    """Stream the language's tar.gz and write only the wavs we need; stop when all are found."""
    todo = {wav: sid for sid, (wav, _) in wanted.items()}       # wav name -> id
    url = hf_hub_url(REPO, f"data/{LOCALES[iso]}/audio/test.tar.gz", repo_type="dataset")
    headers = {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"} if os.getenv("HF_TOKEN") else {}
    out_dir.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        size = int(r.headers.get("content-length", 0))
        src = StreamFile(r)
        with tarfile.open(fileobj=src, mode="r|gz") as tar:     # sequential read, no seeking
            for member in tar:
                name = Path(member.name).name
                if name in todo:
                    pcm, rate = to_pcm16(tar.extractfile(member).read())
                    if rate != 16000:
                        print(f"  warning: {name} is {rate} Hz, not 16 kHz")
                    with wave.open(str(out_dir / f"{todo.pop(name)}.wav"), "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(rate)
                        w.writeframes(pcm)
                    if not todo:
                        break
    print(f"  {iso}: tar is {size / 1e6:.0f} MB, downloaded {src.total / 1e6:.0f} MB "
          f"({len(wanted) - len(todo)}/{len(wanted)} wavs)")
    if todo:
        raise SystemExit(f"{iso}: {len(todo)} wavs were not found in the archive")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=25, help="utterances per language")
    ap.add_argument("--langs", default=",".join(LOCALES), help="comma separated ISO codes")
    ap.add_argument("--out", type=Path, default=BENCH / "data")
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    bad = [l for l in langs if l not in LOCALES]
    if bad:
        raise SystemExit(f"unknown language(s) {bad}; choose from {list(LOCALES)}")

    print("reading test.tsv files ...")
    picked = pick_ids({l: read_tsv(l) for l in langs}, args.n)
    print(f"picked {len(next(iter(picked.values())))} ids shared by {', '.join(langs)}")

    manifest: dict[str, dict] = {}
    for iso in langs:
        print(f"streaming {LOCALES[iso]} ...")
        download_wavs(iso, picked[iso], args.out / iso)
        for sid, (_, text) in picked[iso].items():
            wav = args.out / iso / f"{sid}.wav"
            rel = wav.relative_to(ROOT) if wav.is_relative_to(ROOT) else wav
            manifest.setdefault(sid, {})[iso] = {"wav": str(rel), "text": text}

    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print(f"wrote {args.out / 'manifest.json'} ({len(manifest)} ids)")


if __name__ == "__main__":
    main()
