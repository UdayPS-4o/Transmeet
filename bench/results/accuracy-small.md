# Accuracy: Whisper `small`

Settings: {'compute': 'int8', 'beam': 1, 'cpus': 4, 'threads': 0, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 25 | 4.7 | - | 1.85 | 9.3 | 0.200 |
| hi | 25 | 53.9 | 25.0 | 4.94 | 11.0 | 0.449 |
| es | 25 | 5.1 | - | 2.08 | 11.1 | 0.187 |
| fr | 25 | 15.6 | - | 2.02 | 9.2 | 0.220 |
| de | 25 | 8.0 | - | 2.00 | 11.7 | 0.171 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 25 | 22.6 | 46.7 | 22.5 | 46.6 | 553 | 551 | 0 |
| hi-en | 25 | 25.3 | 54.8 | 4.6 | 25.2 | 557 | 737 | 0 |
| en-es | 25 | 24.6 | 55.5 | 25.7 | 55.1 | 562 | 551 | 0 |
| es-en | 25 | 33.2 | 63.0 | 30.3 | 60.6 | 730 | 752 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
