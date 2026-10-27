# Transmeet

**WebRTC video calls with live speech translation and captions. Fully self-hosted, runs on CPU.**

Two people join a room. Each picks the language they speak (or leaves it on Auto-detect) and the language they want captions in. As someone talks, their speech is transcribed by Whisper and translated by LibreTranslate. The caption appears on the other person's screen about 1–2 seconds after they stop speaking (measured on a 4-vCPU server with no GPU). Everything runs on your own server: no paid APIs, no GPU, and no audio leaves the machine.

```
 Browser A (speaks English)                                   Browser B (reads Hindi)
 ┌──────────────────────┐        WebRTC (peer-to-peer)        ┌──────────────────────┐
 │ camera + mic ────────┼──────────── video / audio ─────────────┼──► remote video       │
 │                      │                                        │                      │
 │ AudioWorklet         │                                        │ captions overlay     │
 │ 48k → 16 kHz PCM ──┐ │                                        │ + transcript    ▲    │
 └────────────────────┼─┘                                        └─────────────────┼────┘
                      │ WebSocket /ws/<room>                                        │
                      │ (binary audio + JSON signalling)       caption JSON         │
                      ▼                                                             │
   ┌─────────────────────────────── Transmeet server (FastAPI) ─────────────────────┼──┐
   │  VAD (Silero, neural) ───► faster-whisper (int8, CPU) ──► LibreTranslate ──────┘  │
   │  cut at 600 ms pause         "Hello, how are you?"         "नमस्ते, आप कैसे हैं?"     │
   │  + interim captions while speaking                         (one call per target   │
   │                                                             language in the room)  │
   └────────────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **1:1 video calls** over WebRTC (peer-to-peer media; the server only relays signalling).
- **Live captions in each viewer's own language.** Each participant chooses *I speak* and *Show captions in*, and can change either mid-call.
- **Auto-detect language (default).** *I speak: Auto-detect* works out the spoken language for every sentence, so nobody has to get the setting right. Pick a language explicitly to skip the detection step (about 0.4–0.5 s on CPU).
- **Wrong-language hint.** If a language is fixed but the first sentences sound like another offered language, the speaker sees "You selected X, but it sounds like you are speaking Y" with a one-click switch.
- **Noise-robust speech detection.** A neural VAD (Silero) tells a voice from keyboard typing, a cough or fan hum, so noise does not become captions and two sentences are not merged.
- **Microphone feedback.** A microphone picker in the lobby, a live mic level (green ring on the mic button), a "hearing you…" badge on your own video when the server hears speech, and a "speaking…" tag on the other person's name. Plain-language banners explain when you are muted, the mic is silent for 10 s, audio is not reaching the server, or the mic was disconnected.
- **Interim captions** appear while the speaker is still talking. The final, translated caption replaces them after a pause.
- **Transcript panel** shows both the original and the translation, with a per-caption latency breakdown (pause + queue + ASR + MT). It can be downloaded as `.txt`.
- **Measured latency.** `/api/stats` returns mean, p50 and p95 for every pipeline stage. `bench/` contains reproducible accuracy (WER, BLEU, chrF) and end-to-end latency benchmarks.
- **Per-language model choice.** For example, English can use fast `base` while Hindi uses `small` (`WHISPER_MODEL_BY_LANG=hi=small`).
- **Single domain, single public port.** UI, signalling, audio and API all share one HTTPS origin, so it deploys as one Dokploy Compose app.
- If the peer-to-peer video is blocked by a strict NAT, **captions still work**, because they travel over the server WebSocket.

## Languages

Defaults: English, Hindi, Spanish, French, German (`LANGUAGES=en,hi,es,fr,de`). Any language that both Whisper and LibreTranslate support can be added, for example `it, pt, ru, ja, ko, zh, ar, bn, ur, tr`. Each extra language adds roughly 200–300 MB of LibreTranslate RAM.

## Does it run without a GPU?

Yes. Transmeet is designed for CPU. Whisper runs through CTranslate2 with int8 quantisation, and LibreTranslate (Argos) is CPU-only. These numbers were **measured** on a cloud VM with no GPU. Latency is from end of speech to the caption on the other screen; full tables are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

| Server | English/Spanish captions | Hindi → English captions | Verdict |
|---|---|---|---|
| **2 vCPU / 4 GB** | 1.3–2.3 s | ~7 s (p50 5.6 s) | Fine for a demo with European languages. Hindi works but is slow. |
| **4 vCPU / 8 GB** (recommended) | 1.1–1.8 s | ~6 s (p50 4.4 s) | Smooth for the default `base` + `hi=small` setup |
| 8 vCPU / 16 GB | – (not measured) | – | Room for `hi=medium` (Hindi WER 54 % → 37 %) or `small` for everyone |

Measured RAM: about 1.0 GB for Transmeet with `base` and `small` loaded, and about 1.1 GB for LibreTranslate with 5 languages, so about **2.1 GB in total**. Disk is about 5 GB (Transmeet image 2.1 GB with models baked in, LibreTranslate image about 2 GB, and its language models 1.1 GB).

Measured accuracy (FLEURS, word error rate): English 7.3 % (`base`) or 4.7 % (`small`), Spanish 10.9 % or 5.1 %, German 15.3 % or 8.0 %, Hindi 54 % (`small`; character error rate 25 %). On short everyday sentences, English/Spanish captions are essentially correct. Hindi captions are understandable but imperfect.

A GPU is optional. With `WHISPER_DEVICE=cuda`, `WHISPER_COMPUTE=float16` and a CUDA base image, `medium` or `large-v3` run in real time.

## Quick start (local)

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
# open http://localhost:8000 in two browser windows (or two devices) and press Join on both:
# a blank room code means the shared "main" room, and the name is optional
```

The first start downloads the LibreTranslate language models, which takes about 1–3 minutes. Until then, the app shows "translator loading…" and captions appear untranslated.

Without Docker (for development):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
docker run -d -p 5000:5000 -e LT_LOAD_ONLY=en,hi,es,fr,de libretranslate/libretranslate:v1.6.2 --host 0.0.0.0
MODEL_DIR=./models LT_URL=http://localhost:5000 uvicorn app.main:app --port 8000
```

## Deploying on Dokploy (one domain)

1. **Create → Compose** in your Dokploy project. Set the source to this Git repository (branch `main`) and the compose path to `./docker-compose.yml`.
2. **Environment** (optional), for example:
   ```env
   WHISPER_MODEL=base
   WHISPER_MODEL_BY_LANG=hi=small
   LANGUAGES=en,hi,es,fr,de
   ```
3. **Domains → Add Domain**: service `transmeet`, port `8000`, path `/`, HTTPS on with Let's Encrypt. This is the only domain needed. LibreTranslate is never exposed.
4. **Deploy.** The first build takes a few minutes. Open `https://your-domain`, create a room, and send the invite link.

Notes:
- **HTTPS is required.** Browsers only allow camera and microphone on `https://` or `localhost`. Dokploy's Let's Encrypt handles this.
- **WebSockets** (`/ws/...`) pass through Dokploy's Traefik without extra configuration. If Safari or Firefox fail to connect the WebSocket on a very new Traefik (an HTTP/2 extended-CONNECT issue), set `http2.maxConcurrentStreams: 0` on the `websecure` entrypoint or update Dokploy.
- **TURN (optional).** Most networks connect peer-to-peer using the public STUN servers. Some strict networks (some campus Wi-Fi, mobile carriers) need a TURN relay for the *video*. Set `TURN_URLS=turn:turn.example.com:3478`, `TURN_USERNAME` and `TURN_CREDENTIAL` to use one. Captions work either way.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WHISPER_MODEL` | `base` | `tiny`, `base`, `small`, `medium`, … (multilingual models) |
| `WHISPER_MODEL_BY_LANG` | – | Per-language override, e.g. `hi=small,ja=small` |
| `WHISPER_COMPUTE` | `int8` | CTranslate2 precision (`int8` is fastest on CPU) |
| `WHISPER_THREADS` | `0` (auto) | CPU threads per transcription. Auto = number of CPUs / `ASR_WORKERS` (2 threads each on 4 vCPU). |
| `ASR_WORKERS` | `2` | Transcriptions run in parallel, so both people in a call are transcribed at the same time. |
| `BEAM_SIZE` | `1` | 1 = greedy (fast). 5 = Whisper default (slower, slightly more accurate). |
| `SILENCE_MS` | `600` | Pause that ends a sentence. Lower is faster but cuts more often. |
| `MAX_SEGMENT_S` | `10` | Long monologues are cut at this length. |
| `INTERIM` / `INTERIM_MS` | `true` / `1200` | Live partial captions and how often to refresh them |
| `INTERIM_BUDGET_MS` | `1000` | Skip an interim whose estimated Whisper time exceeds this (protects final-caption latency on slow models) |
| `LANGUAGES` | `en,hi,es,fr,de` | Offered languages. Also the languages LibreTranslate loads. |
| `LT_URL` / `LT_API_KEY` | `http://libretranslate:5000` | LibreTranslate endpoint |
| `MAX_PEERS` | `2` | People per room |
| `LOG_TRANSCRIPTS` | `false` | Write caption text to server logs (off by default for privacy) |
| `STUN_URLS`, `TURN_URLS`, `TURN_USERNAME`, `TURN_CREDENTIAL` | Google STUN | ICE servers |

## Project structure

```
app/
  main.py          FastAPI app: rooms, WebSocket signalling, caption pipeline, /api
  vad.py           streaming voice-activity detector / segmenter (Silero VAD, frame by frame)
  asr.py           faster-whisper wrapper (+ hallucination and repetition filters)
  translate.py     LibreTranslate client with LRU cache
  config.py        all settings from environment variables
  static/          UI: index.html, style.css, app.js, pcm-worklet.js (no build step)
bench/             FLEURS download, accuracy (WER/BLEU/chrF) and live latency benchmarks
tests/
  e2e.cjs          two headless Chromium browsers in one call (Playwright); checks captions match what was said
  mic_scenario.py  builds a realistic laptop-mic recording (Piper TTS + typing, cough, hum, silence) with known text
  caption_check.py streams that recording to the server and scores every caption: correct / garbled / invented
docs/              benchmark results, related work
Dockerfile, docker-compose.yml
```

## How the caption pipeline works

1. **Capture.** An `AudioWorklet` downsamples the mic (after the browser's echo cancellation and noise suppression) to 16 kHz mono 16-bit PCM. It sends 100 ms binary frames over the WebSocket, about 32 KB/s.
2. **Segment.** The server splits the audio into 32 ms frames (512 samples) and scores each with Silero VAD, a small neural network (the ONNX model bundled with faster-whisper), carrying its recurrent state between frames. Speech starts when the probability is at least 0.5 for 3 frames (about 100 ms) and a frame counts as non-speech below 0.35. An utterance ends after `SILENCE_MS` of non-speech, or at `MAX_SEGMENT_S`. 300 ms of pre-roll keeps the first syllable, and frames quieter than RMS 0.002 skip the network. The cost is about 0.12 ms per frame. Silero scores speech at 0.8–0.96 and keyboard, cough and fan hum at 0.21 or less. The server also tells the room when someone starts or stops speaking (`speaking` message), which drives the "hearing you…" badge.
3. **Interim.** While someone is speaking, the server re-transcribes the partial utterance about every 1.2 s with greedy decoding, so text appears live. Interims are skipped when all Whisper workers are busy, because final captions take priority on a small CPU. With Auto-detect, interims wait until the first sentence has been detected.
4. **Detect language and recognise.** If the speaker chose a language, it is used as is. With *Auto-detect*, Whisper `base` detects the language of each sentence (`detect_language`), Urdu probability is merged into Hindi, and the best of the offered `LANGUAGES` wins. That language's model then transcribes (for example `small` for Hindi). The choice is sticky: if confidence is below 0.6 or the sentence is shorter than 1.5 s, the speaker's previous language is kept. When a language is fixed, the first 2 sentences are also checked in the background and a wrong-language hint is sent if another offered language is at least 0.7 likely. Silero VAD inside faster-whisper trims non-speech. Known Whisper hallucinations ("Thanks for watching") and repetition loops are filtered out.
5. **Translate.** One LibreTranslate request runs for each distinct caption language in the room, and results are cached. LibreTranslate loads its models lazily, so the server warms them up at startup; otherwise the first caption stalls for about 13–15 s.
6. **Deliver.** Each participant receives the original text, the translation in their own caption language, and the timing breakdown.

## Testing and benchmarks

```bash
# end-to-end: two real browsers, fake camera, recorded speech as the microphone
node tests/e2e.cjs http://localhost:8000 mic_en.wav mic_hi.wav        # fixed languages
AUTO=1 node tests/e2e.cjs http://localhost:8000 mic_en.wav mic_hi.wav # both use Auto-detect

# accuracy (FLEURS test set) and live latency; see bench/README.md
pip install -r bench/requirements.txt
python bench/fetch_fleurs.py --n 25
python -m bench.accuracy --pairs en-hi,hi-en,en-es,es-en
python -m bench.latency --url ws://localhost:8000 --pairs en-hi,hi-en --n 10
```

### Realistic microphone test

FLEURS clips are clean. A real laptop mic also records typing, coughs, fan hum and silence, which is what makes Whisper invent sentences. `tests/mic_scenario.py` builds such a recording from 5 known sentences (Piper TTS) mixed with keyboard typing, a cough, 120 Hz fan hum, long silences and -55 dBFS room tone. It writes a `.wav` and a `.json` with the sentences. `tests/caption_check.py` streams the `.wav` to the server like a browser and classifies every caption as **correct** (WER ≤ 35 %), **garbled** (right moment, wrong words) or **invented** (a hallucination during noise).

```bash
pip install piper-tts jiwer websockets
# voices: https://huggingface.co/rhasspy/piper-voices (each needs the .onnx and the .onnx.json)
#   en_US-lessac-medium and hi_IN-pratham-medium, saved in voices/
python tests/mic_scenario.py --voice voices/en_US-lessac-medium.onnx --lang en --out mic_en.wav
python tests/mic_scenario.py --voice voices/hi_IN-pratham-medium.onnx --lang hi --out mic_hi.wav

python tests/caption_check.py --url ws://localhost:8000 --wav mic_en.wav
python tests/caption_check.py --url ws://localhost:8000 --wav mic_hi.wav --caption-lang en
python tests/caption_check.py --wav mic_en.wav --speaker-lang auto   # test Auto-detect
python tests/caption_check.py --wav mic_en.wav --speaker-lang hi     # wrong setting: expect a language hint
```

`mic_en.wav` and `mic_hi.wav` also work as the microphones for `tests/e2e.cjs`.

Results are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). Comparable systems are surveyed in [docs/RELATED_WORK.md](docs/RELATED_WORK.md).

## Troubleshooting: captions don't match what I said

1. **Wrong "I speak" language.** If a language is fixed but you speak another, Whisper writes nonsense (English speech with Hindi selected produced "Torrent I and You Sour Sourts"). Use **Auto-detect**, or click the switch in the "You selected X, but it sounds like you are speaking Y" banner.
2. **Wrong microphone.** Pick the right one in the lobby's *Microphone* list and check that the lobby meter or the green ring on the mic button moves when you talk. The "We can't hear anything from your microphone" banner appears after 10 s of silence.
3. **Is the server hearing you?** A "hearing you…" badge should appear on your own video while you speak. If it does not, the audio is not reaching the server or your voice is too quiet; check the banner, and that you are not muted.
4. Hindi is less accurate than English. This is a limit of the Whisper `small` model (see the accuracy table in [docs/BENCHMARKS.md](docs/BENCHMARKS.md)); captions are usually understandable but imperfect.

## Limitations and future work

- Two people per room (peer-to-peer mesh). Multi-party calls would need an SFU (e.g. mediasoup or LiveKit) and an ASR worker for each speaker.
- Captions are sentence-level. True simultaneous translation, which emits words before the sentence ends (e.g. SimulStreaming), needs much more compute.
- Accuracy depends on model size. Low-resource languages need `small` or larger.
- Rooms are held in memory, so run one server replica.
- Possible extensions: TTS voice-over of translations, speaker diarisation, and saving meeting minutes.

## Licence

Transmeet's own code is MIT-licensed (see `LICENSE`). It uses, unmodified and as separate components: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), OpenAI Whisper model weights (MIT), [LibreTranslate](https://github.com/LibreTranslate/LibreTranslate) (AGPL-3.0, run as its own container), and [Argos Translate](https://github.com/argosopentech/argos-translate) models.
