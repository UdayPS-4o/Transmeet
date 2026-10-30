# Accuracy: Whisper `large-v3-turbo`

Settings: {'device': 'cuda', 'mt': 'nllb', 'mt_model': 'JustFrederik/nllb-200-distilled-600M-ct2-int8', 'compute': 'int8_float16', 'beam': 1, 'cpus': 12, 'by_lang': {'hi': 'songzewu/vasista22-whisper-hindi-small-ct2'}, 'normalize': True, 'gain_db': 0.0, 'threads': 12, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 40 | 2.8 | - | 0.66 | 9.3 | 0.071 |
| hi | 40 | 16.1 | 7.3 | 1.00 | 11.5 | 0.087 |
| es | 40 | 1.6 | - | 2.21 | 11.7 | 0.189 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 40 | 25.8 | 52.6 | 26.3 | 53.0 | 483 | 885 | 0 |
| hi-en | 40 | 40.0 | 66.3 | 34.2 | 61.1 | 1009 | 1040 | 0 |
| en-es | 40 | 29.9 | 59.4 | 26.2 | 57.6 | 1184 | 1167 | 0 |
| es-en | 40 | 37.1 | 65.7 | 35.8 | 64.1 | 1052 | 1045 | 0 |
| hi-es | 40 | 16.4 | 48.2 | 12.6 | 44.2 | 1150 | 1173 | 0 |
| es-hi | 40 | 17.0 | 43.6 | 16.8 | 43.0 | 1248 | 1224 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
