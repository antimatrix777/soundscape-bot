"""
PIPELINE COMPLETO — Orquestrador Principal
Roda todas as 5 etapas em sequência.
Uso: python run_pipeline.py
     python run_pipeline.py --category jazz --duration 3
"""
import os, sys, glob, argparse, subprocess, json
from datetime import datetime

def run(script, extra_args=None):
    cmd = [sys.executable, script] + (extra_args or [])
    print(f"\n{'='*55}")
    print(f"▶ Rodando: {' '.join(cmd)}")
    print('='*55)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"❌ {script} falhou com código {result.returncode}")

def cleanup():
    """Remove arquivos temporários, mantém apenas o .json de log."""
    print("\n🧹 Limpando arquivos temporários...")
    to_delete = (
        glob.glob("output_audio.mp3") +
        glob.glob("background.jpg") +
        glob.glob("thumbnail.jpg") +
        glob.glob("video_*.mp4") +
        glob.glob("sounds_tmp/*.mp3")
    )
    for f in to_delete:
        try:
            os.remove(f)
            print(f"   🗑 {f}")
        except Exception as e:
            print(f"   ⚠ Não apagou {f}: {e}")

def main():
    p = argparse.ArgumentParser(description="Soundscape Bot — Pipeline Completo")
    p.add_argument("--category", choices=["rain","nature","cozy","jazz","focus_noise","study","urban"])
    p.add_argument("--duration", type=int, choices=[2,3,4])
    p.add_argument("--skip-upload", action="store_true", help="Pula o upload (útil para testes)")
    p.add_argument("--no-cleanup", action="store_true", help="Não apaga arquivos temporários")
    args = p.parse_args()

    start = datetime.now()
    print(f"\n🚀 SOUNDSCAPE BOT — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Categoria: {args.category or 'aleatório'}")
    print(f"   Duração: {args.duration or 'aleatório'}h")

    try:
        # 1. Metadata
        step1_args = []
        if args.category: step1_args += ["--category", args.category]
        if args.duration: step1_args += ["--duration", str(args.duration)]
        run("step1_metadata.py", step1_args)

        # 2. Áudio
        run("step2_audio.py")

        # 3. Imagem + Thumbnail
        run("step3_image.py")

        # 4. Vídeo
        run("step4_video.py")

        # 5. Upload
        if not args.skip_upload:
            run("step5_upload.py")
        else:
            print("\n⏭ Upload pulado (--skip-upload)")

        # Log final
        elapsed = datetime.now() - start
        mins = int(elapsed.total_seconds() // 60)
        print(f"\n{'='*55}")
        print(f"✅ PIPELINE CONCLUÍDO em {mins} minutos!")

        if os.path.exists("last_upload.json"):
            with open("last_upload.json") as f:
                info = json.load(f)
            print(f"🎬 Vídeo publicado: {info['url']}")
        print('='*55)

    except RuntimeError as e:
        print(f"\n{e}")
        sys.exit(1)
    finally:
        if not args.no_cleanup:
            cleanup()

if __name__ == "__main__":
    main()
