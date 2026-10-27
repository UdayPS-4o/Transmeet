# Live latency: Whisper `base`

Server: {'model': 'base', 'silenceMs': 600, 'beam': 1, 'translator_online': True}

| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | queue ms | asr ms | mt ms | server total ms | interims/utt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en-hi | 9/10 | 1 | 0 | 1423 | 1432 | 2446 | 623 | 283 | 786 | 309 | 1999 | 4.2 |
| hi-en | 10/10 | 0 | 0 | 6946 | 6040 | 13837 | 390 | 1442 | 7019 | 684 | 9535 | 2.6 |
| en-es | 10/10 | 0 | 0 | 1118 | 1331 | 1978 | 620 | 211 | 743 | 242 | 1816 | 4.5 |
| es-en | 10/10 | 0 | 0 | 2098 | 2045 | 2961 | 692 | 178 | 930 | 407 | 2207 | 4.4 |

e2e = final caption arrival at the listener - end of speech (clips are silence-trimmed; includes the SILENCE_MS pause the VAD needs to decide the sentence ended).
mt ms can be ~0: the last interim caption usually already translated the same text, so the final hits the translation cache.
