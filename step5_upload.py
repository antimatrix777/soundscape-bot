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

    # Body do request
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags", []),
            "categoryId": metadata.get("youtube_category_id", "10"),
            "defaultLanguage": "pt",
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
    print(f"\n✅ Upload concluído! Video ID: {video_id}")
    print(f"   🔗 https://www.youtube.com/watch?v={video_id}")

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
