"""Streaming voice-activity detection.

Audio arrives from the browser as 16 kHz mono PCM in ~100 ms chunks. The
Segmenter splits it into 30 ms frames, compares each frame's energy (RMS)
against an adaptive noise floor and cuts the stream into utterances: an
utterance starts after a few loud frames and ends after SILENCE_MS of quiet.
Each finished utterance is handed to the speech recogniser as one block.
"""
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
FRAME = 480                 # 30 ms at 16 kHz
FRAME_MS = 30
MIN_RMS = 0.008             # absolute floor so digital silence never counts as speech
START_FRAMES = 3            # 90 ms of voice needed to open an utterance


@dataclass
class Utterance:
    audio: np.ndarray       # float32 PCM, 16 kHz
    speech_end: float       # time.monotonic() of the last voiced frame
    cut_at: float           # time.monotonic() when the VAD closed the utterance
    forced: bool            # cut because it hit MAX_SEGMENT_S rather than a pause


class Segmenter:
    def __init__(self, silence_ms: int = 600, max_segment_s: float = 10.0,
                 min_speech_ms: int = 250, preroll_ms: int = 300):
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = int(max_segment_s * 1000 / FRAME_MS)
        self.min_voiced = max(1, min_speech_ms // FRAME_MS)
        self.preroll: deque[np.ndarray] = deque(maxlen=max(1, preroll_ms // FRAME_MS))
        self.noise = 0.002
        self.leftover = np.zeros(0, dtype=np.float32)
        self.frames: list[np.ndarray] = []
        self.in_speech = False
        self.voiced_run = 0
        self.silent_run = 0
        self.voiced_total = 0
        self.last_voiced_at = 0.0
        self.started_at = 0.0

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
        """End the current utterance immediately (e.g. the speaker disconnected)."""
        u = self._finish(forced=False) if self.in_speech else None
        self.in_speech = False
        return [u] if u else []

    def _frame(self, f: np.ndarray) -> Utterance | None:
        rms = float(np.sqrt(np.mean(f * f)))
        voiced = rms > max(MIN_RMS, self.noise * 3.0)
        # Noise floor follows quiet frames quickly and loud frames very slowly,
        # so a constant fan hum is eventually absorbed but speech is not.
        rate = 0.1 if rms < self.noise else 0.001
        self.noise += rate * (rms - self.noise)
        now = time.monotonic()

        if not self.in_speech:
            self.preroll.append(f)
            self.voiced_run = self.voiced_run + 1 if voiced else 0
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
        if voiced:
            self.silent_run = 0
            self.voiced_total += 1
            self.last_voiced_at = now
        else:
            self.silent_run += 1

        if self.silent_run >= self.silence_frames:
            self.in_speech = False
            self.voiced_run = 0
            # keep ~200 ms of trailing silence, drop the rest
            keep = len(self.frames) - self.silent_run + min(self.silent_run, 7)
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
