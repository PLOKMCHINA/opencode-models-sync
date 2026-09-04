# opencode-models-sync

Syncs model lists into your `opencode.json`/`.jsonc` for providers using `@ai-sdk/openai-compatible`.

It walks each such provider, probes `GET {baseURL}/models` (falling back to `{baseURL}/v1/models`, so it skips the `/v1/v1/models` trap), and rebuilds the provider's `models` map from the response. Hand-written models are kept unless you pass `--prune`. Gateways that return 401/403/404 are skipped and left untouched.

## Usage

```
python3 opencode-models-sync.py --dry-run   # preview changes
python3 opencode-models-sync.py             # write changes (backs up first)
```

Flags: `--prune` (drop hand-written models no longer returned), `--config PATH`, `--backup PATH`.

Exit codes: `0` = no change, `1` = changes written (or would be, with `--dry-run`), `2` = error.

Stdlib only; works with either `.json` or `.jsonc`.
