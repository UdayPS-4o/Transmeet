# Accuracy: Whisper `small`

Settings: {'compute': 'int8', 'beam': 1, 'cpus': 4, 'threads': 0, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 25 | 4.7 | - | 1.67 | 9.3 | 0.180 |
| hi | 25 | 53.9 | 26.5 | 4.51 | 11.0 | 0.410 |
| es | 25 | 5.1 | - | 1.88 | 11.1 | 0.169 |
| fr | 25 | 15.6 | - | 1.90 | 9.2 | 0.208 |
| de | 25 | 8.0 | - | 1.84 | 11.7 | 0.157 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 25 | 22.6 | 46.7 | 22.5 | 46.6 | 491 | 494 | 0 |
| hi-en | 25 | 25.3 | 54.8 | 4.7 | 24.3 | 500 | 865 | 0 |
| en-es | 25 | 24.6 | 55.5 | 25.7 | 55.1 | 493 | 510 | 0 |
| es-en | 25 | 33.2 | 63.0 | 30.3 | 60.6 | 672 | 654 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
