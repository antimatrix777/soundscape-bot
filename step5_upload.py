"""
ETAPA 5 — Upload para YouTube (YouTube Data API v3 — GRÁTIS)
Faz upload do vídeo com metadata completo + thumbnail.

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

# ─────────────────────────────────────────────────────────
# PLAYLIST IDs — create these manually on YouTube Studio
# once, then paste the IDs here.
# Each category maps to a playlist.
# Leave empty string "" if not created yet — will skip.
# ─────────────────────────────────────────────────────────
PLAYLIST_IDS = {
    "rain":        os.environ.get("PLAYLIST_RAIN", ""),
    "nature":      os.environ.get("PLAYLIST_NATURE", ""),
    "cozy":        os.environ.get("PLAYLIST_COZY", ""),
    "jazz":        os.environ.get("PLAYLIST_JAZZ", ""),
    "focus_noise": os.environ.get("PLAYLIST_FOCUS", ""),
    "study":       os.environ.get("PLAYLIST_STUDY", ""),
    "urban":       os.environ.get("PLAYLIST_URBAN", ""),
}

# Mapeamento de categoria para ID do YouTube
YT_CATEGORY_IDS = {
    "Music": "10",
    "Entertainment": "24",
    "Education": "27",
    "People & Blogs": "22",
    "Howto & Style": "26",
}


def get_credentials():
    """Obtém credenciais OAuth — do arquivo ou da variável de ambiente (GitHub Actions)."""

    # GitHub Actions: token salvo como secret YT_TOKEN_B64
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

    # Local: usa token.json salvo
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
        "token.json não encontrado. Execute: python step5_upload.py --auth-only"
    )


def authenticate():
    """Autenticação interativa — roda UMA VEZ na máquina local."""
    if not os.path.exists("client_secrets.json"):
        raise FileNotFoundError(
            "client_secrets.json não encontrado.\n"
            "Baixe em: Google Cloud Console → APIs & Services → Credentials"
        )

    flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
    creds = flow.run_local_server(port=0)

    # Salva token para uso futuro
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }
    with open("token.json", "w") as f:
        json.dump(token_data, f, indent=2)

    # Mostra versão base64 para colar no GitHub Secrets
    b64 = base64.b64encode(json.dumps(token_data).encode()).decode()
    print("\n✅ Autenticação concluída! token.json salvo.")
    print("\n" + "="*60)
    print("COPIE o valor abaixo e salve como secret YT_TOKEN_B64 no GitHub:")
    print("="*60)
    print(b64)
    print("="*60 + "\n")

    return creds


def upload_video(video_file, metadata_file=None, thumbnail_file="thumbnail.jpg"):
    """Faz upload do vídeo com metadata e thumbnail."""

    # Lê metadata
    if not metadata_file:
        meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
        if not meta_files:
            raise FileNotFoundError("Metadata não encontrado. Rode step1 primeiro.")
        metadata_file = meta_files[0]

    with open(metadata_file) as f:
        metadata = json.load(f)

    if not os.path.exists(video_file):
        # Tenta encontrar automaticamente
        videos = glob.glob("video_*.mp4")
        if not videos:
            raise FileNotFoundError(f"Vídeo não encontrado: {video_file}")
        video_file = sorted(videos, key=os.path.getmtime, reverse=True)[0]

    print(f"\n📤 Fazendo upload do vídeo...")
    print(f"   🎬 Arquivo: {video_file}")
    print(f"   📋 Metadata: {metadata_file}")

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    # Sanitiza tags — YouTube e muito rigoroso com keywords
    def sanitize_tags(tags):
        import re
        if not isinstance(tags, list):
            return []
        expanded = []
        for tag in tags:
            tag = str(tag).strip()
            # Se a tag tem virgula, divide em multiplas tags
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
            # Remove TODOS os caracteres especiais exceto letras, numeros, espacos e hifens
            tag = re.sub(r"[^a-zA-Z0-9\s\-\u00C0-\u024F]", "", tag)  # keep accented chars
            tag = re.sub(r"\s+", " ", tag).strip()
            tag = tag[:50]  # max 50 chars por tag (conservador)
            low = tag.lower()
            if tag and len(tag) >= 2 and low not in seen:
                seen.add(low)
                clean.append(tag)
            if len(clean) >= 25:  # max 25 tags (conservador, limite e 500 chars total)
                break
        return clean

    raw_tags  = metadata.get("tags", [])
    sanitized = sanitize_tags(raw_tags)
    print(f"   Tags: {len(raw_tags)} originais -> {len(sanitized)} aprovadas")
    print(f"   Amostra: {sanitized[:5]}")

    # Body do request
    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": metadata["description"][:5000],
            "tags": sanitized,
            "categoryId": metadata.get("youtube_category_id", "10"),
            "defaultLanguage": "en",  # English content for max CPM reach
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        }
    }

    media = MediaFileUpload(
        video_file,
        chunksize=50 * 1024 * 1024,  # chunks de 50MB
        resumable=True,
        mimetype="video/mp4"
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    # Upload com progress
    response = None
    last_pct = -1
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
    print(f"\n   Upload done! Video ID: {video_id}")
    print(f"   https://www.youtube.com/watch?v={video_id}")

    # Add to category playlist
    category = metadata.get("category", "")
    add_to_playlist(youtube, video_id, category)

    # Post pinned ambience comment
    ambience_story = metadata.get("ambience_story", metadata.get("description", "")[:120])
    channel_url    = "https://www.youtube.com/@NocturneNoise"
    post_pinned_comment(youtube, video_id, ambience_story, channel_url)

    # Sobe thumbnail
    if os.path.exists(thumbnail_file):
        print(f"   🖼  Enviando thumbnail...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_file, mimetype="image/jpeg")
        ).execute()
        print(f"   ✅ Thumbnail enviada!")

    # Salva ID do vídeo publicado
    with open("last_upload.json", "w") as f:
        json.dump({"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
                   "metadata_file": metadata_file, "video_file": video_file}, f, indent=2)

    return video_id


def add_to_playlist(youtube, video_id, category):
    """Adds video to the category playlist. Skips if playlist ID not configured."""
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


def post_pinned_comment(youtube, video_id, ambience_story, channel_url):
    """Posts and pins an ambience comment on the video."""
    try:
        # Post the comment
        response = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": (
                                f"{ambience_story}\n\n"
                                f"Save this for tonight. 🌙\n"
                                f"More sounds every week → {channel_url}"
                            )
                        }
                    }
                }
            }
        ).execute()
        comment_id = response["snippet"]["topLevelComment"]["id"]
        print(f"   Comment posted: {comment_id}")

        # Pin the comment
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
                   help="Apenas autentica e gera token.json (rode na máquina local 1x)")
    p.add_argument("--video", type=str, default=None, help="Arquivo de vídeo")
    p.add_argument("--metadata", type=str, default=None, help="Arquivo metadata JSON")
    args = p.parse_args()

    if args.auth_only:
        authenticate()
    else:
        video_file = args.video or "final_video.mp4"
        upload_video(video_file, args.metadata)


if __name__ == "__main__":
    main()
