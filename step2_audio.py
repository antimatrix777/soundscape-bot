"""
step2_audio.py
Baixa e processa áudio de chuva/raios para o canal Nocturne Noise.

Mudanças desta versão:
  - Removida toda lógica de detecção/rejeição de vozes e barulhos externos
    (sons de chuva e raios naturalmente têm elementos externos — isso é esperado)
  - Alvo de loudness: -20 dBFS RMS (confortável para dormir, sem clipar)
  - Normalização com compressão suave para manter dinâmica natural da chuva
  - Looping contínuo sem cortes abruptos (crossfade entre loops)
  - Saída: WAV 48kHz / 16-bit (compatível com ffmpeg para montar o vídeo)
"""

import os
import sys
import json
import random
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import yt_dlp
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configurações de áudio ────────────────────────────────────────────────────

SAMPLE_RATE    = 48_000   # Hz — padrão YouTube
BIT_DEPTH      = 16       # bits
CHANNELS       = 2        # stereo
TARGET_DBUS    = -20.0    # dBFS RMS alvo (confortável para dormir)
TARGET_PEAK    = -1.0     # dBFS peak máximo (headroom para evitar clipping)
CROSSFADE_MS   = 8_000    # 8s de crossfade entre loops (transição suave)
MIN_SOURCE_SEC = 60       # áudio fonte precisa ter ao menos 60s
MAX_SOURCE_SEC = 7_200    # ignora fontes maiores que 2h (performance)

# Compressor suave — preserva dinâmica natural da chuva
COMPRESSOR_SETTINGS = dict(
    threshold=-25.0,   # dBFS — só comprime acima disso
    ratio=2.5,         # compressão leve
    attack=50,         # ms
    release=300,       # ms
)

# ── Fontes de busca ───────────────────────────────────────────────────────────

SEARCH_SOURCES = [
    "ytsearch5:{query} no copyright",
    "ytsearch5:{query} free download",
    "ytsearch3:{query} royalty free",
]

# ── Funções auxiliares ────────────────────────────────────────────────────────

def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    log.debug("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _duration_seconds(path: str) -> float:
    """Retorna duração de um arquivo de áudio via ffprobe."""
    result = _run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", path,
    ])
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def _measure_rms_dbfs(audio: AudioSegment) -> float:
    """Calcula RMS em dBFS de um AudioSegment."""
    return audio.dBFS


def _apply_loudness_target(audio: AudioSegment, target_dbfs: float = TARGET_DBUS) -> AudioSegment:
    """
    Normaliza o áudio ao alvo de dBFS RMS.
    Usa compressão suave antes de normalizar para preservar a dinâmica natural.
    """
    # 1. Compressão suave para uniformizar picos sem matar a naturalidade
    audio = compress_dynamic_range(
        audio,
        threshold=COMPRESSOR_SETTINGS["threshold"],
        ratio=COMPRESSOR_SETTINGS["ratio"],
        attack=COMPRESSOR_SETTINGS["attack"],
        release=COMPRESSOR_SETTINGS["release"],
    )

    # 2. Ajuste de ganho para atingir o RMS alvo
    current_dbfs = audio.dBFS
    if current_dbfs == float("-inf"):
        log.warning("Áudio silencioso detectado — pulando normalização.")
        return audio

    gain_needed = target_dbfs - current_dbfs
    audio = audio.apply_gain(gain_needed)

    # 3. Hard ceiling no peak para evitar clipping
    peak = audio.max_dBFS
    if peak > TARGET_PEAK:
        audio = audio.apply_gain(TARGET_PEAK - peak)

    log.info(f"Loudness: {current_dbfs:.1f} → {audio.dBFS:.1f} dBFS RMS (alvo {target_dbfs} dBFS)")
    return audio


def _loop_to_duration(audio: AudioSegment, target_ms: int, crossfade_ms: int = CROSSFADE_MS) -> AudioSegment:
    """
    Faz loop do áudio até atingir target_ms com crossfade suave entre repetições.
    """
    if len(audio) >= target_ms:
        return audio[:target_ms]

    log.info(f"Fazendo loop: {len(audio) / 1000:.0f}s → {target_ms / 1000:.0f}s (crossfade {crossfade_ms / 1000:.0f}s)")
    result = audio
    while len(result) < target_ms + crossfade_ms:
        result = result.append(audio, crossfade=crossfade_ms)

    return result[:target_ms]


def _convert_to_wav(input_path: str, output_path: str) -> bool:
    """Converte qualquer áudio para WAV 48kHz/16bit/stereo via ffmpeg."""
    try:
        _run([
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-sample_fmt", "s16",
            output_path,
        ])
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg falhou: {e.stderr}")
        return False


# ── Download via yt-dlp ───────────────────────────────────────────────────────

def _ydl_opts(output_template: str) -> dict:
    return {
        "format":           "bestaudio/best",
        "outtmpl":          output_template,
        "quiet":            True,
        "no_warnings":      True,
        "noplaylist":       True,
        "postprocessors": [{
            "key":            "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "0",
        }],
    }


def download_audio(search_terms: list[str], output_dir: str) -> Optional[str]:
    """
    Tenta baixar áudio de chuva/raios usando os search_terms.
    Retorna caminho do arquivo WAV baixado ou None se falhar.

    Nota: NÃO filtra sons externos — trovões, chuva pesada, gotas,
    folhas, etc. são esperados e desejados para sons de chuva.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Embaralha para variedade entre runs
    terms = list(search_terms)
    random.shuffle(terms)

    for term in terms:
        log.info(f"Buscando: '{term}'")
        query = f"ytsearch5:{term} no copyright"
        tmp_template = os.path.join(output_dir, "%(id)s.%(ext)s")

        try:
            with yt_dlp.YoutubeDL(_ydl_opts(tmp_template)) as ydl:
                results = ydl.extract_info(query, download=False)
                entries = results.get("entries", [])

                for entry in entries:
                    if not entry:
                        continue

                    duration = entry.get("duration", 0)
                    title    = entry.get("title", "")

                    # Filtro básico de duração
                    if duration < MIN_SOURCE_SEC:
                        log.debug(f"Pulando '{title}' — muito curto ({duration}s)")
                        continue
                    if duration > MAX_SOURCE_SEC:
                        log.debug(f"Pulando '{title}' — muito longo ({duration}s)")
                        continue

                    log.info(f"Baixando: '{title}' ({duration}s)")
                    try:
                        ydl.download([entry["webpage_url"]])
                    except Exception as e:
                        log.warning(f"Falha no download: {e}")
                        continue

                    # Localizar arquivo baixado
                    wav_files = list(Path(output_dir).glob(f"{entry['id']}*.wav"))
                    if wav_files:
                        log.info(f"✅ Áudio baixado: {wav_files[0].name}")
                        return str(wav_files[0])

        except Exception as e:
            log.warning(f"Erro na busca '{term}': {e}")
            continue

    log.error("Nenhum áudio encontrado após todas as tentativas.")
    return None


# ── Pipeline principal ────────────────────────────────────────────────────────

def process_audio(
    source_path: str,
    output_path: str,
    hours: int = 8,
) -> bool:
    """
    Processa o áudio fonte para o formato final do vídeo:
      1. Converte para WAV 48kHz/16bit/stereo
      2. Normaliza loudness para -20 dBFS (confortável para dormir)
      3. Faz loop com crossfade até atingir a duração desejada
      4. Salva o arquivo final

    Args:
        source_path: Caminho do WAV fonte baixado.
        output_path: Onde salvar o áudio processado.
        hours: Duração final em horas.

    Returns:
        True se bem-sucedido.
    """
    target_ms = hours * 3_600_000

    log.info(f"Processando: {source_path}")
    log.info(f"Duração alvo: {hours}h ({target_ms / 1000:.0f}s)")

    # 1. Converter para formato padrão
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if not _convert_to_wav(source_path, tmp_path):
            return False

        # 2. Carregar com pydub
        log.info("Carregando áudio...")
        audio = AudioSegment.from_wav(tmp_path)
        audio = audio.set_frame_rate(SAMPLE_RATE).set_channels(CHANNELS).set_sample_width(2)

        log.info(f"Fonte: {len(audio) / 1000:.0f}s | {audio.frame_rate}Hz | {audio.channels}ch | {audio.dBFS:.1f} dBFS")

        # 3. Normalizar loudness
        audio = _apply_loudness_target(audio, target_dbfs=TARGET_DBUS)

        # 4. Loop até duração alvo
        audio = _loop_to_duration(audio, target_ms=target_ms, crossfade_ms=CROSSFADE_MS)

        # 5. Salvar
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        log.info(f"Exportando: {output_path}")
        audio.export(
            output_path,
            format="wav",
            parameters=[
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                "-sample_fmt", "s16",
            ],
        )

        final_dur = len(audio) / 1000
        log.info(f"✅ Áudio final: {final_dur:.0f}s | {audio.dBFS:.1f} dBFS RMS")
        return True

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def run_pipeline(metadata_path: str, output_dir: str = "output") -> Optional[str]:
    """
    Pipeline completo: lê metadados → baixa → processa → salva.

    Args:
        metadata_path: Caminho do JSON gerado pelo step1_metadata.py
        output_dir: Diretório de saída

    Returns:
        Caminho do WAV final ou None se falhou.
    """
    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    variant_id    = meta["variant_id"]
    search_terms  = meta["search_terms"]
    hours         = meta.get("hours", 8)

    tmp_dir       = os.path.join(output_dir, "tmp_downloads")
    final_wav     = os.path.join(output_dir, f"{variant_id}_final.wav")

    # Download
    source = download_audio(search_terms, tmp_dir)
    if not source:
        log.error("Download falhou — abortando.")
        return None

    # Processamento
    success = process_audio(source, final_wav, hours=hours)

    # Limpar temp
    try:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    if success:
        log.info(f"✅ Pipeline concluído: {final_wav}")
        return final_wav

    return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Processa áudio de chuva/raios — Nocturne Noise")
    parser.add_argument("--metadata", type=str, required=True, help="JSON gerado pelo step1_metadata.py")
    parser.add_argument("--output",   type=str, default="output", help="Diretório de saída")
    args = parser.parse_args()

    result = run_pipeline(args.metadata, args.output)
    if result:
        print(f"\n✅ Áudio pronto: {result}")
        sys.exit(0)
    else:
        print("\n❌ Falha no pipeline de áudio.")
        sys.exit(1)
