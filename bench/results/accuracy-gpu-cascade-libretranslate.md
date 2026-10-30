# Accuracy: Whisper `large-v3-turbo`

Settings: {'device': 'cuda', 'mt': 'libretranslate', 'mt_model': 'JustFrederik/nllb-200-distilled-600M-ct2-int8', 'compute': 'int8_float16', 'beam': 1, 'cpus': 12, 'by_lang': {'hi': 'songzewu/vasista22-whisper-hindi-small-ct2'}, 'normalize': True, 'gain_db': 0.0, 'threads': 12, 'lt_url': 'http://localhost:5000'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 40 | 2.8 | - | 0.62 | 9.3 | 0.067 |
| hi | 40 | 16.1 | 7.3 | 1.02 | 11.5 | 0.088 |
| es | 40 | 1.6 | - | 2.04 | 11.7 | 0.175 |

## Machine translation (LibreTranslate)

| pair | n | BLEU ref | chrF ref | BLEU cascade | chrF cascade | MT ms (ref) | MT ms (cascade) | failed |
|---|---|---|---|---|---|---|---|---|
| en-hi | 40 | 25.8 | 51.1 | 25.2 | 50.3 | 907 | 875 | 0 |
| hi-en | 40 | 27.1 | 53.2 | 20.0 | 49.6 | 825 | 812 | 0 |
| en-es | 40 | 24.0 | 55.4 | 24.2 | 54.8 | 812 | 805 | 0 |
| es-en | 40 | 30.8 | 61.7 | 29.0 | 60.7 | 886 | 846 | 0 |
| hi-es | 40 | 11.0 | 41.4 | 9.0 | 40.6 | 1549 | 1573 | 0 |
| es-hi | 40 | 12.9 | 41.1 | 12.2 | 40.5 | 1647 | 1670 | 0 |

ref = translating the FLEURS source text; cascade = translating the ASR output.
