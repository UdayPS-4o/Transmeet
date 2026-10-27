# Live latency: Whisper `base` (2 vCPU: server + LibreTranslate pinned to 2 cores)

Server: {'model': 'base', 'silenceMs': 600, 'beam': 1, 'translator_online': True}

| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | queue ms | asr ms | mt ms | server total ms | interims/utt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en-hi | 9/10 | 1 | 0 | 1370 | 1366 | 2168 | 623 | 72 | 912 | 340 | 1946 | 1.4 |
| hi-en | 9/10 | 0 | 1 | 6924 | 5640 | 15306 | 434 | 3 | 8581 | 650 | 9667 | 0.1 |
| en-es | 10/10 | 0 | 0 | 1266 | 1501 | 1945 | 620 | 1 | 989 | 355 | 1965 | 1.2 |
| es-en | 10/10 | 0 | 0 | 2346 | 2234 | 2903 | 691 | 1 | 1020 | 742 | 2455 | 1.0 |

e2e = final caption arrival at the listener - end of speech (clips are silence-trimmed; includes the SILENCE_MS pause the VAD needs to decide the sentence ended).
mt ms can be ~0: the last interim caption usually already translated the same text, so the final hits the translation cache.
