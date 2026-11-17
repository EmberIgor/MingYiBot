# Pinned scoring asset provenance

`zhuiguang_scoring.js` is copied verbatim from the authorized read-only reference `/Users/weiyige/.hermes/scripts/sky_reference/zhuiguang_scoring.js`, originally obtained from:

https://yb.zhuiguang.ren/assets/scoring.js

SHA-256: `c5fc3c407a473e2e30ac7bd53fd403be152786a0be3f6a5245c8f4d72539434a`.

The original Chinese header and all algorithm code are unchanged. No upstream license declaration was present in the supplied asset; this note records origin, not an assertion of a particular license. Do not update silently: verify upstream permission, behavior, hash, and regression evidence when changing the asset.

The wrapper uses Node's `vm` with a fixed evaluation clock and `TZ=Asia/Shanghai`, a one-second VM execution limit, a three-second Node subprocess limit, and the outer source process group's 18-second limit. City coordinates are resolved for the requested city, never hardcoded to Beijing. Inputs/outputs are JSON, not interpolated JavaScript.

The upstream fallback uses defaults for missing cloud/weather values and JavaScript coercion for null observations. The Python adapter independently rejects incomplete hourly/rain/PM2.5 event windows and drops incomplete/stale current observations before using the result. It labels indices as heuristic, does not reuse the engine's uncalibrated spectacular-event prose, and applies separate conservative notification guards. Its static path obstruction remains unknown.

Glow parser provenance: adapted and generalized from the authorized read-only `glow_sunset_reference.py` reference; JSON API discovery and original reference verification are documented in the user's `sunsetbot-weather/references/alternative-sources.md`. Runtime collection is self-contained in this repository; it imports nothing from the Hermes installation.

`tests/fixtures/sky/glow_beijing.json` and `glow_summary.json` are reduced real responses fetched on 2026-11-17 in Asia/Shanghai, retaining original values and the parser-relevant fields. Omitted explanatory timelines/geometry are not test inputs. Synthetic weather used by unit tests is explicitly test data; it is never recorded as live network output.
