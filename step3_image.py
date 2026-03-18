import os, json, glob, time, requests, urllib.parse, random, base64, io
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

PEXELS_KEY  = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")

CHANNEL_NAME = "Comfort Sounds"

STYLE_BASE = (
    "lofi illustration, cozy night scene, warm amber lamp light, "
    "crescent moon visible through large window, city skyline at night, "
    "houseplants, detailed and atmospheric, digital art, "
    "no text, no watermark, cinematic lighting, "
    "deep blue night sky, golden warm interior light"
)

CATEGORY_PROMPTS = {
    "rain": [
        f"rain drops on window glass, cozy desk with steaming coffee mug, vinyl record player, open notebook, warm desk lamp, {STYLE_BASE}",
        f"heavy rain outside window at night, reading under blanket, candle light, bookshelf, plants, {STYLE_BASE}",
        f"rain on rooftop terrace, city lights blurred through rain, cozy indoor corner, tea cup, {STYLE_BASE}",
        f"rainy night street lamp reflection on wet pavement, viewed from cozy window, hot drink, {STYLE_BASE}",
    ],
    "nature": [
        f"misty forest at dawn through large window, wooden desk, fern plant, soft morning light, {STYLE_BASE}",
        f"ocean waves visible through floor-to-ceiling window, cozy reading chair, lighthouse in distance, {STYLE_BASE}",
        f"mountain stream and pine forest outside window, log cabin interior, fireplace glow, {STYLE_BASE}",
        f"bamboo forest swaying gently, japanese-inspired interior, tea ceremony set, zen atmosphere, {STYLE_BASE}",
    ],
    "cozy": [
        f"vintage coffee shop interior at night, exposed brick, warm Edison bulbs, vinyl records on wall, coffee and croissant, {STYLE_BASE}",
        f"crackling fireplace close-up, armchair with blanket, open book, cup of tea, cat sleeping, {STYLE_BASE}",
        f"old library with floor-to-ceiling bookshelves, reading nook, vintage lamp, stacked books, {STYLE_BASE}",
        f"cozy cabin in snowstorm, fireplace, hot cocoa with marshmallows, frost on window, pine trees outside, {STYLE_BASE}",
        f"japanese tea house at night, paper lanterns, wooden table, matcha tea, bonsai plant, {STYLE_BASE}",
    ],
    "jazz": [
        f"jazz musician silhouette at grand piano, late night bar, neon sign glow, saxophone on stand, {STYLE_BASE}",
        f"vintage jazz club interior, art deco lighting, small round tables, trumpet on stage, record player, {STYLE_BASE}",
        f"paris sidewalk cafe at night, accordion player, warm cafe lights, cobblestone street, {STYLE_BASE}",
        f"vinyl record spinning on turntable, warm amber light, bookshelf with jazz albums, headphones, {STYLE_BASE}",
        f"bossa nova beach bar at dusk, acoustic guitar, tropical plants, fairy lights, ocean in background, {STYLE_BASE}",
    ],
    "focus_noise": [
        f"minimalist home office at night, single desk lamp, open notebook, pencils, plant, clean aesthetic, {STYLE_BASE}",
        f"student desk late at night, glowing monitor, coffee cup, notes scattered, city view through window, {STYLE_BASE}",
        f"zen meditation corner, candle, cushion, soft light through curtain, {STYLE_BASE}",
        f"cozy bedroom at night, moonlight through window, peaceful, minimal decor, {STYLE_BASE}",
    ],
    "study": [
        f"late night study session, desk with open books and laptop, coffee, desk lamp, rain on window, {STYLE_BASE}",
        f"university library at night, long wooden table, stacked books, warm reading lamps, {STYLE_BASE}",
        f"bedroom desk study corner, fairy lights, sticky notes, textbooks, plant, {STYLE_BASE}",
        f"coffee shop study session at night, laptop, coffee, rainy window, cozy crowd, {STYLE_BASE}",
    ],
    "urban": [
        f"tokyo street at night in rain, neon signs reflected on wet streets, ramen shop glow, {STYLE_BASE}",
        f"paris rooftop at night, eiffel tower in distance, wine glass, fairy lights, warm bistro interior, {STYLE_BASE}",
        f"new york apartment window at night, manhattan skyline, rain on glass, interior lamp, {STYLE_BASE}",
        f"london rainy evening, red phone box, cobblestone street, pub warm light, fog, {STYLE_BASE}",
    ],
}


# ══════════════════════════════════════════════════════════
# FONTE 1: TOGETHER AI — FLUX.1 Schnell (melhor qualidade estetica)
# api.together.ai → cria conta gratis, sem cartao de credito
# 3 meses ilimitado gratis com FLUX.1 Schnell
# Adicione TOGETHER_API_KEY nos GitHub Secrets
# ══════════════════════════════════════════════════════════
def generate_with_together(prompt, width=1024, height=1024):
    key = os.environ.get("TOGETHER_API_KEY", "")
    if not key:
        raise ValueError("TOGETHER_API_KEY nao configurada")
    print(f"   [Together AI FLUX.1] Gerando...")
    r = requests.post(
        "https://api.together.xyz/v1/images/generations",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model":  "black-forest-labs/FLUX.1-schnell-Free",
            "prompt": prompt,
            "width":  width,
            "height": height,
            "steps":  4,
            "n":      1,
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    # Resposta pode ser URL ou base64
    item = data.get("data", [{}])[0]
    if item.get("url"):
        img_r = requests.get(item["url"], timeout=60)
        img   = Image.open(BytesIO(img_r.content)).convert("RGB")
    elif item.get("b64_json"):
        img = Image.open(BytesIO(base64.b64decode(item["b64_json"]))).convert("RGB")
    else:
        raise RuntimeError("Together AI: sem imagem na resposta")
    print(f"   -> Together AI: {img.width}x{img.height}")
    return img


# ══════════════════════════════════════════════════════════
# FONTE 2: GEMINI IMAGE API — 500 imagens/dia gratis
# Usa a GEMINI_API_KEY que voce ja tem configurada
# ══════════════════════════════════════════════════════════
def generate_with_gemini(prompt, width=1920, height=1080):
    if not GEMINI_KEY:
        raise ValueError("GEMINI_API_KEY nao configurada")
    print(f"   [Gemini Image] Gerando...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    # Extrai imagem base64 da resposta
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                img_data = base64.b64decode(part["inlineData"]["data"])
                img = Image.open(BytesIO(img_data)).convert("RGB")
                print(f"   -> Gemini: {img.width}x{img.height}")
                return img
    raise RuntimeError("Gemini nao retornou imagem na resposta")


# ══════════════════════════════════════════════════════════
# FONTE 2: POLLINATIONS.AI — gratis, sem API key
# ══════════════════════════════════════════════════════════
def generate_with_pollinations(prompt, width=1920, height=1080, attempt=0):
    print(f"   [Pollinations] Gerando (tentativa {attempt+1})...")
    seed = int(time.time()) + attempt * 1000
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}"
        f"&seed={seed}&nologo=true&enhance=true&model=flux"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    if "image" not in r.headers.get("content-type", ""):
        raise RuntimeError("Pollinations nao retornou imagem")
    img = Image.open(BytesIO(r.content)).convert("RGB")
    if img.width < 100 or img.height < 100:
        raise RuntimeError("Imagem muito pequena")
    print(f"   -> Pollinations: {img.width}x{img.height}")
    return img


# ══════════════════════════════════════════════════════════
# FONTE 3: PEXELS — foto real, fallback
# ══════════════════════════════════════════════════════════
def search_pexels(query):
    if not PEXELS_KEY:
        raise ValueError("PEXELS_API_KEY nao configurada")
    print(f"   [Pexels] '{query}'")
    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "orientation": "landscape", "size": "large", "per_page": 5},
        timeout=30,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"Pexels: nenhuma foto para '{query}'")
    best = max(photos, key=lambda p: p["width"] * p["height"])
    print(f"   -> Pexels: {best['width']}x{best['height']}")
    return best["src"]["original"]


# ══════════════════════════════════════════════════════════
# FONTE 4: PIXABAY — foto real, fallback final
# ══════════════════════════════════════════════════════════
def search_pixabay(query):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY nao configurada")
    print(f"   [Pixabay] '{query}'")
    r = requests.get("https://pixabay.com/api/", params={
        "key": PIXABAY_KEY, "q": query, "image_type": "photo",
        "orientation": "horizontal", "min_width": 1920,
        "per_page": 5, "safesearch": "true",
    }, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        raise RuntimeError(f"Pixabay: nenhuma imagem para '{query}'")
    best = max(hits, key=lambda h: h.get("imageWidth", 0) * h.get("imageHeight", 0))
    url = best.get("largeImageURL") or best.get("webformatURL")
    print(f"   -> Pixabay: {best.get('imageWidth')}x{best.get('imageHeight')}")
    return url


def download_image(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


# ══════════════════════════════════════════════════════════
# PROCESSAMENTO
# ══════════════════════════════════════════════════════════
def make_background(img, output="background.jpg"):
    W, H = 1920, 1080
    ratio = max(W / img.width, H / img.height)
    new_w, new_h = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top  = (new_h - H) // 2
    img  = img.crop((left, top, left + W, top + H))
    img  = ImageEnhance.Brightness(img).enhance(0.82)
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vignette)
    for i in range(180):
        alpha = int((i / 180) * 100)
        draw.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")
    img.save(output, "JPEG", quality=95)
    print(f"   Background: {output}")
    return img


def make_thumbnail(base_img, thumb_text, output="thumbnail.jpg"):
    W, H = 1280, 720
    img = base_img.resize((W, H), Image.LANCZOS)
    blur = img.filter(ImageFilter.GaussianBlur(radius=3))
    mask = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(mask)
    for i in range(60):
        alpha = int(255 * (i / 60))
        d.rectangle([i, i, W - i, H - i], fill=alpha)
    img = Image.composite(img, blur, mask)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(overlay)
    for i in range(H // 2):
        alpha = int((i / (H // 2)) * 190)
        d2.rectangle([(0, H // 2 + i), (W, H // 2 + i + 1)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    def get_font(size):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        for p in paths:
            if os.path.exists(p):
                try: return ImageFont.truetype(p, size)
                except: pass
        return ImageFont.load_default()

    font_main = get_font(72)
    font_sub  = get_font(28)
    text = thumb_text.upper()
    draw.text((W // 2 + 3, H - 160 + 3), text, font=font_main, fill=(0, 0, 0, 200), anchor="mm")
    draw.text((W // 2, H - 160), text, font=font_main, fill=(255, 255, 255), anchor="mm")
    draw.text((W - 24, H - 24), CHANNEL_NAME, font=font_sub, fill=(200, 200, 200), anchor="rb")
    draw.ellipse([(20, 20), (28, 28)], fill=(255, 180, 50))
    img.save(output, "JPEG", quality=93)
    kb = os.path.getsize(output) / 1024
    print(f"   Thumbnail: {output} ({kb:.0f}KB)")
    return img


# ══════════════════════════════════════════════════════════
# CASCADE — 4 fontes em ordem
# Gemini → Pollinations → Pexels → Pixabay
# ══════════════════════════════════════════════════════════
def get_image(category, pexels_query):
    prompts = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["cozy"])
    prompt  = random.choice(prompts)

    # 1. Together AI FLUX.1 Schnell (melhor qualidade estetica)
    try:
        img = generate_with_together(prompt)
        return img, "together_flux"
    except Exception as e:
        print(f"   Together AI falhou: {e}")

    # 2. Gemini Image (500/dia gratis, ja tem a key)
    try:
        img = generate_with_gemini(prompt)
        return img, "gemini"
    except Exception as e:
        print(f"   Gemini falhou: {e}")

    # 3. Pollinations (sem key, gratuito)
    for attempt in range(2):
        try:
            img = generate_with_pollinations(prompt, attempt=attempt)
            return img, "pollinations"
        except Exception as e:
            print(f"   Pollinations tentativa {attempt+1} falhou: {e}")
            time.sleep(3)

    # 4. Pexels (foto real)
    try:
        url = search_pexels(pexels_query)
        return download_image(url), "pexels"
    except Exception as e:
        print(f"   Pexels falhou: {e}")

    # 5. Pixabay (foto real, fallback final)
    url = search_pixabay(pexels_query)
    return download_image(url), "pixabay"


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")
    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata.get("category", "cozy")
    thumb_text = metadata.get("thumbnail_text", "Comfort Sounds")
    pexels_q   = metadata.get("theme_data", {}).get("pexels", metadata.get("theme", "cozy ambience"))

    print(f"\nGerando imagem: categoria={category}")
    print(f"Thumbnail text: {thumb_text}")

    img, source = get_image(category, pexels_q)
    print(f"   Fonte usada: {source}")

    bg = make_background(img, "background.jpg")
    make_thumbnail(bg, thumb_text, "thumbnail.jpg")
    print("\nEtapa 3 concluida!")


if __name__ == "__main__":
    main()
