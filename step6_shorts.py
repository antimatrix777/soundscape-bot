"""
STEP 6 — Shorts Generator (Nocturne Noise)
==========================================
Cron separado: roda ~6h depois do vídeo longo.

Fluxo:
  1. YouTube API → pega último vídeo publicado (título, ID, categoria)
  2. yt-dlp      → baixa áudio do vídeo longo
  3. pydub       → corta melhor trecho de 55s + fade seamless
  4. AI cascade  → gera título evocativo ÚNICO (Groq → Mistral → Gemini)
  5. AI cascade  → gera thumbnail 9:16 (IA ou Pexels) com prompt rotativo
  6. PIL         → escreve título na thumbnail com fade
  7. ffmpeg      → monta vídeo 1080x1920 com Ken Burns + fade de entrada/saída
  8. YouTube API → sobe como Short com link pro vídeo original

FIXES v2:
  - Title deduplication: used_short_titles.json prevents any title reuse within 30 days
  - AI cascade for titles: Groq → Mistral → Gemini (was Groq-only)
  - Enriched prompt with mood progression and anti-repetition constraints
  - Expanded fallback titles: 5 → 15 per category (emotional arcs)
  - Expanded image prompts: 1 → 8 per category with rotation tracking
  - SEO keyword prefix on Short titles for discoverability
  - Expanded tags: 8 → 15+ per category
"""
import os, json, subprocess, random, re, base64, requests, shutil, textwrap, time
from pathlib import Path
from datetime import datetime, timedelta
from pydub import AudioSegment
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO

load_dotenv()

# ─── Config ───────────────────────────────────────────────
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
MISTRAL_KEY  = os.environ.get("MISTRAL_API_KEY", "")
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
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

# ─── Title Deduplication ──────────────────────────────────
USED_SHORT_TITLES_FILE = "used_short_titles.json"
TITLE_HISTORY_DAYS     = 30  # títulos ficam bloqueados por 30 dias

def get_used_short_titles():
    """Retorna lista de títulos usados nos últimos TITLE_HISTORY_DAYS dias."""
    if not os.path.exists(USED_SHORT_TITLES_FILE):
        return {}
    try:
        with open(USED_SHORT_TITLES_FILE) as f:
            data = json.load(f)
        # Limpa entradas antigas (> 30 dias)
        cutoff = (datetime.now() - timedelta(days=TITLE_HISTORY_DAYS)).isoformat()
        cleaned = {t: ts for t, ts in data.items() if ts > cutoff}
        return cleaned
    except Exception:
        return {}

def save_short_title(title):
    """Salva título usado com timestamp."""
    used = get_used_short_titles()
    used[title.lower().strip()] = datetime.now().isoformat()
    with open(USED_SHORT_TITLES_FILE, "w") as f:
        json.dump(used, f, indent=2)

def is_title_duplicate(title, used_titles):
    """Verifica se o título é duplicado ou muito similar a algum já usado."""
    normalized = title.lower().strip().rstrip(".")
    for used in used_titles:
        used_norm = used.lower().strip().rstrip(".")
        # Exato
        if normalized == used_norm:
            return True
        # Muito similar (80%+ das palavras iguais)
        words_new  = set(normalized.split())
        words_used = set(used_norm.split())
        if len(words_new) > 0 and len(words_new & words_used) / max(len(words_new), 1) > 0.8:
            return True
    return False

# ─── SEO Keyword Prefixes ─────────────────────────────────
SHORT_SEO_KEYWORDS = {
    "rain": [
        "Rain Sounds", "Rain ASMR", "Rainy Night", "Storm Sounds",
        "Rain for Sleep", "Thunder Sounds", "Window Rain",
    ],
    "jazz": [
        "Late Night Jazz", "Jazz Piano", "Smooth Jazz", "Jazz Vibes",
        "Jazz Music", "Midnight Jazz", "Jazz Ambience",
    ],
    "lofi": [
        "Lofi Beats", "Lofi Chill", "Lofi Music", "Chill Beats",
        "Lofi Vibes", "Lofi Hip Hop", "Study Beats",
    ],
}

# ─── Expanded Image Prompts (8 per category) ─────────────
STYLE_BASE = (
    "nocturne lofi illustration, portrait 9:16, intimate night scene, "
    "warm amber lamp glow, crescent moon and city skyline through large window, "
    "cozy interior, houseplants, vinyl record, deep indigo night sky, "
    "warm golden light contrasting dark blue exterior, "
    "cinematic digital art, no text, no watermark, no people, "
    "high detail, painterly, dreamlike atmosphere"
)

CATEGORY_PROMPTS = {
    "rain": [
        f"rain drops on window glass at night, steaming coffee mug, warm desk lamp, city lights blurred through rain, {STYLE_BASE}",
        f"heavy thunderstorm viewed from bedroom window, blanket on chair, candle flickering, bookshelves, {STYLE_BASE}",
        f"rain on rooftop terrace at night, potted plants getting wet, warm interior light spilling out, {STYLE_BASE}",
        f"car windshield covered in rain at night, dashboard glow, city neon reflections, parked on quiet street, {STYLE_BASE}",
        f"rain falling on japanese garden at night, stone lantern, bamboo, misty atmosphere, warm window in background, {STYLE_BASE}",
        f"cozy reading nook by rainy window, stack of books, warm blanket, fairy lights, tea cup, {STYLE_BASE}",
        f"rain on cabin window in forest, fireplace glow, wool rug, wooden walls, {STYLE_BASE}",
        f"puddles reflecting neon signs in rain, empty alley at night, warm cafe window nearby, {STYLE_BASE}",
    ],
    "jazz": [
        f"vinyl record spinning on turntable, warm amber light, jazz album covers on shelf, headphones, {STYLE_BASE}",
        f"grand piano in empty jazz club, single spotlight, whiskey glass on piano, art deco interior, {STYLE_BASE}",
        f"saxophone resting on velvet chair, dim bar lighting, neon sign glow, glasses on counter, {STYLE_BASE}",
        f"paris cafe at night with accordion, cobblestone street, warm cafe lights, empty tables, {STYLE_BASE}",
        f"jazz musician silhouette behind frosted glass, warm interior, city lights outside, {STYLE_BASE}",
        f"old radio playing jazz in dimly lit room, bookshelf, armchair, warm lamp, night window, {STYLE_BASE}",
        f"rooftop jazz setup at dusk, trumpet and sheet music, city skyline, string lights, {STYLE_BASE}",
        f"vintage jukebox glowing in corner of empty diner at night, rain outside, warm booth, {STYLE_BASE}",
    ],
    "lofi": [
        f"cozy desk at night with headphones, lo-fi vinyl aesthetic, warm lamp glow, open notebook, city lights through window, {STYLE_BASE}",
        f"cat sleeping on desk next to laptop, fairy lights, warm room, night city view, cassette tapes, {STYLE_BASE}",
        f"rooftop at golden hour fading to dusk, headphones on railing, plants, sunset clouds, {STYLE_BASE}",
        f"vintage cassette player on wooden desk, polaroid photos pinned to wall, warm amber tones, {STYLE_BASE}",
        f"rainy window with desk lamp reflection, open sketchbook, colored pencils, coffee cup, {STYLE_BASE}",
        f"balcony at night with string lights, small table with tea, city below, headphones, plants, {STYLE_BASE}",
        f"train window at night, passing city lights, headphones on seat, warm interior, {STYLE_BASE}",
        f"cozy floor setup with vinyl player, cushions, warm blanket, fairy lights, rainy night, {STYLE_BASE}",
    ],
}

# Image prompt rotation tracking
USED_SHORT_PROMPTS_FILE = "used_short_prompts.json"

def get_rotated_prompt(category):
    """Retorna um prompt de imagem que não foi usado recentemente."""
    prompts = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["rain"])
    used = []
    if os.path.exists(USED_SHORT_PROMPTS_FILE):
        try:
            with open(USED_SHORT_PROMPTS_FILE) as f:
                used = json.load(f).get(category, [])
        except Exception:
            used = []

    # Filtra prompts não usados
    available = [i for i in range(len(prompts)) if i not in used]
    if not available:
        # Reset cycle
        available = list(range(len(prompts)))
        used = []

    chosen_idx = random.choice(available)
    used.append(chosen_idx)

    # Salva
    all_used = {}
    if os.path.exists(USED_SHORT_PROMPTS_FILE):
        try:
            with open(USED_SHORT_PROMPTS_FILE) as f:
                all_used = json.load(f)
        except Exception:
            pass
    all_used[category] = used
    with open(USED_SHORT_PROMPTS_FILE, "w") as f:
        json.dump(all_used, f, indent=2)

    return prompts[chosen_idx]


# ─── Expanded Fallback Titles (15 per category) ──────────
EVOCATIVE_FALLBACKS = {
    "rain": [
        # Discovery
        "still raining.", "you left the window open.", "it won't stop tonight.",
        # Comfort
        "the rain found you again.", "let it rain a little longer.",
        "this rain feels like home.", "nowhere to be, just rain.",
        # Nostalgia
        "the same rain from that night.", "you remember this sound.",
        "it rained like this once before.",
        # Mystery
        "the city disappears in rain.", "listen. just listen.",
        "something about tonight.", "the storm knows your name.",
        # Farewell
        "one last storm before dawn.",
    ],
    "jazz": [
        # Discovery
        "one more song.", "the piano player stayed late.", "the bar is almost empty.",
        # Comfort
        "nobody's leaving yet.", "just the music now.",
        "the last set before closing.", "somewhere a piano is playing.",
        # Nostalgia
        "this song played that night.", "you've heard this before.",
        "the same jazz, different city.",
        # Mystery
        "who's still playing at 3am?", "the piano started on its own.",
        "the bartender knows this song.", "smoke and slow keys.",
        # Farewell
        "the musician packed up slowly.",
    ],
    "lofi": [
        # Discovery
        "press play and disappear.", "the playlist never ends.",
        "headphones on, world off.",
        # Comfort
        "one more beat.", "stay in the loop.",
        "the coffee got cold hours ago.", "you forgot what time it is.",
        # Nostalgia
        "this beat feels familiar.", "somewhere you've been before.",
        "the same playlist from that summer.",
        # Mystery
        "who made this beat?", "the algorithm found you.",
        "3am and you're still here.", "the glow of one more screen.",
        # Farewell
        "last track before sleep.",
    ],
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
    if any(w in text for w in ["rain", "raining", "drizzle", "storm", "thunder", "lightning"]):
        return "rain"
    if any(w in text for w in ["jazz", "piano", "bossa", "saxophone"]):
        return "jazz"
    if any(w in text for w in ["lofi", "lo-fi", "lo fi", "chill beats", "hip hop beats"]):
        return "lofi"
    return "rain"


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


# ─── 4. Gera título evocativo via AI Cascade ─────────────
# Mood progression for 7-day cycle — gives the AI creative direction
MOOD_PROGRESSION = {
    1: "discovery — the listener just found this sound for the first time",
    2: "comfort — the listener is settling in, this feels familiar already",
    3: "immersion — the listener is fully absorbed, lost in the sound",
    4: "nostalgia — the sound reminds the listener of a specific moment",
    5: "mystery — something about tonight feels different",
    6: "intimacy — the sound feels personal, like it was made just for them",
    7: "farewell — the last listen before something changes",
}

def _build_title_prompt(video_title, category, used_titles_list):
    """Builds a rich, anti-repetition prompt for Short title generation."""
    day_of_week = int(datetime.now().strftime("%u"))  # 1=Monday ... 7=Sunday
    mood = MOOD_PROGRESSION.get(day_of_week, "mystery — something about tonight feels different")
    fallbacks = EVOCATIVE_FALLBACKS.get(category, EVOCATIVE_FALLBACKS["rain"])

    # Inject last 10 used titles to avoid repetition
    avoid_section = ""
    if used_titles_list:
        recent = list(used_titles_list)[-10:]
        avoid_section = "\n".join(f'  - "{t}"' for t in recent)
        avoid_section = f"\n\nNEVER use these titles (already used recently):\n{avoid_section}\n"

    example_titles = "\n  ".join(f'"{t}"' for t in random.sample(fallbacks, min(8, len(fallbacks))))

    return f"""You are writing a YouTube Short title for the ambient channel "Nocturne Noise".

Source video: "{video_title}"
Category: {category}
Today's mood: {mood}

RULES:
- Max 7 words, all lowercase, period at the end
- Second person ("you") or atmospheric scene-setting
- Evocative, cinematic, emotional — like a whisper, not a headline
- NO hashtags, NO emojis, NO category name literally
- Must feel UNIQUE — don't repeat patterns or structures from the examples
- Let today's mood ({mood.split('—')[0].strip()}) subtly influence the tone
{avoid_section}
Example titles for inspiration (do NOT copy these, create something NEW):
  {example_titles}

Output ONLY the title string, nothing else."""


def _call_groq_title(prompt):
    if not GROQ_KEY:
        raise ValueError("GROQ_API_KEY not set")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.95, "max_tokens": 30,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip().strip('"')


def _call_mistral_title(prompt):
    if not MISTRAL_KEY:
        raise ValueError("MISTRAL_API_KEY not set")
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_KEY}", "Content-Type": "application/json"},
        json={
            "model": "mistral-small-latest",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.95, "max_tokens": 30,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip().strip('"')


def _call_gemini_title(prompt):
    if not GEMINI_KEY:
        raise ValueError("GEMINI_API_KEY not set")
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip().strip('"')
    except ImportError:
        import google.generativeai as genai_old
        genai_old.configure(api_key=GEMINI_KEY)
        model = genai_old.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text.strip().strip('"')


TITLE_PROVIDERS = [
    ("Groq",    _call_groq_title),
    ("Mistral", _call_mistral_title),
    ("Gemini",  _call_gemini_title),
]


def generate_short_title(video_title, category):
    """Generates a unique, evocative Short title using AI cascade with deduplication."""
    used_titles = get_used_short_titles()
    used_titles_list = list(used_titles.keys())

    prompt = _build_title_prompt(video_title, category, used_titles_list)

    # Try each AI provider up to 2 times each
    for name, fn in TITLE_PROVIDERS:
        for attempt in range(2):
            try:
                print(f"   [{name}] Gerando título (tentativa {attempt+1})...")
                title = fn(prompt)
                # Validate
                if len(title) < 3 or len(title) > 70:
                    print(f"   [{name}] Título inválido (tamanho): '{title}'")
                    continue
                # Check for duplicates
                if is_title_duplicate(title, used_titles_list):
                    print(f"   [{name}] Título duplicado: '{title}' — tentando novamente")
                    # Add explicit avoidance to prompt for retry
                    prompt += f'\n\nDO NOT use: "{title}"'
                    continue
                print(f"   Título: {title}")
                return title
            except Exception as e:
                print(f"   [{name}] Falhou: {e}")
                break  # Move to next provider

    # Fallback — pick from expanded list, avoiding duplicates
    print("   Todos os providers falharam. Usando fallback criativo.")
    fallbacks = EVOCATIVE_FALLBACKS.get(category, EVOCATIVE_FALLBACKS["rain"])
    available = [t for t in fallbacks if not is_title_duplicate(t, used_titles_list)]
    if not available:
        available = fallbacks  # Reset if all used
    title = random.choice(available)
    print(f"   Título (fallback): {title}")
    return title


# ─── 5. Gera thumbnail 9:16 ───────────────────────────────
def generate_thumbnail(video_title, category):
    prompt = get_rotated_prompt(category)
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
# Expanded tags per category for better Shorts discovery
SHORT_TAGS = {
    "rain": [
        "shorts", "nocturne noise", "rain sounds", "rain asmr", "rain for sleep",
        "rainy night", "thunderstorm", "storm sounds", "window rain",
        "ambient", "sleep sounds", "asmr no talking", "relaxing",
        "rain ambience", "white noise",
    ],
    "jazz": [
        "shorts", "nocturne noise", "jazz", "smooth jazz", "jazz piano",
        "late night jazz", "jazz music", "instrumental jazz", "jazz ambience",
        "midnight jazz", "jazz cafe", "relaxing jazz", "jazz vibes",
        "background jazz", "jazz for studying",
    ],
    "lofi": [
        "shorts", "nocturne noise", "lofi", "lofi beats", "lofi hip hop",
        "chill beats", "lofi music", "study beats", "lofi chill",
        "lofi vibes", "anime lofi", "lofi radio", "relaxing beats",
        "lofi for studying", "chill lofi",
    ],
}

# Category-specific hashtags for Shorts (optimized for discovery)
SHORT_HASHTAGS = {
    "rain": "#nocturnoise #rainsounds #rainasmr #sleepsounds #asmr #shorts",
    "jazz": "#nocturnoise #jazz #smoothjazz #jazzpiano #jazzmusic #shorts",
    "lofi": "#nocturnoise #lofi #lofibeats #lofihiphop #chillbeats #shorts",
}


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

    hashtags = SHORT_HASHTAGS.get(category, "#nocturnoise #shorts")

    # SEO keyword prefix for discoverability
    seo_keyword = random.choice(SHORT_SEO_KEYWORDS.get(category, ["Ambient Sounds"]))

    # Build the upload title: "SEO Keyword • evocative hook #shorts"
    upload_title = f"{seo_keyword} • {title} #shorts"
    if len(upload_title) > 100:
        upload_title = f"{title} #shorts"

    description = (
        f"{title}\n\n"
        f"🎧 Full version → https://www.youtube.com/watch?v={video_id}\n\n"
        f"Nocturne Noise — sounds for wherever you want to be.\n"
        f"Subscribe → https://www.youtube.com/@NocturneNoiseYT\n\n"
        f"{hashtags}"
    )

    tags = SHORT_TAGS.get(category, SHORT_TAGS["rain"])

    print(f"   Upload: {upload_title}")
    media = MediaFileUpload(str(SHORT_OUTPUT), mimetype="video/mp4", resumable=True)

    request = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":           upload_title,
                "description":     description,
                "tags":            tags,
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
        json.dump({"id": short_id, "url": short_url, "title": upload_title}, f, indent=2)

    # Save to deduplication history
    save_short_title(title)

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

    print("\n[4/7] Gerando título evocativo ÚNICO...")
    short_title = generate_short_title(video_title, category)

    print("\n[5/7] Gerando thumbnail 9:16 (prompt rotativo)...")
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
