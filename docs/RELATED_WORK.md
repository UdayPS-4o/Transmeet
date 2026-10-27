# Related work and reference figures

Research notes for the project report. These sources were checked on 2026-10-27. "Unknown" means no reliable published figure was found. Transmeet's own measured numbers are in [BENCHMARKS.md](BENCHMARKS.md).

## Similar systems

| # | System | License | What it does | Difference from Transmeet |
|---|---|---|---|---|
| 1 | [voice-bridge](https://github.com/ankitpokhrel08/voice-bridge) | MIT | WebRTC call (Socket.io). Mic PCM is sent over WebSocket to FastAPI, which runs VAD, faster-whisper and Argos Translate or Google Translate. | Closest prior art. It is a small hobby project. Transmeet is an independent implementation with per-viewer caption language, interim captions, latency instrumentation, a benchmark suite and one-domain Docker deployment. |
| 2 | [meet-translate](https://github.com/mujeebmasi/meet-translate) | none stated | WebRTC call with captions and translated voice. | Uses paid cloud APIs only (OpenAI Realtime, Gemini Live), billed per minute. |
| 3 | [Jitsi Meet + Jigasi](https://github.com/jitsi/jigasi) | Apache-2.0 | Transcriber bot that joins the room. STT is Google, Vosk or Whisper. Translation is LibreTranslate or Microsoft. | Needs the full Jitsi stack (XMPP/Prosody, Maven build). Heavy for a small self-hosted setup. |
| 4 | [Jitsi Skynet](https://github.com/jitsi/skynet) | Apache-2.0 | AI services for Jitsi, including faster-whisper live transcription over WebSocket. | Transcription only. No translation. |
| 5 | [LiveKit Agents](https://github.com/livekit/agents) | Apache-2.0 | Framework for server-side agents in rooms. Includes a transcriber example. | Documented STT paths are cloud services (Deepgram, LiveKit Inference). Needs a LiveKit SFU. |
| 6 | [WhisperLive](https://github.com/collabora/WhisperLive) | MIT | Near-live Whisper server (faster-whisper/TensorRT/OpenVINO) with browser extensions. | ASR component only. Not a calling app. |
| 7 | [whisper_streaming](https://github.com/ufal/whisper_streaming) | MIT | Streaming Whisper with a local-agreement policy. About 3.3 s latency. | Translates into English only. Being replaced by SimulStreaming. |
| 8 | [SimulStreaming](https://github.com/ufal/SimulStreaming) | MIT | Simultaneous Whisper plus an LLM (EuroLLM) for translation. | Recommends a GPU with at least 10 GB VRAM. README says CPU is too slow for real time. |
| 9 | [Vexa](https://github.com/Vexa-ai/vexa) | Apache-2.0 | Bots that transcribe Meet/Teams/Zoom calls. | Transcription only. Self-hosting is aimed at a GPU box. |
| 10 | [Zoom translated captions](https://www.zoom.com/en/blog/translated-captions) | Proprietary | 35 languages, chosen per participant. | Paid add-on (about $5/user/month). Cloud only. |
| 11 | [Google Meet translated captions](https://support.google.com/meet/a/answer/10964115) | Proprietary | 69 languages (June 2024). | Paid Workspace editions only. Since Jan 2025 tied to Gemini for Workspace. |
| 12 | [Microsoft Teams live translated captions](https://support.microsoft.com/topic/4be2d304-f675-4b57-8347-cbd000a21260) | Proprietary | Live translated meeting captions. | Needs Teams Premium or Microsoft 365 Copilot. |

## Published CPU figures

**faster-whisper README CPU benchmark** ([source](https://github.com/SYSTRAN/faster-whisper)). Test setup: `small` model, 13 min of audio, Intel i7-12700K, 8 threads, beam size 5.

| Implementation | Precision | Time | Peak RAM |
|---|---|---|---|
| openai/whisper | fp32 | 6m58s | 2335 MB |
| whisper.cpp | fp32 | 2m05s | 1049 MB |
| faster-whisper | fp32 | 2m37s | 2257 MB |
| faster-whisper | **int8** | **1m42s** | **1477 MB** |

With int8, `small` runs about 7.6× faster than real time on a desktop 8-thread CPU. That is why Transmeet uses CTranslate2 int8 by default.

**LibreTranslate / Argos Translate** ([source](https://github.com/LibreTranslate/LibreTranslate)) is AGPL-3.0. It runs as a separate unmodified container, so Transmeet's own code does not inherit the AGPL.
- `LT_LOAD_ONLY` limits which language models are loaded. This reduces RAM use and start-up time.
- No official RAM figures were found. Third-party templates estimate about 200 MB per loaded language and a 2–4 GB minimum.
- The underlying CTranslate2 engine is quoted at 696 tokens/s for an int8 OPUS-MT model on 4 threads ([source](https://github.com/OpenNMT/CTranslate2)).
