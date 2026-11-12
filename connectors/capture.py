"""Automatic "screen recording" of a PUBLIC web page (a restaurant's storefront/menu, the TV player render page...).

No human recording: Chromium without a window opens the URL at phone size, scrolls it smoothly frame by frame and encodes
a clean 1080x1920 MP4 (deterministic: every frame is a screenshot, so no dropped frames).

  python3 connectors/capture.py <url> clients/<slug>/menu.mp4 [--seconds 8] [--wait 2.5]

Public pages only: it never logs in and never types anything. Using a restaurant's page in a PUBLISHED video still needs
video_consent=true in clients.json (factory.py enforces it for assets under clients/).
Needs: pip install playwright && playwright install chromium ; ffmpeg.
"""
import os
import sys
import shutil
import tempfile
import argparse
import subprocess

FPS = 30


def ease(x):
    return x * x * (3 - 2 * x)


SCROLLER_JS = '''() => {
  let best = document.scrollingElement || document.documentElement, bestMax = best.scrollHeight - window.innerHeight;
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (!/(auto|scroll)/.test(cs.overflowY)) continue;
    const m = el.scrollHeight - el.clientHeight;
    if (m > bestMax + 50 && el.clientHeight > window.innerHeight * 0.5) { best = el; bestMax = m; }
  }
  window.__cfTotal = () => Math.max(0, bestMax);
  window.__cfScroll = (y) => best.scrollTo(0, y);
}'''


def capture(url, out_mp4, seconds=8.0, size=(1080, 1920), scale=2, wait=2.5, hold=1.0):
    from playwright.sync_api import sync_playwright
    vw, vh = size[0] // scale, size[1] // scale
    tmp = tempfile.mkdtemp(prefix='cf-cap-')
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={'width': vw, 'height': vh}, device_scale_factor=scale, is_mobile=True, has_touch=True, locale='es-US',
                          user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')
            pg.goto(url, wait_until='networkidle', timeout=60000)
            pg.wait_for_timeout(int(wait * 1000))
            # Some menus scroll inside a container, not the window: find the tallest scrollable thing and drive that.
            pg.evaluate(SCROLLER_JS)
            total = pg.evaluate('window.__cfTotal()')
            n = int(seconds * FPS)
            nh = int(hold * FPS)  # still frames at the start and end
            for i in range(n):
                u = 0.0 if i < nh else 1.0 if i >= n - nh else ease((i - nh) / max(1, n - 2 * nh - 1))
                pg.evaluate(f'window.__cfScroll({total * u})')
                pg.wait_for_timeout(30)
                pg.screenshot(path=os.path.join(tmp, f'{i:05d}.jpg'), type='jpeg', quality=92)
            br.close()
        os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
        subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(tmp, '%05d.jpg'),
                               '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out_mp4 + '.tmp.mp4'])
        os.replace(out_mp4 + '.tmp.mp4', out_mp4)
        return out_mp4, total
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('out')
    ap.add_argument('--seconds', type=float, default=8)
    ap.add_argument('--wait', type=float, default=2.5)
    a = ap.parse_args()
    f, total = capture(a.url, a.out, a.seconds, wait=a.wait)
    print(f'OK {f} (página de {total}px de scroll)')
