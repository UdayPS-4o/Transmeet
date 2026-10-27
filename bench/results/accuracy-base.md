# Accuracy: Whisper `base`

Settings: {'compute': 'int8', 'beam': 1, 'cpus': 4, 'threads': 0, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 25 | 7.3 | - | 0.77 | 9.3 | 0.083 |
| hi | 25 | 103.3 | 94.0 | 1.75 | 11.0 | 0.159 |
| es | 25 | 10.9 | - | 0.86 | 11.1 | 0.077 |
| fr | 25 | 43.1 | - | 0.96 | 9.2 | 0.105 |
| de | 25 | 15.3 | - | 0.82 | 11.7 | 0.070 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 25 | 22.6 | 46.7 | 23.0 | 45.9 | 528 | 510 | 0 |
| hi-en | 25 | 25.3 | 54.8 | 0.9 | 13.7 | 549 | 1114 | 0 |
| en-es | 25 | 24.6 | 55.5 | 24.4 | 54.0 | 548 | 545 | 0 |
| es-en | 25 | 33.2 | 63.0 | 24.3 | 56.3 | 715 | 771 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
