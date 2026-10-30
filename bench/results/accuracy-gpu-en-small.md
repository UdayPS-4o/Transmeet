# Accuracy: Whisper `base`

Settings: {'device': 'cuda', 'mt': 'libretranslate', 'mt_model': 'JustFrederik/nllb-200-distilled-600M-ct2-int8', 'compute': 'int8_float16', 'beam': 1, 'cpus': 12, 'by_lang': {'en': 'small'}, 'normalize': True, 'gain_db': 0.0, 'threads': 12, 'lt_url': 'http://127.0.0.1:9'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| en | 40 | 5.4 | - | 0.32 | 9.3 | 0.035 |
