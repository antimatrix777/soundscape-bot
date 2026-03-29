"""
PIPELINE COMPLETO — Orquestrador Principal
Roda todas as 5 etapas em sequência.

FIXES vs previous version:
  - subprocess.run agora tem timeout por step (era sem limite — causava cancelamento)
  - step2_audio tem 90min, step4_video tem 60min (ffmpeg é lento)
  - Erro de timeout reporta qual step falhou claramente
"""
import os, sys, glob, argparse, subprocess, json
from datetime import datetime

# ─────────────────────────────────────────────────────────
# TIMEOUTS POR STEP (em segundos)
# Ajuste se o seu pipeline consistentemente ultrapassar esses limites.
# ─────────────────────────────────────────────────────────
STEP_TIMEOUTS = {
    "step1_metadata.py": 120,    # 2 min  — só chama API de texto
    "step2_audio.py":    5400,   # 90 min — download + processamento de áudio
    "step3_image.py":    300,    # 5 min  — geração de imagem
    "step4_video.py":    3600,   # 60 min — ffmpeg encoding
    "step5_upload.py":   1800,   # 30 min — upload para YouTube
}

def run(script, extra_args=None):
    cmd         = [sys.executable, script] + (extra_args or [])
    script_name = os.path.basename(script)
    timeout_sec = STEP_TIMEOUTS.get(script_name, 600)

    print(f"\n{'='*55}")
    print(f"Rodando: {' '.join(cmd)}")
    print(f"Timeout: {timeout_sec//60} minutos")
    print(f"{'='*55}")

    try:
        result = subprocess.run(cmd, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        print(f"\n⏰ TIMEOUT: {script_name} ultrapassou {timeout_sec//60} minutos.")
        print(f"   Aumente STEP_TIMEOUTS['{script_name}'] se necessário.")
        raise RuntimeError(f"{script_name} cancelado por timeout ({timeout_sec//60}min)")

    if result.returncode != 0:
        raise RuntimeError(f"{script} falhou com codigo {result.returncode}")

def cleanup():
    print("\nLimpando arquivos temporarios...")
    # NOTE: short_audio_*.mp3 clips are EXCLUDED from cleanup to be used as artifacts for Shorts pool.
    for pat in ["output_audio.mp3", "background.jpg", "thumbnail.jpg",
                "video_*.mp4", "audio_tmp/*.mp3", "metadata_*.json"]:
        for f in glob.glob(pat):
            try:
                os.remove(f)
                print(f"   Removido: {f}")
            except Exception as e:
                print(f"   Nao removeu {f}: {e}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--category", choices=["rain","nature","cozy","jazz","focus_noise","study","urban"])
    p.add_argument("--duration", type=int, choices=[2,3,4])
    p.add_argument("--skip-upload", action="store_true")
    p.add_argument("--no-cleanup",  action="store_true")
    args = p.parse_args()

    start = datetime.now()
    print(f"\nSOUNDSCAPE BOT — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Categoria: {args.category or 'aleatorio'}")
    print(f"   Duracao:   {args.duration or 'aleatorio'}h")

    try:
        step1_args = []
        if args.category: step1_args += ["--category", args.category]
        if args.duration:  step1_args += ["--duration", str(args.duration)]

        run("step1_metadata.py", step1_args)
        run("step2_audio.py")
        run("step3_image.py")
        run("step4_video.py")

        if not args.skip_upload:
            run("step5_upload.py")
        else:
            print("\nUpload pulado (--skip-upload)")

        elapsed = int((datetime.now() - start).total_seconds() // 60)
        print(f"\n✅ PIPELINE CONCLUIDO em {elapsed} minutos!")

        if os.path.exists("last_upload.json"):
            with open("last_upload.json") as f:
                info = json.load(f)
            print(f"Video: {info.get('url','')}")

    except RuntimeError as e:
        print(f"\n❌ FALHA: {e}")
        sys.exit(1)
    finally:
        if not args.no_cleanup:
            cleanup()

if __name__ == "__main__":
    main()
