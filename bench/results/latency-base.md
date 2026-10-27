# Live latency: Whisper `base`

Server: {'model': 'base', 'silenceMs': 600, 'beam': 1, 'translator_online': True}

| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | queue ms | asr ms | mt ms | server total ms | interims/utt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| en-hi | 4/10 | 0 | 6 | 1481 | 1470 | 1607 | 651 | 173 | 617 | 88 | 1529 | 3.5 |
| hi-en | 8/10 | 0 | 2 | 7142 | 6537 | 13394 | 425 | 2248 | 5486 | 631 | 8790 | 2.8 |
| en-es | 4/10 | 0 | 6 | 1624 | 1554 | 2013 | 656 | 186 | 682 | 149 | 1672 | 3.5 |
| es-en | 10/10 | 0 | 0 | 2081 | 1951 | 2872 | 690 | 114 | 1034 | 351 | 2189 | 4.3 |

e2e = final caption arrival at the listener - end of speech (clips are silence-trimmed; includes the SILENCE_MS pause the VAD needs to decide the sentence ended).
mt ms can be ~0: the last interim caption usually already translated the same text, so the final hits the translation cache.
