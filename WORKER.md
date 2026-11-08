# content-worker

Cloud renderer for the Zafnatech content factory (videos for DiniDine and the other brands).
Source: the Mac project `content-factory` (copied 7 Nov 2026, without secrets, client registry or channel ids).

## State
- Renderer runs in the cloud: a 9 s test video renders in ~17 s (measured), so 30 videos a day is ~30 min of compute a month-end-to-end.
- Needs only Python 3.12, Pillow, numpy, ffmpeg. See `Dockerfile`.

## Brands
`brands/<slug>/` holds brand.json (palette, fonts, voice, `guardrails` from the Brand Book: status, language, honest message, avoid) + mascot + logo.
Built from the 7 Nov 2026 brand book with `python3 tools/import_brandbook.py <folder>`. Palettes of the 9 new brands are PROVISIONAL (from the brief),
voices (ElevenLabs) are not assigned yet, and only DiniDine has an approved look and voice. Mother brand `zafnatech` added (palette from the book: #2458D3 / #159EAA / #102A43; logo = the vector SVG rendered to PNG; the wordmark already carries Space Grotesk, UI text uses Outfit until the font file is added to `fonts/`; no mascot).
Each brand has `banned_phrases` (Brand Book "evitar"): a hit blocks the render (`cf/guardrails.py`).

## Done (8 Nov 2026)
- Step 1: `cf/menu_video.py` (menu from the Agent API -> job; kinds `top3`, `estrella`; prices shown, never spoken) + tests.
- Step 2: `worker.py` (`make`, `run`) -> render -> ElevenLabs voice -> Cloudinary -> panel as "needs review". Skips (never registers) a video with no consent / no voice. Per-run voice cap `WORKER_VOICE_USD_CAP`.
- Env contract is in the `worker.py` docstring. Consent registry and channel list come from `CLIENTS_JSON` / `CHANNELS_JSON` env vars in the cloud.
- KNOWN LIMIT before daily mode: slot state is a file lost between cloud runs. Fix = a platform endpoint that returns the already-scheduled slots + registered job keys (planned with `content_requests`).

- DECISION 8 Nov 2026 (Jonathan): no restaurant permission is asked for menu videos. `WORKER_REQUIRE_CONSENT=1` restores the clients.json gate. Each video still needs his approval in the panel.

## Plan (each step is its own commit; nothing publishes without approval in the panel)
1. Menu -> video template: takes a business menu and builds the job JSON.
2. `worker.py`: picks up video requests, renders, adds the voice (ElevenLabs), uploads to Cloudinary, registers in the panel as "needs review".
3. Daily mode: proposes videos from menus + idea bank; a person approves.
4. Results loop (views per post) to repeat what works.

## Rules
- Never commit `.env`, `clients.json`, `channels.json`, media or card data. Keys live in the host's dashboard.
- The brand kill switch and the approval gate live in the platform (panel "Contenido"); this worker never publishes.
