# Live latency: Whisper `base`

Server: {'model': 'base', 'silenceMs': 600, 'beam': 1, 'translator_online': True}

| pair | ok | empty | timeout | e2e mean ms | p50 | p95 | vad ms | asr ms | mt ms | server total ms | interims/utt |
|---|---|---|---|---|---|---|---|---|---|---|---|
| en-hi | 4/10 | 0 | 6 | 899 | 1048 | 1324 | 602 | 716 | 0 | 1548 | 3.8 |
| hi-en | 8/10 | 0 | 2 | 6102 | 4938 | 13689 | 375 | 6366 | 1349 | 9895 | 2.1 |
| en-es | 4/10 | 0 | 6 | 906 | 893 | 1354 | 601 | 676 | 94 | 1554 | 3.8 |
| es-en | 7/10 | 0 | 3 | 1022 | 1166 | 1851 | 600 | 973 | 510 | 2263 | 4.1 |

e2e = final caption arrival at the listener - last audio frame sent (includes SILENCE_MS and any trailing silence in the wav).
