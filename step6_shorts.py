"""
STEP 6 — Shorts Generator (Nocturne Noise)
==========================================
Cron separado: roda ~6h depois do vídeo longo.

Fluxo:
  1. YouTube API → pega último vídeo publicado (título, ID, categoria)
  2. yt-dlp      → baixa áudio do vídeo longo
  3. pydub       → corta melhor trecho de 55s + fade seamless
  4. Groq        → gera título evocativo (máx 7 palavras)
  5. AI cascade  → gera thumbnail 9:16 (IA ou Pexels)
  6. PIL         → escreve título na thumbnail com fade
  7. ffmpeg      → monta vídeo 1080x1920 com Ken Burns + fade de entrada/saída
  8. YouTube API → sobe como Short com link pro vídeo original
"""
import os, json, subprocess, random, re, base64, requests, shutil, textwrap
from pathlib import Path
from datetime import datetime
from pydub import AudioSegment
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO

load_dotenv()

# ─── Config ───────────────────────────────────────────────
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
TOGETHER_KEY = os.environ.get("TOGETHER_API_KEY", "")
FAL_KEY      = os.environ.get("FAL_API_KEY", "")
PEXELS_KEY   = os.environ.get("PEXELS_API_KEY", "")

SHORT_DURATION_S = 55
FADE_MS          = 1500
SHORT_FPS        = 30
SHORT_OUTPUT     = Path("short_final.mp4")
SHORT_AUDIO      = Path("short_audio.mp3")
SHORT_THUMB      = Path("short_thumb.jpg")    # thumbnail pura (sem texto)
SHORT_FRAME      = Path("short_frame.jpg")    # thumbnail com título sobreposto

STYLE_BASE = (
    "nocturne lofi illustration, portrait 9:16, intimate night scene, "
    "warm amber lamp glow, crescent moon and city skyline through large window, "
    "cozy interior, houseplants, vinyl record, deep indigo night sky, "
    "warm golden light contrasting dark blue exterior, "
    "cinematic digital art, no text, no watermark, no people, "
    "high detail, painterly, dreamlike atmosphere"
)

CATEGORY_PROMPTS = {
    "rain":        f"rain drops on window glass at night, steaming coffee mug, warm desk lamp, city lights blurred through rain, {STYLE_BASE}",
    "nature":      f"misty forest at dawn, wooden desk near large window, fern plants, soft morning fog, {STYLE_BASE}",
    "cozy":        f"crackling fireplace close-up, armchair with wool blanket, open book, cup of tea, {STYLE_BASE}",
    "jazz":        f"vinyl record spinning on turntable, warm amber light, jazz album covers on shelf, headphones, {STYLE_BASE}",
    "focus_noise": f"minimalist home office at night, single desk lamp, open notebook, clean aesthetic, city through window, {STYLE_BASE}",
    "study":       f"late night study desk, open books, coffee, warm lamp, rain visible outside window, {STYLE_BASE}",
    "urban":       f"city rain at night, neon reflections on wet pavement, cozy window view from above, {STYLE_BASE}",
}


# ─── 1. Pega último vídeo publicado ───────────────────────
def get_latest_video():
    """Retorna (video_id, title, category) do último vídeo longo do canal."""
    import google.oauth2.credentials as goc
    from googleapiclient.discovery import build

    token_b64 = os.environ.get("YT_TOKEN_B64")
    if not token_b64:
        raise RuntimeError("YT_TOKEN_B64 não definido")

    token_data = json.loads(base64.b64decode(token_b64).decode())
    creds = goc.Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=["https://www.googleapis.com/auth/youtube"],
    )

    yt = build("youtube", "v3", credentials=creds)

    # channels.list = 1 unidade de quota (search.list = 100)
    me         = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = me["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # playlistItems.list = 1 unidade de quota
    pl = yt.playlistItems().list(
        part="snippet",
        playlistId=uploads_id,
        maxResults=10,
    ).execute()

    for item in pl.get("items", []):
        vid_id = item["snippet"]["resourceId"]["videoId"]
        title  = item["snippet"]["title"]
        desc   = item["snippet"].get("description", "")

        # Pula Shorts (são curtos e têm #shorts)
        if "#shorts" in title.lower() or "#shorts" in desc.lower():
            continue

        category = detect_category(title + " " + desc)
        print(f"   Último vídeo: [{vid_id}] {title} → {category}")
        return vid_id, title, category

    raise RuntimeError("Nenhum vídeo longo encontrado no canal")


def detect_category(text):
    text = text.lower()
    if any(w in text for w in ["rain", "raining", "drizzle", "storm", "thunder"]):
        return "rain"
    if any(w in text for w in ["jazz", "piano", "bossa", "saxophone"]):
        return "jazz"
    if any(w in text for w in ["fire", "fireplace", "cozy", "café", "cafe", "library", "cabin"]):
        return "cozy"
    if any(w in text for w in ["forest", "ocean", "river", "waterfall", "bird", "nature"]):
        return "nature"
    if any(w in text for w in ["tokyo", "paris", "london", "new york", "city", "urban", "neon"]):
        return "urban"
    if any(w in text for w in ["brown noise", "white noise", "pink noise"]):
        return "focus_noise"
    if any(w in text for w in ["study", "focus", "concentration"]):
        return "study"
    return "cozy"


# ─── 2. Baixa áudio via yt-dlp ────────────────────────────
def download_audio(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"   Baixando áudio: {url}")
    result = subprocess.run([
        "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
        # Use common clients to bypass bot detection (fallback layer)
        "--extractor-args", "youtube:player_client=android,web",
        "-o", "yt_audio_raw.%(ext)s", "--no-playlist", url,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp falhou:\n{result.stderr[-800:]}")
    files = list(Path(".").glob("yt_audio_raw.*"))
    if not files:
        raise FileNotFoundError("yt-dlp não gerou arquivo")
    return str(files[0])


# ─── 3. Corta melhor trecho de 55s ────────────────────────
def cut_best_segment(audio_path):
    print(f"   Cortando {SHORT_DURATION_S}s do áudio...")
    audio      = AudioSegment.from_file(audio_path)
    total_ms   = len(audio)
    start_ms   = 60_000          # pula 1 minuto de intro
    chunk_ms   = SHORT_DURATION_S * 1000
    best_start = start_ms
    best_rms   = 0

    for t in range(start_ms, min(total_ms - chunk_ms, 600_000), 120_000):
        rms = audio[t : t + chunk_ms].rms
        if rms > best_rms:
            best_rms, best_start = rms, t

    segment = audio[best_start : best_start + chunk_ms]
    segment = segment.fade_in(FADE_MS).fade_out(FADE_MS)

    from pydub.effects import normalize
    segment = normalize(segment)

    segment.export(str(SHORT_AUDIO), format="mp3", bitrate="192k")
    print(f"   Corte: {SHORT_DURATION_S}s @ {best_start//1000}s do original")
    return str(SHORT_AUDIO)


# ─── 4. Gera título evocativo via Groq ────────────────────
EVOCATIVE_FALLBACKS = {
    "rain":        ["Still raining.", "You left the window open.", "It won't stop tonight.",
                    "The rain found you again.", "Let it rain a little longer."],
    "cozy":        ["The fire is still going.", "Stay a little longer.", "No one needs you right now.",
                    "Just this corner of the world.", "Nothing to do but be here."],
    "nature":      ["Nobody knows where you are.", "The forest doesn't need anything from you.",
                    "You found the quiet place.", "Still here. Still breathing."],
    "jazz":        ["One more song.", "The piano player stayed late.", "The bar is almost empty.",
                    "Nobody's leaving yet.", "Just the music now."],
    "focus_noise": ["Disappear into the work.", "Everything else fades.",
                    "The world can wait.", "Block it all out."],
    "study":       ["One more hour.", "The lamp is still on.", "Late night. Just you.",
                    "You still have time.", "The desk is yours tonight."],
    "urban":       ["The city is still awake.", "The lights never really go out.",
                    "Somewhere out there, the night goes on."],
}

def generate_short_title(video_title, category):
    if not GROQ_KEY:
        return random.choice(EVOCATIVE_FALLBACKS.get(category, ["The night is yours."]))
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model":    "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content":
                    f'Video: "{video_title}" | Category: {category}\n'
                    f"Write 1 punchy, evocative Short title (max 5 words). Lowercase. "
                    f"Use a second person 'hook' or atmospheric mystery. "
                    f"Example: 'the rain found you again.' or 'stay a little longer.' "
                    f"Output ONLY the title string."}],
                "temperature": 0.9, "max_tokens": 25,
            },
            timeout=20,
        )
        r.raise_for_status()
        title = r.json()["choices"][0]["message"]["content"].strip().strip('"')
        if 3 <= len(title) <= 60:
            print(f"   Título: {title}")
            return title
    except Exception as e:
        print(f"   Groq falhou: {e}")
    return random.choice(EVOCATIVE_FALLBACKS.get(category, ["The night is yours."]))


# ─── 5. Gera thumbnail 9:16 ───────────────────────────────
def generate_thumbnail(video_title, category):
    prompt = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["cozy"])
    kw     = " ".join(w for w in video_title.lower().split() if len(w) > 3)[:60]
    prompt = f"{kw}, {prompt}"
    img    = None

    # Together AI
    if TOGETHER_KEY:
        try:
            r = requests.post(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
                json={"model": "black-forest-labs/FLUX.1-schnell-Free",
                      "prompt": prompt[:900], "width": 1080, "height": 1920, "n": 1},
                timeout=90,
            )
            r.raise_for_status()
            url = r.json()["data"][0]["url"]
            img = Image.open(BytesIO(requests.get(url, timeout=60).content)).convert("RGB")
            print("   Thumbnail: Together AI OK")
        except Exception as e:
            print(f"   Together falhou: {e}")

    # fal.ai
    if FAL_KEY and img is None:
        try:
            r = requests.post(
                "https://fal.run/fal-ai/flux/schnell",
                headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
                json={"prompt": prompt[:900], "image_size": "portrait_4_3",
                      "num_images": 1, "enable_safety_checker": False},
                timeout=90,
            )
            r.raise_for_status()
            url = r.json()["images"][0]["url"]
            img = Image.open(BytesIO(requests.get(url, timeout=60).content)).convert("RGB")
            img = img.resize((1080, 1920), Image.LANCZOS)
            print("   Thumbnail: fal.ai OK")
        except Exception as e:
            print(f"   fal.ai falhou: {e}")

    # Pollinations (sem key)
    if img is None:
        try:
            encoded = requests.utils.quote(prompt[:350])
            url = (f"https://image.pollinations.ai/prompt/{encoded}"
                   f"?width=1080&height=1920&nologo=true&seed={random.randint(1,9999)}&model=flux")
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            if "image" in r.headers.get("content-type", ""):
                img = Image.open(BytesIO(r.content)).convert("RGB")
                print("   Thumbnail: Pollinations OK")
        except Exception as e:
            print(f"   Pollinations falhou: {e}")

    # Pexels fallback
    if PEXELS_KEY and img is None:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": category.replace("_", " "), "per_page": 5, "orientation": "portrait"},
                timeout=20,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                url = random.choice(photos)["src"]["large2x"]
                img = Image.open(BytesIO(requests.get(url, timeout=30).content)).convert("RGB")
                img = img.resize((1080, 1920), Image.LANCZOS)
                print("   Thumbnail: Pexels OK")
        except Exception as e:
            print(f"   Pexels falhou: {e}")

    # Gradiente programático (último recurso)
    if img is None:
        print("   Thumbnail: gradiente fallback")
        img = _gradient_thumb()

    img.save(str(SHORT_THUMB), "JPEG", quality=95)
    return str(SHORT_THUMB)


def _gradient_thumb():
    img  = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(img)
    for y in range(1920):
        t = y / 1920
        draw.line([(0, y), (1080, y)], fill=(int(10+t*5), int(8+t*3), int(20+t*15)))
    for i in range(200):
        a = 1 - i / 200
        draw.ellipse([(100-i*2, 1400-i*2), (600+i*2, 1900+i*2)],
                     fill=(int(180*a), int(100*a), int(20*a)))
    return img.filter(ImageFilter.GaussianBlur(80))


# ─── 6. Escreve título na imagem com PIL ──────────────────
def add_title_to_frame(thumb_path, title):
    """
    Adiciona o título art-direcionado ao topo da thumbnail.
    Retorna o path da imagem com texto.
    """
    img  = Image.open(thumb_path).convert("RGB")
    W, H = img.size  # 1080 x 1920

    # Gradiente escuro no topo (área do título)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)
    for y in range(int(H * 0.42)):
        alpha = int((1 - y / (H * 0.42)) * 160)
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Fonte — tenta DejaVu (disponível no Ubuntu CI)
    def get_font(size):
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold.ttf",
        ]:
            if os.path.exists(p):
                try:
                    from PIL import ImageFont
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        from PIL import ImageFont
        return ImageFont.load_default()

    # Linha decorativa âmbar
    line_y = int(H * 0.085)
    draw.line([(W // 2 - 55, line_y), (W // 2 + 55, line_y)],
              fill=(200, 160, 80), width=2)

    # Título — quebra em linhas se necessário
    font_size = 96  # Increased from 88 for better 'hook' visibility
    font      = get_font(font_size)
    max_w     = int(W * 0.88) # Slightly wider

    # Reduz fonte se o texto for muito largo
    while font_size > 32:
        wrapped = textwrap.fill(title, width=18)
        lines   = wrapped.split("\n")
        max_line_w = max(
            (draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0])
            for line in lines
        )
        if max_line_w <= max_w:
            break
        font_size -= 6
        font = get_font(font_size)

    wrapped   = textwrap.fill(title, width=18)
    lines     = wrapped.split("\n")
    line_h    = font_size + 12
    text_h    = len(lines) * line_h
    text_y    = line_y + 20

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw   = bbox[2] - bbox[0]
        x    = (W - lw) // 2
        y    = text_y + i * line_h
        # Sombra profunda para destacar o título
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 220))
        # Texto principal — creme quente com leve brilho
        draw.text((x, y), line, font=font, fill=(255, 245, 220))

    # "Nocturne Noise" abaixo do título
    small_font = get_font(28)
    brand      = "NOCTURNE NOISE"
    bbox       = draw.textbbox((0, 0), brand, font=small_font)
    bw         = bbox[2] - bbox[0]
    draw.text(
        ((W - bw) // 2, text_y + text_h + 18),
        brand, font=small_font, fill=(200, 170, 100, 140)
    )

    img.save(str(SHORT_FRAME), "JPEG", quality=95)
    print(f"   Frame com título: {SHORT_FRAME}")
    return str(SHORT_FRAME)


# ─── 7. Renderiza com ffmpeg ──────────────────────────────
def render_with_ffmpeg(frame_path, audio_path, duration_s=59):
    """
    Monta o Short com ffmpeg:
      - Imagem 9:16 com título já sobreposto
      - Ken Burns: zoom suave de 1.0→1.05 ao longo do vídeo
      - Fade in 1.2s / Fade out 1.5s
      - Áudio normalizado
    Sem Node.js, sem React, sem dependências externas.
    """
    fps          = SHORT_FPS
    total_frames = duration_s * fps
    zoom_speed   = 0.05 / total_frames   # chega a 1.05 no último frame

    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"zoompan="
        f"z='min(zoom+{zoom_speed:.10f},1.05)':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s=1080x1920:fps={fps},"
        f"fade=t=in:st=0:d=1.2,"
        f"fade=t=out:st={duration_s-1.5}:d=1.5"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", frame_path,
        "-i",    audio_path,
        "-vf",   vf,
        "-c:v",  "libx264",
        "-preset", "fast",
        "-crf",  "23",
        "-c:a",  "aac",
        "-b:a",  "192k",
        "-t",    str(duration_s),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(SHORT_OUTPUT),
    ]

    print("   ffmpeg renderizando...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("ffmpeg falhou ao renderizar o Short")

    size_mb = os.path.getsize(SHORT_OUTPUT) / (1024 * 1024)
    print(f"   Short: {SHORT_OUTPUT} ({size_mb:.1f}MB)")
    return str(SHORT_OUTPUT)


# ─── 8. Upload como Short ─────────────────────────────────
def upload_short(title, category, video_id, thumb_path):
    import google.oauth2.credentials as goc
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token_b64  = os.environ.get("YT_TOKEN_B64")
    token_data = json.loads(base64.b64decode(token_b64).decode())
    creds = goc.Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=["https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.upload"],
    )

    yt = build("youtube", "v3", credentials=creds)

    hashtags = {
        "rain":        "#nocturnoise #rainambience #shorts",
        "cozy":        "#nocturnoise #cozyambience #shorts",
        "nature":      "#nocturnoise #naturesounds #shorts",
        "jazz":        "#nocturnoise #jazzambience #shorts",
        "focus_noise": "#nocturnoise #brownnoise #shorts",
        "study":       "#nocturnoise #studyambience #shorts",
        "urban":       "#nocturnoise #cityambience #shorts",
    }

    description = (
        f"{title}\n\n"
        f"🎧 Full version → https://www.youtube.com/watch?v={video_id}\n\n"
        f"Nocturne Noise — sounds for wherever you want to be.\n"
        f"Subscribe → https://www.youtube.com/@NocturneNoiseYT\n\n"
        f"{hashtags.get(category, '#nocturnoise #shorts')}"
    )

    print(f"   Upload: {title} #shorts")
    media = MediaFileUpload(str(SHORT_OUTPUT), mimetype="video/mp4", resumable=True)

    request = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":           f"{title} #shorts",
                "description":     description,
                "tags":            ["shorts", "nocturne noise", "soundscape", category,
                                    "ambient", "lofi", "sleep sounds", "relaxing"],
                "categoryId":      "10",
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    short_id  = response["id"]
    short_url = f"https://www.youtube.com/shorts/{short_id}"
    print(f"   Publicado: {short_url}")

    # Thumbnail original (sem texto) — mais clean para o card do Short
    if thumb_path and Path(thumb_path).exists():
        try:
            yt.thumbnails().set(
                videoId=short_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg"),
            ).execute()
            print("   Thumbnail definida")
        except Exception as e:
            print(f"   Thumbnail falhou (não crítico): {e}")

    with open("last_short.json", "w") as f:
        json.dump({"id": short_id, "url": short_url, "title": title}, f, indent=2)

    return short_url


# ─── Main ──────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-upload", action="store_true")
    args_cli = ap.parse_args()

    print(f"\nNOCTURNE NOISE SHORTS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print("\n[1/7] Buscando último vídeo publicado...")
    video_id, video_title, category = get_latest_video()

    print("\n[2/7] Preparando áudio para o Short...")
    # Se o áudio já existe (passado via Artifact), pulamos o download
    if os.path.exists(str(SHORT_AUDIO)):
        print(f"   ✓ Usando áudio existente: {SHORT_AUDIO}")
        short_audio = str(SHORT_AUDIO)
    else:
        print("   Baixando áudio via yt-dlp (fallback)...")
        raw_audio = download_audio(video_id)
        print("\n[3/7] Cortando melhor trecho...")
        short_audio = cut_best_segment(raw_audio)
        # Limpa o raw
        try: os.remove(raw_audio)
        except: pass

    print("\n[4/7] Gerando título evocativo...")
    short_title = generate_short_title(video_title, category)

    print("\n[5/7] Gerando thumbnail 9:16...")
    thumb_path = generate_thumbnail(video_title, category)

    print("\n[6/7] Montando frame com título + renderizando com ffmpeg...")
    frame_path = add_title_to_frame(thumb_path, short_title)
    render_with_ffmpeg(frame_path, short_audio, duration_s=59)

    if not args_cli.skip_upload:
        print("\n[7/7] Fazendo upload do Short...")
        url = upload_short(short_title, category, video_id, thumb_path)
        print(f"\n✓ SHORT PUBLICADO: {url}")
    else:
        print("\n⚠️  Upload pulado (--skip-upload)")

    # Cleanup: só deleta se não for o arquivo de artefato original baixado
    for f in [str(SHORT_AUDIO), str(SHORT_FRAME)]:
        try:
            # Se baixamos via yt-dlp, limpamos. Se veio via Artifact, o workflow limpa no final.
            if Path(f).exists():
                Path(f).unlink(missing_ok=True)
        except Exception:
            pass

    print(f"  Título: {short_title}")
    print(f"  Baseado em: {video_title}")


if __name__ == "__main__":
    main()
