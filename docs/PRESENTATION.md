# Transmeet: presentation kit

Contents: (1) slide-by-slide outline with speaker notes, (2) viva / Q&A prep, (3) glossary.
Code references are `file:line` in this repository. Results slide numbers come from `docs/BENCHMARKS.md`, which is still being produced, so no figures are quoted here.

---

## Part 1. Slide outline

### Slide 1. Title
- **Transmeet: self-hosted video calls with live speech-translation captions**
- Your name, guide, department, date
- One-line tagline: "WebRTC + Whisper + LibreTranslate, on a CPU, with no paid API"

*Notes:* Introduce yourself and the one-sentence pitch: two people speak different languages, each reads captions in their own. Say upfront that you will demo it live.

### Slide 2. Problem and motivation
- Language differences block remote study, work and community meetings
- Zoom, Google Meet and Teams translated captions are paid-tier and cloud-only (RELATED_WORK #10-12)
- Open-source options mostly lack integrated multilingual support
- Workaround today: copy text into an external translator, which breaks the flow of conversation
- Gap: an affordable, self-hostable option for students and small teams

*Notes:* Quote the abstract's gap statement. Stress "affordable and self-hosted", not "better than Zoom".

### Slide 3. Objectives (mapped to the abstract)
| Abstract promise | Where it is delivered |
|---|---|
| WebRTC peer-to-peer video/audio | `app.js` `startPeer`, server only relays signalling (`main.py`) |
| Streaming Whisper ASR (local) | `asr.py` faster-whisper, utterance segmentation plus interim captions |
| Self-hosted LibreTranslate | `translate.py`, separate container |
| WebSocket caption loop | `/ws/{room}` carries audio in and captions out (`main.py`) |
| Two-person calls | `MAX_PEERS=2` (`config.py`, `main.py`) |
| At least two language pairs | Default five languages: en, hi, es, fr, de |
| Latency and accuracy benchmarks | `/api/stats`, `bench/accuracy.py`, `bench/latency.py` |

*Notes:* Walk the table left to right. Be honest on one row: "streaming" here means segmentation plus partial re-transcription, not token-level incremental decoding (slide 7).

### Slide 4. Related work (honest summary)
- Closest prior art: **voice-bridge**, a hobby project with WebRTC, WebSocket PCM, VAD, faster-whisper and Argos/Google Translate
- Others cover only part of the problem: WhisperLive and Skynet (ASR only), Jigasi (heavy Jitsi stack), LiveKit Agents (cloud STT in docs), meet-translate (paid APIs), SimulStreaming (wants a GPU, CPU too slow)
- Commercial: Zoom (~$5/user/month add-on), Meet and Teams (premium tiers)
- **What Transmeet adds over voice-bridge:** independent implementation with per-viewer caption language, interim captions, per-stage latency instrumentation, a reproducible benchmark suite, and one-domain Docker deployment
- **What it does not claim:** a new algorithm. The contribution is integration, measurement and deployability.

*Notes:* Say plainly that voice-bridge exists and the architecture is similar. The differentiators are engineering and evaluation, not novelty of idea.

### Slide 5. System architecture
- Browser A and B: camera/mic, WebRTC peer connection, AudioWorklet, caption overlay
- Server (FastAPI, one process, one port): signalling, VAD, faster-whisper, LibreTranslate client, stats
- LibreTranslate: private container, never exposed publicly
- Two planes: **media plane** (P2P video/audio) and **caption plane** (WebSocket through server)

```mermaid
flowchart LR
  subgraph A[Browser A - speaker]
    MIC[Mic] --> WK[AudioWorklet 16 kHz PCM]
  end
  subgraph S[Transmeet server - FastAPI]
    WS[/ws/room/] --> VAD[Silero VAD] --> ASR[faster-whisper int8] --> MT[LibreTranslate client]
  end
  LT[(LibreTranslate container)]
  subgraph B[Browser B - listener]
    CAP[Caption overlay]
  end
  WK -- binary PCM --> WS
  MT <--> LT
  MT -- caption JSON in B's language --> CAP
  A <-. WebRTC video/audio, P2P .-> B
```

*Notes:* Point out that video never touches the server; only a 16 kHz copy of the mic does. This is why captions survive a blocked P2P link.

### Slide 6. Life of one caption (sequence diagram)

```mermaid
sequenceDiagram
  participant Mic as Speaker mic
  participant WK as AudioWorklet (browser)
  participant WS as WebSocket /ws/room
  participant VAD as Segmenter (VAD)
  participant W as faster-whisper
  participant LT as LibreTranslate
  participant L as Listener browser
  Mic->>WK: 48 kHz audio (echo-cancelled)
  WK->>WS: 100 ms frames, 16 kHz int16 PCM
  WS->>VAD: 32 ms frames, Silero speech probability
  Note over VAD: speech starts after 3 frames (~100 ms) with p >= 0.5
  VAD-->>W: interim audio every ~1.2 s (skipped if all workers busy)
  W-->>LT: interim text
  LT-->>L: interim caption (grey, "...")
  Note over VAD: 600 ms of quiet ends the utterance
  VAD->>W: final utterance (Auto-detect: language detected first)
  W->>LT: text, one request per caption language in room
  LT->>WS: translated text
  WS->>L: final caption + timings (pause, queue, ASR, MT)
```

*Notes:* Narrate once, slowly. Mention the timings object returned with every final caption, which is how latency is measured in the app itself.

### Slide 7. Module: capture and VAD
- **AudioWorklet** (`pcm-worklet.js`): box-filter downsample 48 kHz to 16 kHz, int16, posts 1600-sample (100 ms) chunks, about 32 KB/s
- **Segmenter** (`vad.py`): 32 ms frames (`FRAME=512`, what Silero expects at 16 kHz) scored by **Silero VAD**, the neural ONNX model bundled with faster-whisper. It runs frame by frame, carrying its recurrent state (h, c) and a 64-sample context between frames
- **Why not energy:** the earlier energy/RMS VAD with an adaptive noise floor counted keyboard typing as speech and merged two sentences into one caption. Silero scores speech at 0.8-0.96 and keyboard, cough and fan hum at 0.21 or less
- **Start rule:** speech probability >= 0.5 (`START_PROB`) for 3 frames (`START_FRAMES`, ~100 ms), with 300 ms pre-roll so the first syllable is kept
- **Hysteresis:** a frame counts as non-speech only below 0.35 (`END_PROB`); between 0.35 and 0.5 nothing changes
- **End rule:** `SILENCE_MS` = 600 ms of non-speech, or forced cut at `MAX_SEGMENT_S` = 10 s; utterances with under 250 ms of speech are discarded
- **Cost:** 0.12 ms per frame measured; frames quieter than RMS 0.002 skip the network
- The VAD state is also sent to the room (`speaking` message), which drives the "hearing you..." badge and the "speaking..." tag
- Trade-off: lower SILENCE_MS gives faster captions but cuts sentences at natural pauses

*Notes:* "Streaming ASR" in this project means VAD-driven utterance chunking plus interim captions. Say this yourself before an examiner does.

### Slide 8. Module: ASR (Whisper)
- faster-whisper (CTranslate2), **int8** on CPU, greedy decoding by default (`BEAM_SIZE=1`)
- **Language:** either fixed by the speaker's setting, or **Auto-detect** (the default): per sentence, Whisper `base` runs `detect_language` (~0.4-0.5 s on CPU, since Whisper pads to 30 s), Urdu probability is merged into Hindi, and the best of the offered `LANGUAGES` picks the model (`asr.py`, `main.py`). It is sticky: below 0.6 confidence or under 1.5 s of audio, the speaker's previous language is kept
- **Wrong-language hint:** with a fixed language, the first 2 sentences are checked; if they sound like another offered language with p >= 0.7, the speaker gets a banner with a one-click switch (`main.py`)
- **Parallel workers:** `ASR_WORKERS=2`, each with `WHISPER_THREADS` = CPUs / workers, so both speakers are transcribed at once
- **Per-language model:** `WHISPER_MODEL_BY_LANG=hi=small` so only Hindi pays for the larger model (`asr.py`)
- **Interim vs final:** interims are greedy re-transcriptions of the utterance so far, first at 1 s and then every 1.2 s; finals allow one retry at temperature 0.4 (`asr.py`)
- **Interims are skipped when all Whisper workers are busy** (`main.py`) because finals must not queue behind throwaway text on a small CPU
- **Filters:** drops low-confidence segments (`no_speech_prob > 0.6` and `avg_logprob < -1.0`), regex for known hallucinations ("thanks for watching"), and `collapse_repeats` for loops of 1-3 word units

*Notes:* Explain the busy rule as a priority policy: correctness of final captions beats freshness of partial ones.

### Slide 9. Module: translation and fan-out
- LibreTranslate (Argos models) over HTTP, async `httpx` client (`translate.py`)
- **Per-viewer fan-out:** the server collects the distinct caption languages in the room, translates once per language, and sends each viewer their own (`main.py`, `main.py`)
- LRU cache of 2000 sentences keyed by (source, target, text)
- Small fix-ups: strips the stray "." Argos adds after a Hindi danda (`translate.py`)
- If translation fails, the client shows the original text with "(translation unavailable)" instead of nothing

*Notes:* Fan-out is trivial with two people but the code is already per-language, not per-pair, so it generalises.

### Slide 10. Instrumentation and WebRTC
- Every final caption carries `audioMs, vadMs, queueMs, asrMs, mtMs, totalMs` (`main.py`)
- `/api/stats` returns mean, p50, p95 per stage plus ASR real-time factor (`main.py`)
- Transcript panel shows the breakdown live
- WebRTC: newcomer sends the offer, ICE candidates relayed over the same WebSocket; STUN by default, TURN optional via env (`config.py`)
- Connection state `failed` shows "media blocked by network (captions still work)" (`app.js`)

*Notes:* Instrumentation is what makes the latency claim defensible: you can show where every millisecond went.

### Slide 11. Tech stack and deployment
| Layer | Choice |
|---|---|
| Browser | WebRTC, AudioWorklet, WebSocket, vanilla JS (no build step) |
| Server | Python, FastAPI, uvicorn, NumPy, httpx |
| ASR | faster-whisper 1.2.1 on CTranslate2, int8, Whisper `base` (`small` for Hindi) |
| MT | LibreTranslate v1.6.2 (Argos), AGPL-3.0, separate container |
| Packaging | Docker Compose, one public service on port 8000 |
| Host | Dokploy with Traefik and Let's Encrypt, one domain |

- Only `transmeet` is public; LibreTranslate stays on the private network
- **HTTPS is mandatory:** browsers allow camera/mic only on `https://` or `localhost`, and `wss://` follows from it
- Whisper `base` and `small` are baked into the image; other sizes download to a volume
- LibreTranslate is warmed up at startup, because it loads models lazily and the first caption otherwise stalls ~13-15 s
- One uvicorn worker because rooms are in memory and Whisper already uses all cores (`Dockerfile`)

*Notes:* If asked "why a single domain", the answer is simpler TLS, no CORS, and the WebSocket and API share the page's origin.

### Slide 12. Results
All measured on a CPU-only 4-vCPU VM. Details are in docs/BENCHMARKS.md.

| Metric | English | Spanish | Hindi |
|---|---|---|---|
| ASR WER, `base` / `small` | 7.3 % / 4.7 % | 10.9 % / 5.1 % | 103 % / 53.9 % (CER 25 %) |
| ASR speed (`base` / `small`) | 12× / 5× faster than real time | 13× / 5× | 6× / 2.2× |
| Caption latency, end of speech → screen (mean) | en→hi **1.1 s**, en→es **1.1 s** | es→en **1.8 s** | hi→en 5.9 s (p50 4.4 s) |
| Same on only 2 vCPU | 1.3–1.4 s | 2.3 s | 6.9 s |
| MT BLEU, perfect transcript / live cascade | en→hi 22.6 / 23.0 | es→en 33.2 / 24.3 | hi→en 25.3 / 4.6 |

- Latency budget: about 0.6 s is the deliberate VAD pause, about 0.6–0.9 s Whisper, and about 0.4 s LibreTranslate
- An adaptive interim budget cut queueing from 1.4 s to 0 s for Hindi
- RAM: 2.1 GB total. No GPU.
- Realistic microphone test (typing, cough, hum, silence): English 5/5 and Hindi 5/5 captions correct, 0 invented; wrong "I speak" language 0/5 (see Q&A 21)
- The latency rows above were measured before the Silero VAD, Auto-detect and 2-worker changes

*Notes:* Method in one breath: FLEURS test set, 25 sentences per language, jiwer for WER, sacreBLEU for BLEU and chrF, live latency measured by two WebSocket clients. State the small sample size yourself.

### Slide 13. Live demo (script in Part 1b below)
- Two devices, one room, two languages (English to Hindi, then Hindi to English)
- Show: captions, interim text, latency chip, transcript panel, `/api/stats`
- Fallback if P2P video is blocked: captions continue through the server

*Notes:* Keep the demo to 4 minutes. Rehearse on the venue network beforehand.

### Slide 14. Limitations, future work, conclusion
- Limits: two participants; sentence-level captions (not word-by-word simultaneous); accuracy tied to model size; no authentication; in-memory rooms (single replica); CPU contention between rooms
- Future: SFU for multi-party calls, one ASR path per speaker, simultaneous translation, TTS voice-over, diarisation, meeting minutes, TURN bundled in Compose
- **Conclusion:** a fully open-source, self-hostable pipeline gives usable cross-language captions on a CPU server with no paid API, and the latency and accuracy are measured rather than assumed

*Notes:* End by returning to the abstract: prototype, two-person calls, more than two language pairs, benchmarks. Then invite questions.

---

## Part 1b. Live demo script

**Before the session (15 min earlier):** open the `https://` URL on both devices, allow camera/mic, check `/api/health` shows `"translator": true`, and speak one test sentence per language to warm things up. Use headphones on at least one device to avoid echo, and keep the devices in different spots (or mute one speaker) so the mics do not hear each other.

1. **Device A (laptop, projected):** open the site, name "Asha", *I speak* English, *Show captions in* English, room code left blank (= the shared "main" room, nothing to type). Join.
2. **Device B (phone or second laptop):** open the invite link (the copy-invite button), name "Ravi", *I speak* Hindi, *Show captions in* Hindi. Join. Point out "in call - peer-to-peer".
3. **Asha says:** "Hello Ravi, welcome to our project demo. Can you hear me clearly?" Show the grey interim text, then the final Hindi caption on B, with the original underneath.
4. **Ravi replies in Hindi:** "हाँ, मुझे आपकी आवाज़ साफ़ सुनाई दे रही है।" Show the English caption on A.
5. **Change a setting mid-call:** switch Ravi's caption language to English; say another sentence; show it changes (the `update` message, `main.py`).
6. **Show numbers:** the latency chip, one transcript entry's breakdown (pause + queue + ASR + MT), then `/api/stats` in a tab.
7. **Mic feedback:** while Asha speaks, point at the "hearing you..." badge on her own video and the green ring on her mic button, and the "speaking..." tag on her name on Ravi's screen.
8. **Optional:** toggle the mic off mid-sentence to show the `flush` that finishes the sentence (`app.js`).

**Fallback plan:**
- *Video does not connect* (venue Wi-Fi blocks UDP/P2P): the status chip says "media blocked by network (captions still work)". Carry on: captions travel over the server WebSocket, and you can say your lines aloud. Alternatively switch one device to a phone hotspot, or configure TURN beforehand.
- *WebSocket blocked:* the page shows "reconnecting"; switch to a hotspot.
- *Translator still loading:* captions appear untranslated with a lobby warning; wait for `/api/health` to show `translator: true`.
- *Everything fails:* play a pre-recorded screen capture of a successful call.

---

## Part 2. Viva / Q&A prep

**1. Why WebRTC peer-to-peer and not an SFU?**
For two people, a mesh of one link is the simplest correct topology: no media server, lower latency, no server bandwidth for video. The server only relays SDP/ICE (`main.py`). An SFU (mediasoup, LiveKit) pays off at three or more participants, and is listed as future work. The abstract itself scopes the project to two-person calls.

**2. Why send audio separately over a WebSocket instead of using the WebRTC audio on the server?**
In P2P the server never receives the WebRTC media. To get it, the server would have to be a WebRTC endpoint (for example an SFU or a Python WebRTC stack) and decode Opus. The AudioWorklet instead gives clean 16 kHz int16 PCM, which is exactly what Whisper wants, over a plain WebSocket (`app.js`, `pcm-worklet.js`). Cost: about 32 KB/s extra upload per speaker. Benefit: the caption path is independent of the media path, so captions work even if video fails.

**3. How does your VAD work and what is the trade-off?**
It is a streaming neural VAD: Silero, the ONNX model bundled with faster-whisper, run on 32 ms frames (512 samples) with its recurrent state and a 64-sample context carried from frame to frame (`vad.py`). A frame is speech at probability >= 0.5 and non-speech below 0.35 (hysteresis). An utterance opens after 3 speech frames (~100 ms) and closes after `SILENCE_MS` (600 ms) of non-speech, with 300 ms pre-roll and a 10 s maximum. Frames quieter than RMS 0.002 skip the network, and the measured cost is 0.12 ms per frame. We switched from an energy VAD because it counted keyboard typing as speech and merged two sentences into one caption; Silero scores speech at 0.8-0.96 and keyboard, cough and fan hum at 0.21 or less. Trade-off: a shorter silence window lowers caption latency by that amount but splits sentences at mid-sentence pauses, hurting ASR and translation context; a longer one is more accurate but slower. faster-whisper's built-in Silero filter (`asr.py`) still gives a second pass inside each segment.

**4. Is this really "streaming" ASR?**
Not token-level streaming. It is VAD-segmented, utterance-level recognition plus interim captions produced by re-transcribing the growing utterance every ~1.2 s (`main.py`). Final captions arrive after the sentence ends. True simultaneous decoding (SimulStreaming) needs far more compute (RELATED_WORK #8).

**5. Why are interim captions skipped when Whisper is busy?**
There are two ASR workers by default (`ASR_WORKERS=2`, two threads each on 4 vCPU). An interim costs the same compute as a real transcription, so running it while a final is waiting would delay the caption that matters. `maybe_interim` returns early when all workers are busy (`asr.busy >= ASR_WORKERS`, `main.py`), and stale interims are dropped if the final already went out (`main.py`).

**6. Why int8?**
CTranslate2 int8 quantisation roughly halves memory and speeds up CPU inference with little accuracy loss. faster-whisper's published benchmark (small model, 13 min audio, i7-12700K, 8 threads, beam 5) is 1m42s and 1477 MB for int8 against 2m37s and 2257 MB for fp32. That is a published figure, not our measurement; ours are in BENCHMARKS.md. Config: `WHISPER_COMPUTE=int8` (`config.py`).

**7. Why offer a fixed language when Auto-detect exists?**
Auto-detect is the default because a wrong "I speak" setting makes Whisper write nonsense (in our test, English speech with Hindi selected gave "Torrent I and You Sour Sourts"), and that was the cause of the "it shows random sentences" report. It costs a detection pass of about 0.4-0.5 s per sentence on CPU (Whisper pads to 30 s), and short or unclear sentences are easy to misjudge, so detection is sticky: below 0.6 confidence or under 1.5 s of audio the speaker's previous language is kept. A fixed language skips that pass and avoids mis-detection, so it is still available. If a fixed language sounds wrong in the first 2 sentences (another offered language at p >= 0.7), the speaker gets a one-click "switch to Y" banner.

**8. What does the latency consist of?**
`totalMs` = end of speech to caption sent = pause wait (`vadMs`, at least `SILENCE_MS`) + queue (`queueMs`) + ASR (`asrMs`) + MT (`mtMs`) (`main.py`). It excludes up to 100 ms of worklet buffering and network transit, which are not measured server-side. The live benchmark (`bench/latency.py`) measures from the last audio frame sent to the final caption received by a second client, so it includes the silence wait and the network. The pause is a design parameter, not compute.

**9. How did you measure accuracy?**
Offline with `bench/accuracy.py` on FLEURS test sentences (n-way parallel: the same sentence id exists in every language, so it gives both audio and reference translations). ASR: WER via jiwer (plus CER for Hindi) after lowercasing and stripping punctuation. MT: BLEU and chrF via sacreBLEU against the target-language FLEURS text, once from the reference source text (isolates MT) and once from ASR output (the real cascade). Limitation: 25 sentences per language is a small sample, read-speech FLEURS is cleaner than real calls.

**10. Why does Hindi need a bigger model?**
Small Whisper models are weaker on lower-resource languages and Devanagari, with more errors and repetition loops. `WHISPER_MODEL_BY_LANG=hi=small` loads a second model and routes Hindi speakers to it (`asr.py`, `asr.py`), so English stays on fast `base`. Cost: about 1 GB more RAM. The size of the gain is in BENCHMARKS.md.

**11. How do you deal with Whisper hallucinations?**
Several layers: Silero VAD filtering inside faster-whisper (`asr.py`); dropping segments with `no_speech_prob > 0.6` and `avg_logprob < -1.0` (`asr.py`); a regex for known phantom phrases such as "thanks for watching" (`asr.py`); and `collapse_repeats`, which caps runs of repeated 1-3 word units at two (`asr.py`). `condition_on_previous_text=False` also prevents error carry-over between segments.

**12. What about privacy and security?**
No cloud APIs: audio is processed on your own server and is not stored (the code writes no audio to disk; transcripts exist only in the browser unless the user downloads them). Honest caveats: the server does receive everyone's audio; the transcript text is written to the server log at INFO level (`main.py`); default STUN uses Google servers, which see participants' IP addresses; model weights are downloaded from the internet at build or first start. There is **no authentication**: anyone who knows or guesses a room name can join an empty room, and the only guard is the two-person cap (`main.py`). Room names from the UI are random with some entropy, but this is not access control. Rooms live in memory only (`main.py`). HTTPS/WSS is provided by the reverse proxy.

**13. How does it scale?**
It does not scale far, by design. Whisper is CPU-bound; with `ASR_WORKERS=2` all rooms share two decoders, so more concurrent speech than that queues (visible as `queueMs`). Two workers were chosen because 2 threads is nearly as fast as 4 on these models (base English 0.86 s with 4 threads vs 1.07 s with 2; small Hindi 2.45 s vs 2.39 s). Rooms are in process memory, so only one server replica works (`Dockerfile` runs one uvicorn worker). Scaling out would need sticky routing or a shared room store, and ideally a separate ASR service or GPU (`WHISPER_DEVICE=cuda`).

**14. What happens when NAT blocks peer-to-peer?**
STUN handles most home and office NATs. Strict networks (some campus Wi-Fi, mobile carriers) need a TURN relay, configurable with `TURN_URLS/USERNAME/CREDENTIAL` (`config.py`). Without TURN, the connection state becomes `failed`; the UI says media is blocked and the initiator calls `restartIce` (`app.js`). Captions are unaffected because they use the WebSocket. TURN is not bundled in the Compose file.

**15. What are the AGPL implications of LibreTranslate?**
LibreTranslate is AGPL-3.0. We run the unmodified upstream image as its own container and talk to it over HTTP, so it is a separate program and Transmeet's own code (MIT) is not a derivative work. Obligations would arise if we modified LibreTranslate and offered it to users over a network; then we would need to publish those changes. (This is the standard reading, not legal advice.) The Whisper weights are MIT.

**16. Why Silero VAD instead of a simple energy VAD?**
We started with an energy VAD (RMS against an adaptive noise floor) because it is cheap and fully controllable, but real-microphone testing showed it counts keyboard typing as speech and merged two sentences into one caption (Hindi test: 3/5 correct). Silero is already installed with faster-whisper, so it adds no dependency, costs 0.12 ms per 32 ms frame, and separates a voice from typing, coughs and fan hum. It can still be fooled by background speech or music.

**17. How do you keep captions in order and avoid duplicates?**
Each peer has a sequence number per utterance. `final_lock` serialises that speaker's finals (`main.py`); `finalized` marks the highest completed utterance so a late interim never overwrites a final (`main.py`, `main.py`). The client keys captions by `seg` id (`speakerId-n`), so an interim is replaced in place by its final (`app.js`). Empty finals clear a dangling interim.

**18. How does one speaker's caption reach each viewer in a different language?**
`translate_for_room` collects the distinct caption languages in the room, excluding the speaker's own, and translates once per language in parallel (`main.py`). `deliver` then builds a per-peer message with that peer's `tgt` and translated text (`main.py`). Viewers can change their caption language mid-call; the server just reads the updated value.

**19. Why not use a cloud ASR or LLM translator, which would be more accurate?**
The project's goal is a fully open-source, self-hostable, no-per-minute-cost pipeline (abstract). Cloud services would give better quality or lower latency but add cost, data leaving your control and vendor dependence. The architecture is modular, so the ASR or MT stage could be swapped.

**20. What would you do with more time?**
Run the benchmark on more sentences and real call audio; stream-friendly decoding for lower latency; bundle a TURN server; room passcodes and rate limits; an SFU plus per-speaker ASR for group calls; optional TTS voice-over.


**21. How do you know it transcribes what the user actually says and doesn't make things up?**
We tested it with a realistic microphone recording instead of only clean FLEURS clips. `tests/mic_scenario.py` builds 5 known sentences (Piper TTS, English or Hindi) mixed with keyboard typing, a cough, 120 Hz fan hum, long silences and -55 dBFS room tone. `tests/caption_check.py` streams it to the server like a browser and classifies every caption as correct (WER <= 35 %), garbled, or invented (a hallucination when nothing was said). Result: English 5/5 correct and Hindi 5/5 correct with **0 invented** captions, both with a fixed language; with Auto-detect it was also 5/5 for each language, and two people talking at exactly the same time gave 5/5 each. The same test showed the failure we fixed: a wrong "I speak" setting (English speech, Hindi selected) gave 0/5, which is why Auto-detect is the default and a wrong-language hint appears. Honest limits: the test uses synthetic (TTS) speech and 5 sentences per language, and Hindi is less accurate than English because of the model.

---

## Part 3. Glossary

| Term | Meaning in this project |
|---|---|
| **WebRTC** | Browser API for real-time peer-to-peer audio/video; carries the call media |
| **SDP** | Session Description Protocol: the offer/answer text describing codecs and connection details; relayed via `signal` messages |
| **ICE** | Interactive Connectivity Establishment: process of finding a working network path between peers |
| **STUN** | Server that tells a peer its public address; defaults to Google's (`config.py`) |
| **TURN** | Relay server used when direct P2P fails; optional here, costs bandwidth |
| **Signalling** | Exchange of SDP and ICE candidates before a call; done over the app's WebSocket |
| **SFU** | Selective Forwarding Unit: media server for group calls; not used (future work) |
| **AudioWorklet** | Browser API for processing audio on a dedicated thread; used to produce 16 kHz PCM |
| **PCM** | Raw uncompressed audio samples; 16-bit mono at 16 kHz here |
| **VAD** | Voice Activity Detection: decides when speech starts and stops (`vad.py`, Silero) |
| **RMS** | Root-mean-square amplitude of a frame; used only to skip silent frames (below 0.002) before the VAD network runs |
| **Silero VAD** | Small neural voice-activity model (ONNX, bundled with faster-whisper) that scores each 32 ms frame as speech or not; keeps typing, coughs and hum out of the captions |
| **Auto-detect** | The "I speak" option where Whisper `base` detects the spoken language of each sentence (Urdu counted as Hindi, previous language kept if unsure) |
| **Whisper** | OpenAI's multilingual speech-recognition model family (tiny, base, small, ...) |
| **CTranslate2** | Fast C++ inference engine for transformer models; runs Whisper (via faster-whisper) and Argos |
| **int8 quantisation** | Storing weights as 8-bit integers: less memory and faster on CPU with small accuracy loss |
| **RTF** | Real-time factor: compute time divided by audio duration; below 1 means faster than real time (`/api/stats` `asrRealTimeFactor`) |
| **WER / CER** | Word / character error rate of a transcript against a reference; lower is better |
| **BLEU / chrF** | Translation quality scores (n-gram overlap / character n-gram F-score); higher is better; computed with sacreBLEU |
| **FLEURS** | Google's n-way parallel multilingual speech benchmark; same sentence in many languages |
| **LibreTranslate** | Open-source (AGPL-3.0) translation server built on Argos Translate models |
| **Interim / final caption** | Provisional text while speaking vs the committed sentence after a pause |
