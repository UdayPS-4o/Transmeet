# Benchmarks

All numbers were measured on a **CPU-only** cloud VM (4 vCPU, x86-64, 16 GB RAM, **no GPU**) on 2026-10-27. Whisper ran int8 with greedy decoding (`BEAM_SIZE=1`); LibreTranslate was v1.6.2. Raw outputs are in [`bench/results/`](../bench/results), and the scripts are in [`bench/`](../bench).

Test data is the [FLEURS](https://huggingface.co/datasets/google/fleurs) test split: 25 read sentences per language, with an average clip of about 10 s. FLEURS is n-way parallel, so every sentence has a human reference translation in every language. That allows both transcription and translation to be scored.

## 1. Speech recognition accuracy (WER, lower is better)

| Language | `base` WER | `small` WER | `small` CER | `base` RTF | `small` RTF |
|---|---|---|---|---|---|
| English | 7.3 % | **4.7 %** | – | 0.08 | 0.20 |
| Spanish | 10.9 % | **5.1 %** | – | 0.08 | 0.19 |
| German | 15.3 % | **8.0 %** | – | 0.07 | 0.17 |
| French | 43.1 % | **15.6 %** | – | 0.11 | 0.22 |
| Hindi | 103 % (unusable) | **53.9 %** | 25.0 % | 0.16 | 0.45 |

**RTF** (real-time factor) is compute time divided by audio length. An RTF of 0.2 means a 10 s sentence is transcribed in 2 s.

Extra measurements for Hindi:

| Hindi option | WER | CER | RTF | Notes |
|---|---|---|---|---|
| `medium` (n=10) | 36.7 % | 14.9 % | 0.75 | Best quality, but too slow for 4 vCPU live use. Fine on 8+ vCPU. |
| `small` without temperature fallback | 60.6 % | 26.7 % | 0.36 | Faster worst case (0.6× real time) but less accurate. |
| `small`, token cap 20/s or 30/s | 61.1 % / 53.8 % | – | 0.37 / 0.42 | Truncated real Hindi text, so the default stays at 40 tokens/s. |

Takeaways:
- `base` is excellent for English and Spanish and about 12× faster than real time.
- Hindi needs at least `small`. Hindi WER also overstates the problem: much of the error is spelling variation, which is why CER is half of WER, and many captions are still understandable.
- This is why Transmeet defaults to `WHISPER_MODEL=base` plus `WHISPER_MODEL_BY_LANG=hi=small`.

## 2. Translation quality (BLEU / chrF, higher is better)

"Reference" translates the human transcript, so it measures LibreTranslate alone. "Cascade" translates what Whisper heard, so it measures the whole pipeline as used in a call. The cascade uses the default model per language (`base`, and `small` for Hindi).

| Pair | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT time / sentence |
|---|---|---|---|---|---|
| English → Hindi | 22.6 | 46.7 | 23.0 | 45.9 | ~0.5 s |
| Hindi → English | 25.3 | 54.8 | 4.6 | 25.2 | ~0.6 s |
| English → Spanish | 24.6 | 55.5 | 24.4 | 54.0 | ~0.5 s |
| Spanish → English | 33.2 | 63.0 | 24.3 (`small`: 30.3) | 56.3 (`small`: 60.6) | ~0.7 s |

Takeaways:
- When ASR is good (English, Spanish), the cascade loses almost nothing: captions are about as good as translating a perfect transcript.
- Hindi → English is limited by ASR, not translation. LibreTranslate scores 25 BLEU on correct Hindi text.
- For comparison, Whisper's built-in speech-to-English mode scored BLEU 8.6 with `small` and 20.1 with `medium`. Upgrading Hindi to `medium` on a bigger server is the most effective improvement.
- MT time is mostly hidden: the last interim caption has usually translated the same sentence already, so the final caption hits the cache.

## 3. Live caption latency (end of speech → caption on the listener's screen)

Measured with `bench/latency.py`. Two WebSocket clients join a room, exactly like two browsers. The speaker streams each clip in real time as 100 ms PCM frames, and the listener timestamps the arriving final caption. Clips are trimmed of silence and level-normalised (like the browser's auto-gain), with 10 utterances per pair.

### 4 vCPU (recommended size)

| Pair | Success | Mean | p50 | p95 | VAD pause | Queue | ASR | MT |
|---|---|---|---|---|---|---|---|---|
| English → Hindi | 9/10* | **1.12 s** | 1.40 s | 1.73 s | 0.62 s | 0.04 s | 0.66 s | 0.39 s |
| English → Spanish | 9/10* | **1.10 s** | 1.34 s | 1.73 s | 0.62 s | 0.04 s | 0.64 s | 0.38 s |
| Spanish → English | 10/10 | **1.84 s** | 1.80 s | 2.27 s | 0.69 s | 0.00 s | 0.73 s | 0.53 s |
| Hindi → English (`small`) | 10/10 | 5.86 s | 4.38 s | 15.7 s | 0.39 s | 0.00 s | 7.29 s | 0.77 s |

\* The one "failure" was a clip that Whisper's own VAD judged to be non-speech, so it returned an empty caption.

Interim captions appear while the person is still speaking: about 2–3 per sentence for English and Spanish. The column breakdown is approximate, because the mean and total are taken over slightly different sets of finals. See the raw JSON.

The VAD pause (`SILENCE_MS=600`) is a deliberate design cost: the system has to hear 0.6 s of silence before it knows a sentence has ended. Lowering it makes captions faster but splits sentences at natural pauses.

### 2 vCPU (smallest viable server)

This run used the same machine and code, with Transmeet and LibreTranslate both pinned to the same 2 cores.

| Pair | Success | Mean | p50 | p95 | ASR | MT | Interims / sentence |
|---|---|---|---|---|---|---|---|
| English → Hindi | 9/10* | **1.37 s** | 1.37 s | 2.17 s | 0.91 s | 0.34 s | 1.4 |
| English → Spanish | 10/10 | **1.27 s** | 1.50 s | 1.95 s | 0.99 s | 0.36 s | 1.2 |
| Spanish → English | 10/10 | **2.35 s** | 2.23 s | 2.90 s | 1.02 s | 0.74 s | 1.0 |
| Hindi → English (`small`) | 9/10 | 6.92 s | 5.64 s | 15.3 s | 8.58 s | 0.65 s | 0.1 |

With half the cores, English and Spanish captions are only about 0.2–0.5 s slower. The adaptive budget simply shows fewer live interim captions. Hindi is usable on 2 vCPU but slow. For Hindi, use 4+ vCPU, or 8 vCPU with `hi=medium` for better accuracy.

### Before and after the interim budget (4 vCPU)

The first version re-transcribed partial sentences whenever Whisper was idle. On the slower `small` model this delayed final captions. `INTERIM_BUDGET_MS` now skips an interim when its estimated cost, from the measured real-time factor, exceeds 1 s.

| Pair | Mean before | Mean after | Queue before | Queue after |
|---|---|---|---|---|
| English → Hindi | 1.42 s | 1.12 s | 0.28 s | 0.04 s |
| Spanish → English | 2.10 s | 1.84 s | 0.18 s | 0.00 s |
| Hindi → English | 6.95 s | 5.86 s | 1.44 s | 0.00 s |

## 4. Resource usage

| Component | RAM (measured) | Disk |
|---|---|---|
| Transmeet server with Whisper `base` + `small` loaded | ~1.0 GB | image 2.1 GB (both models baked in) |
| LibreTranslate, 5 languages (en, hi, es, fr, de) | ~1.1 GB | image ~2 GB + ~1.1 GB language models |
| **Total** | **~2.1 GB** | ~5.2 GB |

## 5. Browser end-to-end test

`tests/e2e.cjs` launches two headless Chromium browsers with fake cameras. Their microphones play the recordings from `tests/mic_scenario.py` (English and Hindi speech mixed with typing, a cough, fan hum and silence), and both join the same room. The test checks that:
1. the peer-to-peer WebRTC video connects on both sides (about 1 s),
2. each side receives the other's speech as a final caption, translated into its own language,
3. the captions match what was really said (the sentences in the `.json` next to each `.wav`), and
4. the "hearing you…" indicator lights up while the person speaks.

`AUTO=1` makes both people use *I speak: Auto-detect*. It passes against a local run and against the Docker image built from this repo's `Dockerfile` (started with `HF_HUB_OFFLINE=1` to prove the models are baked in). The worst case, with both fake microphones talking non-stop at the same time, is reported in section 6.

## 6. Realistic microphone test

The FLEURS clips above are clean read speech. A real laptop microphone also records keyboard typing, coughs, fan hum, long silences and room tone, and in a first round of real-microphone testing these produced captions that looked like random sentences. Two causes were found: the old energy-based VAD counted keyboard typing as speech (and merged two sentences into one caption), and a wrong *I speak* setting made Whisper write nonsense. The fixes are the Silero VAD, Auto-detect with a wrong-language hint, and warming up LibreTranslate at startup.

**Method.** `tests/mic_scenario.py` builds a recording with Piper TTS: 5 known sentences (English or Hindi) mixed with keyboard typing, a cough, 120 Hz fan hum, long silences and -55 dBFS room tone. `tests/caption_check.py` streams it to the server like a browser (16 kHz PCM, 100 ms frames, real time) and classifies every final caption as:
- **correct**: matches a spoken sentence (WER ≤ 35 %),
- **garbled**: appears at the right moment but the words are mostly wrong,
- **invented**: nothing was said at that time (typing, cough, hum, silence), so it is a hallucination.

On the VAD itself: Silero scored speech at 0.8–0.96 and keyboard, cough and fan hum at 0.21 or less, and costs 0.12 ms per 32 ms frame.

| Scenario | Correct | Invented | Notes |
|---|---|---|---|
| English, language fixed, one speaker | 5/5 | 0 | |
| Hindi, language fixed, one speaker | 5/5 | 0 | Before the VAD change: 3/5, because typing merged two sentences. The first captions also arrived about 13 s late because LibreTranslate was cold. |
| English, Auto-detect, one speaker | 5/5 | – | Captions about 1.7–2.0 s after speech |
| Hindi, Auto-detect, one speaker | 5/5 | – | |
| **Wrong language** (English speech, Hindi selected) | **0/5** | – | Nonsense such as "Torrent I and You Sour Sourts". The wrong-language hint fired after the first sentence (97 % English). |

**Worst case: both people talking at exactly the same time** (Auto-detect, server only, no browsers on the server). With `ASR_WORKERS=2` and 2 threads each, the two speakers are transcribed in parallel instead of queueing:

| Speaker | Correct | Caption latency |
|---|---|---|
| English | 5/5 | 2.1–2.4 s |
| Hindi | 5/5 | mostly 3.9–4.4 s (one sentence took 9 s, caused by Whisper's temperature-fallback retry) |

**Why 2 workers x 2 threads** (4 vCPU, Whisper compute time per sentence):

| Model | 4 threads | 2 threads | Two run in parallel, 2 threads each |
|---|---|---|---|
| `base`, English | 0.86 s | 1.07 s | 0.77 s |
| `small`, Hindi | 2.45 s | 2.39 s | 2.52 s |

These models barely speed up beyond 2 threads, so `ASR_WORKERS=2` with `WHISPER_THREADS` = CPUs / workers fills the CPU with almost no extra latency.

**Browser end-to-end** (`tests/e2e.cjs`, 2 headless Chromium on the same 4-vCPU box, both talking simultaneously, Auto-detect): English 5/5 and Hindi 5/5 captions correct, and the "hearing you…" indicator lit for both. Latency was higher than in the server-only test (English 3–5.7 s, Hindi 6–11 s) because the two browsers' 720p video encoding competes with Whisper for the same 4 cores. In real use the browsers run on the users' own devices.

Note that the latency tables in section 3 were measured before these changes, with the old VAD and a fixed language.

## How to reproduce

```bash
pip install -r requirements.txt -r bench/requirements.txt
docker run -d -p 5000:5000 -e LT_LOAD_ONLY=en,hi,es,fr,de libretranslate/libretranslate:v1.6.2 --host 0.0.0.0
python bench/fetch_fleurs.py --n 25
WHISPER_MODEL=small LT_URL=http://localhost:5000 python -m bench.accuracy --pairs en-hi,hi-en,en-es,es-en
# in another shell: start the server, then
python -m bench.latency --url ws://localhost:8000 --pairs en-hi,hi-en,en-es,es-en --n 10
```

For the realistic microphone test (section 6), install `piper-tts` and download the voices `en_US-lessac-medium` and `hi_IN-pratham-medium` from <https://huggingface.co/rhasspy/piper-voices>, then:

```bash
python tests/mic_scenario.py --voice voices/en_US-lessac-medium.onnx --lang en --out mic_en.wav
python tests/mic_scenario.py --voice voices/hi_IN-pratham-medium.onnx --lang hi --out mic_hi.wav
python tests/caption_check.py --url ws://localhost:8000 --wav mic_en.wav [--speaker-lang auto|hi] [--caption-lang hi]
AUTO=1 node tests/e2e.cjs http://localhost:8000 mic_en.wav mic_hi.wav
```
