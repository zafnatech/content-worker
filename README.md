# content-factory

Fábrica de videos verticales (9:16) para las marcas de Zafnatech. Un archivo JSON describe el video; la fábrica pone la voz, el avatar, los subtítulos, la música y entrega el MP4 con su caption y su permiso verificado.

Proyecto propio, separado del repo `zafnatech-platform` (no toca su arquitectura). Solo LEE del panel, con una llave de solo lectura.

## Uso

```bash
python3 panel.py     # panel web local: http://127.0.0.1:8787 (lista, editar guion, cuadros, generar, descargar, permisos)
```

O por línea de comandos:

```bash
python3 factory.py jobs/whatsapp-business-tutorial.json            # un video -> out/<fecha>/<id>.mp4 + .srt + .json
python3 factory.py jobs/<job>.json --preview 3,12,25               # fotogramas en build/ para revisar el diseño
python3 batch.py "jobs/*.json" --workers 2                         # muchos videos + out/<fecha>/manifest.csv
```

Requisitos: Python 3, Pillow, numpy, ffmpeg. Render medido: ~58 s por video de 42 s en 1 núcleo (30 videos/día ≈ 30 min).

## Piezas

| Pieza | Dónde | Estado |
|---|---|---|
| Job JSON (marca, escenas, caption) | `jobs/` | listo |
| Marcas (paleta, logo, mascota, voz) | `brands/<marca>/brand.json` | solo DiniDine; copia la carpeta para Tarsiz, Ferritico... |
| Plantillas: `hook`, `step`/`tip`, `outro` (+ visuales: lista, teléfono-perfil, teléfono-chat, imagen) | `cf/templates.py` | listas |
| Voz ElevenLabs (modelo por defecto: `eleven_v4_turbo`) | `cf/voice.py` | por API si hay `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`; si no, clips `.raw.mp3` pegados a mano. El manifiesto de cada video guarda `voice_chars` y `voice_cost_usd_est` |
| Abeja que "habla" | `cf/avatar.py` | se mueve con el volumen de la voz (sin boca). Reemplazable por un avatar animado real |
| Permiso por restaurante | `clients.json` | todo en `false`; sin permiso la fábrica BLOQUEA (o `--draft` marca "BORRADOR") |
| Conector al panel (solo lectura) | `connectors/platform.py` | escrito, SIN probar (la nube no alcanza el panel); correr en tu Mac/servidor |
| Captura automática de la página pública del restaurante (sin grabar nada a mano) | `connectors/capture.py` + visual `phone/clip` | probada con una página local de prueba; contra el menú real hay que correrla en tu Mac/servidor |
| Pantallas de TV | `scripts/tv-export.mjs` de la plataforma (ya existe) | por integrar |
| Publicación automática (IG, FB, TikTok, YouTube) | `publish.py` + `publisher/` + pestaña Publicación del panel | cola propia (topes diarios, horarios, aprobación, sin borradores ni videos sin voz) sobre Postiz (motor de las redes). Probada con un Postiz simulado; falta probar contra un Postiz real y las aprobaciones de las redes |

## Publicación

```bash
cp channels.example.json channels.json      # pon los integration_id (python3 publish.py integrations) y enabled:true
python3 publish.py enqueue-new               # videos nuevos de out/ -> cola
python3 publish.py run --dry                 # ver qué se enviaría, sin enviar
python3 publish.py daemon                    # automático: cada 10 min mete y entrega
python3 -m unittest tests.test_publisher -v  # pruebas (Postiz simulado)
```
Por defecto TikTok y YouTube salen PRIVADOS hasta que esas redes aprueben la app (ver `channels.example.json`).

## Instalación (una vez)

```bash
./setup.sh && cp .env.example .env   # y llena .env en tu computadora
```

## Secretos

Solo en variables de entorno del servidor o de tu Mac. Nunca en jobs, código, repo o chat.

## Regla de oro

Ningún dato, cifra o testimonio inventado. Cada job lista en `verify` lo que hay que confirmar antes de publicar. Videos con fotos, logo o pantallas de un cliente: solo con `video_consent: true`.

## Registro en la plataforma (`sync`)
Sube cada video terminado al banco de Cloudinary (cuenta ZAFNATECH) y lo registra en el módulo "Contenido" de la plataforma, donde queda **pendiente de aprobación**. No publica nada por sí solo.

```
python3 publish.py sync --dry     # muestra qué subiría, sin tocar nada
python3 publish.py sync           # sube y registra los videos nuevos (idempotente)
python3 publish.py platform-channels-sql   # SQL para dar de alta los canales en la plataforma (revisar antes de correr)
```
- Variables en `.env`: ver `.env.example` (`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_UPLOAD_PRESET`, `CONTENT_INGEST_URL`, `CONTENT_INGEST_TOKEN`).
- Salta borradores, videos con escenas sin voz y archivos faltantes. Un rechazo del servidor no marca el video como sincronizado ni consume horarios.
- Estado local: `out/.platform-sync.json`. Pruebas: `python3 -m unittest discover -s tests`.
- Un job puede traer `captions`/`titles` por red y `lineage` (`parent_job`, `change_kind`, `substantive_change`) para reciclar un tema con una pieza nueva.
