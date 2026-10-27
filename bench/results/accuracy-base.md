# Accuracy: Whisper `base`

Settings: {'compute': 'int8', 'beam': 1, 'cpus': 4, 'threads': 0, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 25 | 7.3 | - | 0.79 | 9.3 | 0.085 |
| hi | 25 | 118.3 | 96.5 | 1.88 | 11.0 | 0.170 |
| es | 25 | 10.9 | - | 0.80 | 11.1 | 0.072 |
| fr | 25 | 31.7 | - | 0.92 | 9.2 | 0.100 |
| de | 25 | 15.3 | - | 0.81 | 11.7 | 0.069 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 25 | 22.6 | 46.7 | 23.0 | 45.9 | 516 | 505 | 0 |
| hi-en | 25 | 25.3 | 54.8 | 0.6 | 13.6 | 518 | 1230 | 0 |
| en-es | 25 | 24.6 | 55.5 | 24.4 | 54.0 | 512 | 517 | 0 |
| es-en | 25 | 33.2 | 63.0 | 24.3 | 56.3 | 643 | 643 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
