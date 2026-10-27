# Live latency: Whisper `base` (4 vCPU)

Server: {'model': 'base', 'silenceMs': 600, 'beam': 1, 'translator_online': True}

| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | queue ms | asr ms | mt ms | server total ms | interims/utt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en-hi | 9/10 | 1 | 0 | 1124 | 1396 | 1725 | 623 | 38 | 655 | 386 | 1701 | 2.4 |
| hi-en | 10/10 | 0 | 0 | 5862 | 4384 | 15663 | 390 | 1 | 7290 | 769 | 8450 | 0.5 |
| en-es | 9/10 | 1 | 0 | 1101 | 1335 | 1725 | 622 | 36 | 638 | 382 | 1678 | 2.8 |
| es-en | 10/10 | 0 | 0 | 1843 | 1796 | 2273 | 691 | 1 | 731 | 530 | 1952 | 2.3 |

e2e = final caption arrival at the listener - end of speech (clips are silence-trimmed; includes the SILENCE_MS pause the VAD needs to decide the sentence ended).
mt ms can be ~0: the last interim caption usually already translated the same text, so the final hits the translation cache.
