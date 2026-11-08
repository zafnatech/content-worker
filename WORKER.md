# content-worker

Cloud renderer for the Zafnatech content factory (videos for DiniDine and the other brands).
Source: the Mac project `content-factory` (copied 7 Nov 2026, without secrets, client registry or channel ids).

## State
- Renderer runs in the cloud: a 9 s test video renders in ~17 s (measured), so 30 videos a day is ~30 min of compute a month-end-to-end.
- Needs only Python 3.12, Pillow, numpy, ffmpeg. See `Dockerfile`.

## Plan (each step is its own commit; nothing publishes without approval in the panel)
1. Menu -> video template: takes a business menu and builds the job JSON.
2. `worker.py`: picks up video requests, renders, adds the voice (ElevenLabs), uploads to Cloudinary, registers in the panel as "needs review".
3. Daily mode: proposes videos from menus + idea bank; a person approves.
4. Results loop (views per post) to repeat what works.

## Rules
- Never commit `.env`, `clients.json`, `channels.json`, media or card data. Keys live in the host's dashboard.
- The brand kill switch and the approval gate live in the platform (panel "Contenido"); this worker never publishes.
