# Offline license snapshot sources

These files are evidence snapshots, not legal advice. Each URL is pinned to the
revision used by this package where the upstream service supports immutable
revisions.

| Local file | Covered asset | Official source and fixed revision |
|---|---|---|
| `QWEN-RESEARCH-LICENSE.txt` | Qwen2.5-3B-Instruct and the Q4_K_M GGUF conversion | GGUF files: `Qwen/Qwen2.5-3B-Instruct-GGUF@cc1e68eea5f05f88f41a6de1fc73110178f23715` (the commit contains GGUF files only). License text: `Qwen/Qwen2.5-3B-Instruct@aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE`, https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE |
| `LFM-OPEN-LICENSE-1.0.txt` | LFM2.5-1.2B-Instruct Q4_K_M GGUF | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF@012803cf70d6cdcf698f0c65fa8f9b7175128770/LICENSE`, https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/blob/012803cf70d6cdcf698f0c65fa8f9b7175128770/LICENSE |
| `LLAMA-CPP-MIT.txt` | llama.cpp Windows CPU runtime b10375 | tag `b10375`, commit `ba360efe1f574ebae727aad64112d18ecedca85a`, https://github.com/ggml-org/llama.cpp/blob/b10375/LICENSE |
| `FASTER-WHISPER-MIT.txt` | Faster-Whisper Python software 1.2.1 | tag `v1.2.1`, commit `65882eee9f5cdbeeb2d877f1131d48cf241b327d`, https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/LICENSE |
| `OPENAI-WHISPER-MIT.txt` | OpenAI Whisper source software referenced by the converted model | tag `v20240930`, commit `25639fc17ddc013d56c594bfbf7644f2185fad84`, https://github.com/openai/whisper/blob/v20240930/LICENSE |

The packaged CTranslate2 model is
`Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`.
That fixed model repository has no standalone `LICENSE` file; its fixed
`README.md` declares `license: mit` and states that the model is a conversion
of `openai/whisper-small`:
https://huggingface.co/Systran/faster-whisper-small/blob/536b0662742c02347bc0e980a01041f333bce120/README.md

The three MIT files above are software license notices. They do not silently
resolve the separate provenance or redistribution gaps listed in
`BLOCKED-NOTICE.md`.
