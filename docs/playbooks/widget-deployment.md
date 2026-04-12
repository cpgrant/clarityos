# Widget Deployment Playbook

## Use When

- the embed widget loads on the wrong host
- the widget is unexpectedly unavailable
- operators need to verify branding, allowed origins, or allowed agents for a deployed widget

## Pre-Checks

1. Inspect `GET /widget/config`.
2. Verify:
   - `enabled`
   - `allowed_origins`
   - `allowed_agents`
   - `launcher`
   - `branding`
3. If the widget is embedded, confirm the browser host appears in `requested_origin_allowed`.

## Procedure

1. If the widget should be disabled, set:
   - `CLARITYCLAW_WIDGET_ENABLED=0`
2. If the widget should be limited to specific hosts, set:
   - `CLARITYCLAW_WIDGET_ALLOWED_ORIGINS`
3. If only specific agents should be exposed through the widget, set:
   - `CLARITYCLAW_WIDGET_ALLOWED_AGENTS`
4. Adjust branding and launcher posture only through env config:
   - brand name
   - tagline
   - accent
   - label
   - launcher position
   - launcher default open

## Guardrails

- do not rely on widget query params alone for deployment posture
- prefer same-origin embedding unless there is a clear cross-origin need
- do not expose agents through the widget that should remain operator-only
