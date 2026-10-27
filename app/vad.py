"""Streaming voice-activity detection.

Audio arrives from the browser as 16 kHz mono PCM in ~100 ms chunks. The
Segmenter splits it into 32 ms frames and asks Silero VAD, a small neural
network shipped with faster-whisper, how likely each frame is to be speech.
That is what separates a voice from keyboard clicks, a cough or a fan; a plain
loudness threshold cannot. An utterance starts after ~100 ms of speech and ends
after SILENCE_MS without it. Each finished utterance goes to Whisper as one block.
"""
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from faster_whisper.vad import get_vad_model

SAMPLE_RATE = 16000
FRAME = 512                 # 32 ms: the frame size Silero VAD expects at 16 kHz
FRAME_MS = 32
CONTEXT = 64                # Silero looks at the last 64 samples of the previous frame
START_PROB = 0.5            # frame counts as speech above this...
END_PROB = 0.35             # ...and as non-speech below this (hysteresis in between)
START_FRAMES = 3            # ~100 ms of speech opens an utterance
MIN_RMS = 0.002             # quieter than -54 dBFS is silence; skip the network

_model = None


def _silero():
    global _model
    if _model is None:
        _model = get_vad_model()
    return _model


@dataclass
class Utterance:
    audio: np.ndarray       # float32 PCM, 16 kHz
    speech_end: float       # time.monotonic() of the last speech frame
    cut_at: float           # time.monotonic() when the VAD closed the utterance
    forced: bool            # cut because it hit MAX_SEGMENT_S rather than a pause


class Segmenter:
    def __init__(self, silence_ms: int = 600, max_segment_s: float = 10.0,
                 min_speech_ms: int = 250, preroll_ms: int = 300):
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = int(max_segment_s * 1000 / FRAME_MS)
        self.min_voiced = max(1, min_speech_ms // FRAME_MS)
        self.preroll: deque[np.ndarray] = deque(maxlen=max(1, preroll_ms // FRAME_MS))
        self.leftover = np.zeros(0, dtype=np.float32)
        # Silero's recurrent state, carried from frame to frame
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(CONTEXT, dtype=np.float32)
        self.frames: list[np.ndarray] = []
        self.in_speech = False
        self.voiced_run = 0
        self.silent_run = 0
        self.voiced_total = 0
        self.last_voiced_at = 0.0
        self.started_at = 0.0
        self.prob = 0.0             # latest speech probability (exposed for the UI)

    def current_audio(self) -> np.ndarray | None:
        """Audio of the utterance still in progress (used for interim captions)."""
        if not self.in_speech or not self.frames:
            return None
        return np.concatenate(self.frames)

    def push(self, pcm: np.ndarray) -> list[Utterance]:
        data = np.concatenate([self.leftover, pcm]) if self.leftover.size else pcm
        n = len(data) // FRAME
        self.leftover = data[n * FRAME:].copy()
        done: list[Utterance] = []
        for i in range(n):
            u = self._frame(data[i * FRAME:(i + 1) * FRAME])
            if u is not None:
                done.append(u)
        return done

    def flush(self) -> list[Utterance]:
        """End the current utterance immediately (e.g. the speaker muted)."""
        u = self._finish(forced=False) if self.in_speech else None
        self.in_speech = False
        return [u] if u else []

    def _speech_prob(self, f: np.ndarray) -> float:
        if float(np.sqrt(np.mean(f * f))) < MIN_RMS:
            p = 0.0
        else:
            x = np.concatenate([self.context, f])[None, :]
            out, self.h, self.c = _silero().session.run(None, {"input": x, "h": self.h, "c": self.c})
            p = float(out.reshape(-1)[0])
        self.context = f[-CONTEXT:]
        return p

    def _frame(self, f: np.ndarray) -> Utterance | None:
        p = self.prob = self._speech_prob(f)
        now = time.monotonic()

        if not self.in_speech:
            self.preroll.append(f)
            self.voiced_run = self.voiced_run + 1 if p >= START_PROB else 0
            if self.voiced_run >= START_FRAMES:
                self.in_speech = True
                self.frames = list(self.preroll)
                self.preroll.clear()
                self.voiced_total = self.voiced_run
                self.silent_run = 0
                self.last_voiced_at = now
                self.started_at = now
            return None

        self.frames.append(f)
        if p >= START_PROB:
            self.silent_run = 0
            self.voiced_total += 1
            self.last_voiced_at = now
        elif p < END_PROB:
            self.silent_run += 1

        if self.silent_run >= self.silence_frames:
            self.in_speech = False
            self.voiced_run = 0
            # keep ~200 ms of trailing silence, drop the rest
            keep = len(self.frames) - self.silent_run + min(self.silent_run, 6)
            self.frames = self.frames[:keep]
            return self._finish(forced=False)
        if len(self.frames) >= self.max_frames:
            u = self._finish(forced=True)       # stay in speech, start a fresh block
            self.started_at = now
            return u
        return None

    def _finish(self, forced: bool) -> Utterance | None:
        frames, voiced = self.frames, self.voiced_total
        self.frames, self.voiced_total = [], 0
        if voiced < self.min_voiced or not frames:
            return None
        return Utterance(np.concatenate(frames), self.last_voiced_at, time.monotonic(), forced)
