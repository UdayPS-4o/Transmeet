# Transmeet

**WebRTC video calls with live speech translation and captions. Fully self-hosted, runs on CPU.**

Two people join a room. Each picks the language they speak and the language they want captions in. As someone talks, their speech is transcribed by Whisper and translated by LibreTranslate. The caption appears on the other person's screen about 1–3 seconds after they stop speaking. Everything runs on your own server: no paid APIs, no GPU, and no audio leaves the machine.

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
   │  VAD (energy, adaptive) ──► faster-whisper (int8, CPU) ──► LibreTranslate ──────┘  │
   │  cut at 600 ms pause         "Hello, how are you?"         "नमस्ते, आप कैसे हैं?"     │
   │  + interim captions while speaking                         (one call per target   │
   │                                                             language in the room)  │
   └────────────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **1:1 video calls** over WebRTC (peer-to-peer media; the server only relays signalling).
- **Live captions in each viewer's own language.** Each participant chooses *I speak* and *Show captions in*, and can change either mid-call.
- **Interim captions** appear while the speaker is still talking. The final, translated caption replaces them after a pause.
- **Transcript panel** shows both the original and the translation, with a per-caption latency breakdown (pause + queue + ASR + MT). It can be downloaded as `.txt`.
- **Measured latency.** `/api/stats` returns mean, p50 and p95 for every pipeline stage. `bench/` contains reproducible accuracy (WER, BLEU, chrF) and end-to-end latency benchmarks.
- **Per-language model choice.** For example, English can use fast `base` while Hindi uses `small` (`WHISPER_MODEL_BY_LANG=hi=small`).
- **Single domain, single public port.** UI, signalling, audio and API all share one HTTPS origin, so it deploys as one Dokploy Compose app.
- If the peer-to-peer video is blocked by a strict NAT, **captions still work**, because they travel over the server WebSocket.

## Languages

Defaults: English, Hindi, Spanish, French, German (`LANGUAGES=en,hi,es,fr,de`). Any language that both Whisper and LibreTranslate support can be added, for example `it, pt, ru, ja, ko, zh, ar, bn, ur, tr`. Each extra language adds roughly 200–300 MB of LibreTranslate RAM.

## Does it run without a GPU?

Yes. Transmeet is designed for CPU. Whisper runs through CTranslate2 with int8 quantisation, and LibreTranslate (Argos) is CPU-only. The figures below were measured on a 4-vCPU server; full tables are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

| Server | Setting | What to expect |
|---|---|---|
| **2 vCPU / 4 GB** | `WHISPER_MODEL=base`, `LANGUAGES=en,es` (2–3 langs) | Usable demo. Captions about 2–3 s after speech. |
| **4 vCPU / 8 GB** (recommended) | `base` + `WHISPER_MODEL_BY_LANG=hi=small` | Smooth 1:1 call including Hindi. |
| 8 vCPU / 16 GB | `small` for everyone | Best accuracy that is still comfortably real time. |

RAM, roughly: Transmeet with `base` uses about 0.5 GB, plus about 1 GB more for `small`. LibreTranslate uses about 1.5–2 GB with 5 languages. Docker images are about 1.2 GB (Transmeet) and about 2 GB (LibreTranslate), plus about 1 GB of downloaded language models.

A GPU is optional. Set `WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE=float16` on a CUDA host to use a larger model such as `medium` in real time. This also needs a CUDA base image.

## Quick start (local)

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
# open http://localhost:8000 in two browser windows (or two devices), same room code
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
| `WHISPER_THREADS` | `0` (auto) | CPU threads used by Whisper |
| `ASR_WORKERS` | `1` | Transcriptions run in parallel. Use 2 on 8+ cores. |
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
  vad.py           streaming energy-based voice-activity detector / segmenter
  asr.py           faster-whisper wrapper (+ hallucination and repetition filters)
  translate.py     LibreTranslate client with LRU cache
  config.py        all settings from environment variables
  static/          UI: index.html, style.css, app.js, pcm-worklet.js (no build step)
bench/             FLEURS download, accuracy (WER/BLEU/chrF) and live latency benchmarks
tests/e2e.cjs      two headless Chromium browsers in one call (Playwright)
docs/              benchmark results, related work
Dockerfile, docker-compose.yml
```

## How the caption pipeline works

1. **Capture.** An `AudioWorklet` downsamples the mic (after the browser's echo cancellation and noise suppression) to 16 kHz mono 16-bit PCM. It sends 100 ms binary frames over the WebSocket, about 32 KB/s.
2. **Segment.** The server splits the audio into 30 ms frames and compares each frame's RMS energy with an adaptive noise floor. An utterance starts after 90 ms of voice and ends after `SILENCE_MS` of quiet, or at `MAX_SEGMENT_S`.
3. **Interim.** While someone is speaking, the server re-transcribes the partial utterance about every 1.2 s with greedy decoding, so text appears live. Interims are skipped whenever Whisper is busy, because final captions take priority on a small CPU.
4. **Recognise.** The finished utterance goes to faster-whisper with the speaker's language fixed, which skips language detection and avoids mistakes. Silero VAD inside faster-whisper trims non-speech. Known Whisper hallucinations ("Thanks for watching") and repetition loops are filtered out.
5. **Translate.** One LibreTranslate request runs for each distinct caption language in the room, and results are cached.
6. **Deliver.** Each participant receives the original text, the translation in their own caption language, and the timing breakdown.

## Testing and benchmarks

```bash
# end-to-end: two real browsers, fake camera, recorded speech as the microphone
node tests/e2e.cjs http://localhost:8000 english.wav hindi.wav

# accuracy (FLEURS test set) and live latency; see bench/README.md
pip install -r bench/requirements.txt
python bench/fetch_fleurs.py --n 25
python -m bench.accuracy --pairs en-hi,hi-en,en-es,es-en
python -m bench.latency --url ws://localhost:8000 --pairs en-hi,hi-en --n 10
```

Results are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). Comparable systems are surveyed in [docs/RELATED_WORK.md](docs/RELATED_WORK.md).

## Limitations and future work

- Two people per room (peer-to-peer mesh). Multi-party calls would need an SFU (e.g. mediasoup or LiveKit) and an ASR worker for each speaker.
- Captions are sentence-level. True simultaneous translation, which emits words before the sentence ends (e.g. SimulStreaming), needs much more compute.
- Accuracy depends on model size. Low-resource languages need `small` or larger.
- Rooms are held in memory, so run one server replica.
- Possible extensions: TTS voice-over of translations, speaker diarisation, and saving meeting minutes.

## Licence

Transmeet's own code is MIT-licensed (see `LICENSE`). It uses, unmodified and as separate components: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), OpenAI Whisper model weights (MIT), [LibreTranslate](https://github.com/LibreTranslate/LibreTranslate) (AGPL-3.0, run as its own container), and [Argos Translate](https://github.com/argosopentech/argos-translate) models.
