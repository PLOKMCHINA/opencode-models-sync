#!/usr/bin/env python3
"""opencode provider models auto-refresh.

Reads /root/.config/opencode/opencode.jsonc, and for every custom provider that
uses @ai-sdk/openai-compatible, tries GET {baseURL}/models (falling back to
{v1}/models variants). When the endpoint returns a model list, the provider's
"models" map is rebuilt from the response. Models that were hand-written in the
config but are no longer returned by the gateway are kept unless --prune is
passed, so manual aliases never get lost silently.

Usage:
  python3 opencode-models-sync.py [--prune] [--dry-run] [--config PATH]

Exit code 0 when nothing changed, 1 when changes were written (or would be),
2 on error.
"""

import argparse
import json
import os
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.request

DEFAULT_CONFIG = "/root/.config/opencode/opencode.jsonc"
DEFAULT_BACKUP = "/root/.config/opencode/opencode.jsonc.bak-modelsync"

# Optional per-provider whitelist (prefixes) can be added here to keep only a
# subset of gateway models. Hand-written models are always kept regardless.

# Order of candidate model-list endpoints per provider, normalized on baseURL.
# If baseURL already ends with /v1 (e.g. https://x/v1/), the list endpoint is
# {base}/models. Otherwise try both {base}/models and {base}/v1/models.
def candidates(base_url):
    base = base_url.rstrip("/")
    out = []
    if base.endswith("/v1"):
        out.append(base + "/models")
    else:
        out.append(base + "/models")
        out.append(base + "/v1/models")
    return out


def strip_jsonc(raw):
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    return raw


def fetch_models(base_url, api_key, timeout=10):
    ctx = ssl.create_default_context()
    last_err = None
    for url in candidates(base_url):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + api_key})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = json.loads(r.read().decode())
                mids = [m.get("id") for m in data.get("data", []) if m.get("id")]
                if mids:
                    return url, mids
                return url, []
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {url}"
            if e.code == 200:  # unreachable, but keep symmetrical
                break
        except Exception as e:
            last_err = f"{type(e).__name__} {url}"
    raise RuntimeError(last_err or "no endpoint reachable")


def rebuild_models(existing, discovered, whitelist=None, prune=False):
    """Build the merged model map.

    - discovered: ids returned by the gateway list endpoint.
    - Hand-written entries whose id is NOT in the gateway list are KEPT by
      default (so manual aliases never get lost silently) and dropped only when
      prune=True.
    - whitelist: optional list of prefixes; gateway ids not matching any prefix
      and not already hand-written are skipped.
    """
    discovered_set = set(discovered)
    models = {}
    for mid in discovered_set:
        if whitelist is not None:
            if isinstance(whitelist, tuple):
                keep = mid in whitelist
            else:
                keep = any(mid.startswith(p) for p in whitelist)
            if not keep and mid not in existing:
                continue
        prior = existing.get(mid, {})
        entry = {"name": mid}
        for k, v in prior.items():
            if k != "name":
                entry[k] = v
        models[mid] = entry
    if not prune:
        for mid, prior in existing.items():
            if mid not in models:
                models[mid] = dict(prior)
    return models


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--backup", default=DEFAULT_BACKUP)
    ap.add_argument("--prune", action="store_true",
                    help="drop hand-written models not returned by the gateway")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg_path = args.config
    if not os.path.exists(cfg_path):
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 2

    raw = open(cfg_path, encoding="utf-8").read()
    try:
        data = json.loads(strip_jsonc(raw))
    except Exception as e:
        print(f"failed to parse config: {e}", file=sys.stderr)
        return 2

    providers = data.get("provider", {})
    changed = False
    for pid, pconf in providers.items():
        if not isinstance(pconf, dict):
            continue
        if pconf.get("npm") != "@ai-sdk/openai-compatible":
            continue
        options = pconf.get("options", {})
        base_url = options.get("baseURL")
        api_key = options.get("apiKey")
        if not base_url or not api_key:
            print(f"[{pid}] skip: no baseURL/apiKey")
            continue
        existing = pconf.get("models", {}) or {}
        try:
            src_url, discovered = fetch_models(base_url, api_key)
        except Exception as e:
            print(f"[{pid}] FAILED: {e} (keeping current models)")
            continue

        whitelist = None
        new_models = rebuild_models(existing, discovered, whitelist=whitelist, prune=args.prune)

        old_count = len(existing)
        new_count = len(new_models)
        if new_count == 0:
            print(f"[{pid}] endpoint returned no models ({src_url}), keeping current")
            continue
        if set(new_models.keys()) == set(existing.keys()):
            print(f"[{pid}] unchanged ({new_count} models)")
            continue

        pconf["models"] = new_models
        changed = True
        added = sorted(set(new_models) - set(existing))
        removed = sorted(set(existing) - set(new_models))
        print(f"[{pid}] {old_count} -> {new_count} models ({src_url})")
        if added:
            print(f"    added: {added[:10]}{' ...' if len(added) > 10 else ''}")
        if removed:
            print(f"    removed: {removed[:10]}{' ...' if len(removed) > 10 else ''}")

    if not changed:
        print("no changes")
        return 0

    if args.dry_run:
        print("dry-run: would write changes")
        return 1

    shutil.copy2(cfg_path, args.backup)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"backup written to {args.backup}")
    print(f"config updated: {cfg_path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
