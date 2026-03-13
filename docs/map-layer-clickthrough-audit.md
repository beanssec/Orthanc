# Map Layer Click-Through Audit (Static)

| Layer key | Fetch endpoint | Click layer | Link target(s) | Result |
|---|---|---|---|---|
| flights | `'/layers/flights'` | `FLIGHTS_LAYER` | — | popup-only/no-link |
| ships | `'/layers/ships'` | `SHIPS_LAYER` | — | popup-only/no-link |
| firms | `'/layers/firms'` | `FIRMS_LAYER` | — | popup-only/no-link |
| frontlines | ``/layers/frontlines?source=${frontlineSource}`` | `FRONTLINES_LAYER_EVENTS` | — | popup-only/no-link |
| satellites | `'/layers/satellites'` | `SATELLITES_LAYER` | — | popup-only/no-link |
| sentiment | ``/layers/sentiment?hours=${sentimentHours}`` | `SENTIMENT_LAYER_CIRCLES` | /feed?location=${encodeURIComponent(p.place_name || '')}&has_geo=true | feed-link |
| gdelt | ``/gdelt/geo?q=${encodeURIComponent(q)}`` | `GDELT_GEO_CIRCLE_LAYER` | — | popup-only/no-link |
| acled | `'/layers/acled?hours=168'` | `ACLED_LAYER` | /feed?post=${encodeURIComponent(String(p.id))} | feed-link |
| fusion | `'/layers/fusion?hours=48'` | `FUSION_LAYER` | ${feedPath}, ${feedPath} | feed-link |
| notams | `'/layers/notams?active_only=true'` | `NOTAMS_LAYER` | /feed?post=${encodeURIComponent(String(p.id))} | feed-link |
| maritime | `'/layers/maritime-events?hours=72'` | `MARITIME_LAYER` | — | popup-only/no-link |
| watchpoints | `'/layers/watchpoints'` | `WATCHPOINTS_LAYER` | — | popup-only/no-link |
| narratives | `'/layers/narratives'` | `NARRATIVES_LAYER` | /narratives | internal-link |

Notes:
- Fusion layer now parses `entity_names`, `source_types`, and `component_post_ids` as either arrays or JSON strings before resolving `/feed?post=...`.
- This fixes the unresolved "View related events" behavior when map feature properties are delivered as arrays instead of serialized JSON.
- Runtime UI verification still requires authenticated session in the browser.
