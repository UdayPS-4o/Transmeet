# Transmeet benchmarks

Run everything from the repo root with the project's Python environment
(`pip install -r bench/requirements.txt` on top of the app requirements).

## 1. Get test data

```
python -m bench.fetch_fleurs --n 25
```

Downloads 25 FLEURS test sentences per language (en, hi, es, fr, de) into
`bench/data/<lang>/<id>.wav` and writes `bench/data/manifest.json`. The same id is the
same sentence in every language, so it also gives reference translations. Only the wavs
we need are pulled out of the ~250-300 MB tar files (streamed, stops early). Use
`--langs en,hi` to fetch fewer languages. `bench/data/` is git-ignored.

## 2. Accuracy (offline, no server needed except LibreTranslate)

```
WHISPER_MODEL=base LT_URL=http://localhost:5000 python -m bench.accuracy
```

* `MODEL_DIR` is the Whisper `download_root` (defaults to `~/.cache/huggingface/hub`).
* `--pairs en-hi,hi-en,en-es,es-en` picks the translation directions, `--n` caps utterances.
* Prints a markdown table and writes `bench/results/accuracy-<model>.json` and `.md`.
* ASR: WER (plus CER for Hindi) after lowercasing, removing punctuation and collapsing spaces,
  mean ASR time and real-time factor (decode time / audio time, lower is faster).
* MT: BLEU and chrF (sacreBLEU) against the FLEURS text of the target language, once for the
  reference source text and once for the ASR output (the cascade the app really runs).

## 3. Live latency (needs the server running)

Start the server (e.g. `WHISPER_MODEL=base uvicorn app.main:app --port 8000`), then:

```
python -m bench.latency --url ws://localhost:8000 --pairs en-hi,hi-en --n 10
```

Two WebSocket clients join one room: the speaker streams each wav in real time (100 ms frames,
then 1.5 s of silence) and the listener times the first final caption. Latency is measured from
the last audio frame sent, so it includes the server's `SILENCE_MS` wait and any silence at the
end of the recording. One extra warm-up utterance per pair is sent first and not counted
(`--warmup 0` to disable); utterances with no final caption after 20 s count as timeouts.
Results go to `bench/results/latency-<model>.json` and `.md`.
The run takes about `pairs * (n + 1) * (clip length + 1.5 s)` seconds, since audio is real time.

Repeat steps 2 and 3 with other `WHISPER_MODEL` values (tiny, base, small) to compare them.
