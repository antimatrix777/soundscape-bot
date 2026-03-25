"""
ETAPA 5 — Upload para YouTube (YouTube Data API v3 — GRÁTIS)
Faz upload do vídeo com metadata completo + thumbnail.

FIXES vs previous version:
  - Pinned comment reescrito para maximizar retenção e inscritos
  - Comment agora usa ambience_story da description (hook cinematográfico)
  - CTA mais direto: salvar + inscrever + playlist
  - sanitize_tags sem alterações (estava OK)

SETUP ÚNICO (na sua máquina local):
  1. Baixe client_secrets.json do Google Cloud Console
  2. Execute: python step5_upload.py --auth-only
  3. Isso abre o browser, você autoriza, e gera token.json
  4. Salve token.json como secret no GitHub

USO NORMAL (GitHub Actions já faz isso):
  python step5_upload.py
"""
import os, json, glob, base64, argparse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

PLAYLIST_IDS = {
    "rain":        os.environ.get("PLAYLIST_RAIN", ""),
    "nature":      os.environ.get("PLAYLIST_NATURE", ""),
    "cozy":        os.environ.get("PLAYLIST_COZY", ""),
    "jazz":        os.environ.get("PLAYLIST_JAZZ", ""),
    "focus_noise": os.environ.get("PLAYLIST_FOCUS", ""),
    "study":       os.environ.get("PLAYLIST_STUDY", ""),
    "urban":       os.environ.get("PLAYLIST_URBAN", ""),
}

# Playlist names for the comment CTA (more readable than IDs)
PLAYLIST_NAMES = {
    "rain":        "Rain Sounds",
    "nature":      "Nature Sounds",
    "cozy":        "Cozy Ambience",
    "jazz":        "Jazz Collection",
    "focus_noise": "Focus & Brown Noise",
    "study":       "Study Music",
    "urban":       "City Sounds",
}

# Emoji and mood line per category — makes the pinned comment feel personal
CATEGORY_MOOD = {
    "rain":        ("🌧", "Put this on, close your eyes, and let the rain do the rest."),
    "nature":      ("🌿", "Disappear into this for a while. You've earned it."),
    "cozy":        ("☕", "This one's for the slow evenings. Pull up a chair."),
    "jazz":        ("🎷", "The kind of jazz that makes time feel different. Stay a while."),
    "focus_noise": ("🎧", "Block everything out. Just you and the work."),
    "study":       ("📚", "Put this on, get into the zone. You've got this."),
    "urban":       ("🌃", "Somewhere out there, the night is still going. Join it."),
}


def get_credentials():
    token_b64 = os.environ.get("YT_TOKEN_B64")
    if token_b64:
        token_data = json.loads(base64.b64decode(token_b64).decode())
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=SCOPES,
        )
        return creds

    if os.path.exists("token.json"):
        with open("token.json") as f:
            token_data = json.load(f)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=SCOPES,
        )
        return creds

    raise FileNotFoundError(
        "token.json nao encontrado. Execute: python step5_upload.py --auth-only"
    )


def authenticate():
    if not os.path.exists("client_secrets.json"):
        raise FileNotFoundError(
            "client_secrets.json nao encontrado.\n"
            "Baixe em: Google Cloud Console → APIs & Services → Credentials"
        )

    flow  = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes),
    }
    with open("token.json", "w") as f:
        json.dump(token_data, f, indent=2)

    b64 = base64.b64encode(json.dumps(token_data).encode()).decode()
    print("\n✅ Autenticação concluída! token.json salvo.")
    print("\n" + "="*60)
    print("COPIE o valor abaixo e salve como secret YT_TOKEN_B64 no GitHub:")
    print("="*60)
    print(b64)
    print("="*60 + "\n")

    return creds


def build_pinned_comment(metadata):
    """
    Build a retention-optimized pinned comment.

    Strategy:
    1. Open with the cinematic hook (2nd person, scene-setting) — creates emotional connection
    2. Mood line per category — reinforces the feeling
    3. CTA to save the video — boosts saves (strong watch-later signal to algorithm)
    4. CTA to subscribe with frequency reminder — converts passive viewers
    5. Playlist link — keeps them on the channel (watch time signal)
    """
    category      = metadata.get("category", "rain")
    channel_url   = "https://www.youtube.com/@NocturneNoise"
    description   = metadata.get("description", "")
    playlist_id   = PLAYLIST_IDS.get(category, "")
    playlist_name = PLAYLIST_NAMES.get(category, "More Sounds")
    emoji, mood   = CATEGORY_MOOD.get(category, ("🎧", "Enjoy."))

    # Extract just the hook (first 2 lines of description, before the use-case line)
    hook_lines = [l.strip() for l in description.split("\n") if l.strip()]
    hook       = " ".join(hook_lines[:2]) if len(hook_lines) >= 2 else hook_lines[0] if hook_lines else ""
    # Cap hook at 200 chars to keep comment tight
    if len(hook) > 200:
        hook = hook[:197] + "..."

    # Build playlist CTA line
    if playlist_id:
        playlist_url  = f"https://www.youtube.com/playlist?list={playlist_id}"
        playlist_line = f"📂 Full {playlist_name} playlist → {playlist_url}"
    else:
        playlist_line = f"📂 More sounds → {channel_url}/playlists"

    comment = (
        f"{hook}\n\n"
        f"{emoji} {mood}\n\n"
        f"⬇ Save this video — you'll want it again tonight.\n"
        f"🔔 New sounds twice a week → {channel_url}\n"
        f"{playlist_line}"
    )

    return comment


def upload_video(video_file, metadata_file=None, thumbnail_file="thumbnail.jpg"):
    if not metadata_file:
        meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
        if not meta_files:
            raise FileNotFoundError("Metadata nao encontrado. Rode step1 primeiro.")
        metadata_file = meta_files[0]

    with open(metadata_file) as f:
        metadata = json.load(f)

    if not os.path.exists(video_file):
        videos = glob.glob("video_*.mp4")
        if not videos:
            raise FileNotFoundError(f"Video nao encontrado: {video_file}")
        video_file = sorted(videos, key=os.path.getmtime, reverse=True)[0]

    print(f"\n📤 Fazendo upload do vídeo...")
    print(f"   🎬 Arquivo: {video_file}")
    print(f"   📋 Metadata: {metadata_file}")

    creds   = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    def sanitize_tags(tags):
        import re
        if not isinstance(tags, list):
            return []
        expanded = []
        for tag in tags:
            tag = str(tag).strip()
            if "," in tag:
                parts = [p.strip() for p in tag.split(",")]
                expanded.extend(parts)
            else:
                expanded.append(tag)
        clean = []
        seen  = set()
        for tag in expanded:
            tag = str(tag).strip()
            tag = tag.lstrip("#").lstrip("@")
            tag = re.sub(r"[^a-zA-Z0-9\s\-\u00C0-\u024F]", "", tag)
            tag = re.sub(r"\s+", " ", tag).strip()
            tag = tag[:50]
            low = tag.lower()
            if tag and len(tag) >= 2 and low not in seen:
                seen.add(low)
                clean.append(tag)
            if len(clean) >= 25:
                break
        return clean

    raw_tags  = metadata.get("tags", [])
    sanitized = sanitize_tags(raw_tags)
    print(f"   Tags: {len(raw_tags)} originais -> {len(sanitized)} aprovadas")
    print(f"   Amostra: {sanitized[:5]}")

    body = {
        "snippet": {
            "title":           metadata["title"][:100],
            "description":     metadata["description"][:5000],
            "tags":            sanitized,
            "categoryId":      metadata.get("youtube_category_id", "10"),
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":            "public",
            "selfDeclaredMadeForKids":  False,
            "madeForKids":              False,
        }
    }

    media = MediaFileUpload(
        video_file,
        chunksize=50 * 1024 * 1024,
        resumable=True,
        mimetype="video/mp4"
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    response  = None
    last_pct  = -1
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct != last_pct:
                    print(f"   ⬆ Upload: {pct}%")
                    last_pct = pct
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                print(f"   ⚠ Erro temporário ({e.resp.status}), tentando novamente...")
                continue
            raise

    video_id = response["id"]
    print(f"\n   ✅ Upload done! Video ID: {video_id}")
    print(f"   https://www.youtube.com/watch?v={video_id}")

    # Add to category playlist
    category = metadata.get("category", "")
    add_to_playlist(youtube, video_id, category)

    # Post pinned comment (retention-optimized)
    comment_text = build_pinned_comment(metadata)
    post_pinned_comment(youtube, video_id, comment_text)

    # Upload thumbnail
    if os.path.exists(thumbnail_file):
        print(f"   🖼  Enviando thumbnail...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_file, mimetype="image/jpeg")
        ).execute()
        print(f"   ✅ Thumbnail enviada!")

    with open("last_upload.json", "w") as f:
        json.dump({
            "video_id":      video_id,
            "url":           f"https://www.youtube.com/watch?v={video_id}",
            "metadata_file": metadata_file,
            "video_file":    video_file,
        }, f, indent=2)

    return video_id


def add_to_playlist(youtube, video_id, category):
    playlist_id = PLAYLIST_IDS.get(category, "")
    if not playlist_id:
        print(f"   Playlist for '{category}' not configured — skipping")
        return
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            }
        ).execute()
        print(f"   Added to playlist: {category} ({playlist_id})")
    except Exception as e:
        print(f"   Playlist add failed: {e}")


def post_pinned_comment(youtube, video_id, comment_text):
    """Posts and pins the retention-optimized comment."""
    try:
        response = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": comment_text
                        }
                    }
                }
            }
        ).execute()
        comment_id = response["snippet"]["topLevelComment"]["id"]
        print(f"   Comment posted: {comment_id}")
        print(f"   Preview: {comment_text[:80]}...")

        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published"
        ).execute()
        print(f"   Comment pinned OK")
    except Exception as e:
        print(f"   Comment post failed (non-critical): {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--auth-only", action="store_true",
                   help="Apenas autentica e gera token.json (rode na maquina local 1x)")
    p.add_argument("--video",    type=str, default=None, help="Arquivo de video")
    p.add_argument("--metadata", type=str, default=None, help="Arquivo metadata JSON")
    args = p.parse_args()

    if args.auth_only:
        authenticate()
    else:
        video_file = args.video or "final_video.mp4"
        upload_video(video_file, args.metadata)


if __name__ == "__main__":
    main()
