"""Build a realistic 'someone talking into a laptop mic' recording with known text.

The FLEURS benchmark uses clean studio-like clips. A real call also has room
tone, keyboard typing, coughs, fan hum and long silences, and these are what
make Whisper invent "random sentences". This script synthesises known
sentences with Piper TTS and mixes them with those noises. tests/e2e.cjs can
then feed the result to Chrome as the microphone and check that every
caption matches something that was really said and that noise produces none.

    pip install piper-tts
    python tests/mic_scenario.py --voice voices/en_US-lessac-medium.onnx --lang en --out mic_en.wav

Writes mic_en.wav (16 kHz mono PCM16) and mic_en.json (the sentences and
where the noise events are).
"""
import argparse
import json
import wave

import numpy as np
from piper import PiperVoice

SR = 16000
SENTENCES = {
    "en": [
        "Hello, can you hear me clearly?",
        "My name is Priya and I am a computer science student.",
        "Today I will show you our project called Transmeet.",
        "It translates what I say into your language in real time.",
        "Can we meet tomorrow at five o'clock in the library?",
    ],
    "hi": [
        "नमस्ते, क्या आप मुझे सुन सकते हैं?",
        "मेरा नाम राहुल है और मैं इंजीनियरिंग का छात्र हूँ।",
        "आज हम अपने प्रोजेक्ट के बारे में बात करेंगे।",
        "क्या आप कल शाम को लाइब्रेरी में मिल सकते हैं?",
        "यह ऐप मेरी बात को आपकी भाषा में अनुवाद करता है।",
    ],
    "es": [
        "Hola, ¿me escuchas bien?",
        "Me llamo Lucía y estudio ingeniería en Madrid.",
        "Hoy vamos a hablar de nuestro proyecto.",
        "¿Podemos vernos mañana a las cinco en la biblioteca?",
        "Esta aplicación traduce lo que digo a tu idioma.",
    ],
}

rng = np.random.default_rng(7)


def db(x: float) -> float:
    return 10 ** (x / 20)


def tts(voice: PiperVoice, text: str) -> np.ndarray:
    pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(text))
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    src = voice.config.sample_rate                       # 22050 -> 16000
    t = np.arange(0, len(audio) / src, 1 / SR)
    audio = np.interp(t, np.arange(len(audio)) / src, audio).astype(np.float32)
    return audio / (np.sqrt(np.mean(audio ** 2)) + 1e-9) * db(-22)   # speech at about -22 dBFS RMS


def pink(n: int) -> np.ndarray:
    """Pink-ish noise (1/f), close to real room tone."""
    spec = np.fft.rfft(rng.standard_normal(n))
    spec /= np.sqrt(np.arange(1, len(spec) + 1))
    x = np.fft.irfft(spec, n)
    return (x / np.std(x)).astype(np.float32)


def keyboard(seconds: float) -> np.ndarray:
    out = np.zeros(int(seconds * SR), np.float32)
    for t in rng.uniform(0, seconds - 0.05, int(seconds * 7)):            # ~7 keys per second
        i = int(t * SR)
        click = rng.standard_normal(int(0.012 * SR)) * np.exp(-np.linspace(0, 8, int(0.012 * SR)))
        out[i:i + len(click)] += click.astype(np.float32) * db(-24)
    return out


def cough() -> np.ndarray:
    n = int(0.35 * SR)
    env = np.concatenate([np.linspace(0, 1, n // 10), np.exp(-np.linspace(0, 5, n - n // 10))])
    burst = np.convolve(rng.standard_normal(n), np.ones(6) / 6, "same") * env   # muffled noise burst
    return (burst / np.max(np.abs(burst)) * db(-12)).astype(np.float32)


def hum(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (np.sin(2 * np.pi * 120 * t) * 0.6 + np.sin(2 * np.pi * 240 * t) * 0.3).astype(np.float32) * db(-34)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", required=True)
    ap.add_argument("--lang", choices=SENTENCES, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    voice = PiperVoice.load(args.voice)

    parts, events = [], []
    def add(kind: str, audio: np.ndarray, text: str | None = None):
        start = sum(len(p) for p in parts) / SR
        parts.append(audio)
        events.append({"kind": kind, "start": round(start, 2), "end": round(start + len(audio) / SR, 2),
                       **({"text": text} if text else {})})

    s = SENTENCES[args.lang]
    add("silence", silence(3.0))
    add("speech", tts(voice, s[0]), s[0])
    add("keyboard", keyboard(2.5))
    add("speech", tts(voice, s[1]), s[1])
    add("silence", silence(3.0))
    add("cough", cough())
    add("silence", silence(2.0))
    add("speech", tts(voice, s[2]), s[2])
    add("hum", hum(3.0))
    add("speech", tts(voice, s[3]), s[3])
    add("silence", silence(2.5))
    add("speech", tts(voice, s[4]), s[4])
    add("silence", silence(4.0))

    audio = np.concatenate(parts)
    audio += pink(len(audio)) * db(-55)                   # quiet room tone under everything
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    meta = {"lang": args.lang, "duration": round(len(audio) / SR, 2), "events": events}
    with open(args.out.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"wrote {args.out} ({meta['duration']} s, {len(s)} sentences)")


if __name__ == "__main__":
    main()
