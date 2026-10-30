# Accuracy: Whisper `base`

Settings: {'device': 'cuda', 'mt': 'libretranslate', 'mt_model': 'JustFrederik/nllb-200-distilled-600M-ct2-int8', 'compute': 'int8_float16', 'beam': 1, 'cpus': 12, 'by_lang': {'hi': 'collabora/faster-whisper-large-v2-hindi'}, 'normalize': True, 'gain_db': 0.0, 'threads': 12, 'lt_url': 'http://127.0.0.1:9'}

## ASR (WER on normalised text)

| lang | n | WER % | CER % | mean ASR s | mean audio s | RTF |
|---|---|---|---|---|---|---|
| hi | 40 | 15.9 | 8.1 | 11.70 | 11.5 | 1.015 |
