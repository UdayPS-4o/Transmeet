# Accuracy: Whisper `base`

Settings: {'device': 'cuda', 'mt': 'libretranslate', 'mt_model': 'JustFrederik/nllb-200-distilled-600M-ct2-int8', 'compute': 'int8_float16', 'beam': 1, 'cpus': 12, 'by_lang': {'hi': 'digikar/vasista22-whisper-hindi-large-v2-ct2-int8'}, 'normalize': True, 'gain_db': 0.0, 'threads': 12, 'lt_url': 'http://127.0.0.1:9'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| hi | 40 | 13.5 | 5.8 | 6.99 | 11.5 | 0.607 |
