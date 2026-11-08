"""Voice per scene.

Order of preference for each scene clip voz/<job>/<scene>.mp3:
  1. already processed clip exists            -> use it
  2. raw clip voz/<job>/<scene>.raw.mp3 exists -> trim silence + speed up -> use it
     (this is how clips made in the ElevenLabs web UI are dropped in)
  3. ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID set -> call the API server-side, then as (2)
  4. otherwise the scene is "pending": the render uses an estimated duration (no voice) and
     voz/<job>/PENDIENTE.md lists the exact text to generate.

Secrets only come from environment variables. Never write them in jobs, code or chat.
"""
import os
import json
import subprocess
import urllib.request
import urllib.error

from .brand import ROOT


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def process_clip(raw, out, atempo=1.15):
    """Trim leading/trailing silence, then speed up (atempo) without changing pitch."""
    af = ('silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,'
          'silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse')
    if abs(atempo - 1) > 1e-3:
        af += f',atempo={atempo}'
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', raw, '-af', af, '-b:a', '128k', out + '.tmp.mp3'])
    os.replace(out + '.tmp.mp3', out)


def say_text(scene, brand):
    """Text for the TTS engine: `say` if given, else `speak` with the brand's pronunciation map."""
    t = scene.say or scene.speak
    if not scene.say:
        for k, v in brand.voice_cfg.get('pronounce', {}).items():
            t = t.replace(k, v)
    return t


def tts_api(text, out_raw, brand):
    key, voice = os.environ.get('ELEVENLABS_API_KEY'), os.environ.get('ELEVENLABS_VOICE_ID')
    model = os.environ.get('ELEVENLABS_MODEL_ID') or 'eleven_v4_turbo'   # decisión: Turbo (mitad de precio que v4, misma calidad dentro del margen de error). Ids: eleven_v4, eleven_v4_turbo
    if not (key and voice):
        return False
    body = {'text': text, 'voice_settings': {'stability': brand.voice_cfg.get('stability', 0.5),
                                              'similarity_boost': brand.voice_cfg.get('similarity', 0.75)}}
    if model:
        body['model_id'] = model
    req = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128',
        data=json.dumps(body).encode(), method='POST',
        headers={'xi-api-key': key, 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(out_raw, 'wb') as f:
            f.write(r.read())
        return True
    except urllib.error.HTTPError as e:
        print(f'  ElevenLabs API error {e.code} on {os.path.basename(out_raw)}')
    except Exception as e:  # network blocked, etc.
        print(f'  ElevenLabs API unreachable: {type(e).__name__}')
    return False


def ensure_voice(job_id, scenes, brand, atempo=None):
    """Fill scene.voice_path / scene.voice_dur where possible. Returns list of pending scenes."""
    d = os.path.join(ROOT, 'voz', job_id)
    os.makedirs(d, exist_ok=True)
    atempo = atempo or brand.voice_cfg.get('atempo', 1.15)
    tag = brand.voice_cfg.get('tag', '')
    pending = []
    for sc in scenes:
        out, raw = os.path.join(d, f'{sc.id}.mp3'), os.path.join(d, f'{sc.id}.raw.mp3')
        if not os.path.exists(out):
            if not os.path.exists(raw):
                tts_api(f'{tag} {say_text(sc, brand)}'.strip(), raw, brand)
            if os.path.exists(raw):
                process_clip(raw, out, atempo)
        if os.path.exists(out):
            sc.voice_path, sc.voice_dur = out, probe(out)
        else:
            pending.append(sc)
    note = os.path.join(d, 'PENDIENTE.md')
    if pending:
        with open(note, 'w', encoding='utf-8') as f:
            f.write(f'# Voz pendiente: {job_id}\n\nVoz: {brand.voice_cfg.get("voice_name", "")}. '
                    f'Genera cada texto (con la etiqueta) y guarda el MP3 como `voz/{job_id}/<escena>.raw.mp3`.\n\n')
            for sc in pending:
                f.write(f'## {sc.id}\n\n```\n{tag} {say_text(sc, brand)}\n```\n\n')
    elif os.path.exists(note):
        os.remove(note)
    return pending


def envelope(path, sr=16000, hop=0.02):
    """Loudness per `hop` seconds (0..1) to animate the mascot's mouth/body."""
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', str(sr), '-'],
                         capture_output=True).stdout
    a = np.frombuffer(raw, dtype='<i2').astype('float32') / 32768.0
    n = int(sr * hop)
    if len(a) < n:
        return np.zeros(1, dtype='float32'), hop
    a = a[:len(a) // n * n].reshape(-1, n)
    rms = np.sqrt((a ** 2).mean(axis=1))
    rms = rms / (np.percentile(rms, 95) + 1e-6)
    return np.clip(rms, 0, 1).astype('float32'), hop
