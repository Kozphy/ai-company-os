"""Offline, human-approved single-scene video renderer. No network or model calls.

Input format: {"image":"frame.png","audio":"voice.wav","duration_seconds":2,
"width":640,"height":360}. Relative inputs resolve beside the manifest.
Only FFmpeg and FFprobe executables already on PATH are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}


def sha256_file(path: Path) -> str:
    """Hash file bytes without loading entire videos into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source(root: Path, name: object, allowed: set[str]) -> Path:
    """Allow only existing regular source files inside the manifest directory."""
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("source must be a relative path")
    candidate = root / name
    if candidate.is_symlink() or any(part.is_symlink() for part in candidate.parents if part != root.parent):
        raise ValueError("source symlinks are not allowed")
    path = candidate.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in allowed:
        raise ValueError("invalid or out-of-root media source")
    if path.stat().st_size == 0 or path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("source must be nonempty and at most 100 MiB")
    return path


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def render(manifest: Path, output_dir: Path) -> dict:
    """Render one MP4 and an integrity report; never overwrite existing artifacts.

    No external publication, uploads, automation, or generative model invoked.
    Raises on unsafe paths, malformed input, encoder failure, or QA failure.
    """
    manifest = manifest.resolve(strict=True)
    if not manifest.is_file() or manifest.stat().st_size > 16_384:
        raise ValueError("invalid manifest")
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) != {
        "image", "audio", "duration_seconds", "width", "height"
    }:
        raise ValueError("unexpected manifest fields")
    duration = spec["duration_seconds"]
    width, height = spec["width"], spec["height"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.5 <= duration <= 60:
        raise ValueError("duration must be 0.5..60 seconds")
    if (any(isinstance(n, bool) or not isinstance(n, int) or n < 16 or n > 1920 or n % 2
            for n in (width, height))):
        raise ValueError("dimensions must be even integers in 16..1920")
    root = manifest.parent
    image = _source(root, spec["image"], IMAGE_EXTENSIONS)
    audio = _source(root, spec["audio"], AUDIO_EXTENSIONS)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    if output_dir.is_symlink():
        raise ValueError("output directory symlink rejected")
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        raise ValueError("output directory must already exist")
    video = output_dir / "campaign.mp4"
    evidence = output_dir / "evidence.json"
    if video.exists() or evidence.exists():
        raise FileExistsError("artifacts already exist; use a new empty output directory")
    filter_graph = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
    )
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "25", "-i", str(image), "-i", str(audio),
        "-t", str(duration), "-vf", filter_graph,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-map", "0:v:0", "-map", "1:a:0", str(video),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=180)
        observed = _probe(video)
        streams = observed.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_present = any(s.get("codec_type") == "audio" for s in streams)
        actual_duration = float(observed.get("format", {}).get("duration", "0"))
        checks = {
            "mp4_nonempty": video.is_file() and video.stat().st_size > 1024,
            "video_stream": video_stream is not None,
            "audio_stream": audio_present,
            "dimensions": video_stream is not None
            and video_stream.get("width") == width and video_stream.get("height") == height,
            "duration_tolerance_0_3s": abs(actual_duration - duration) <= 0.3,
        }
        if not all(checks.values()):
            raise RuntimeError(f"render QA failed: {checks}")
        report = {
            "schema": "kozphy.multimodal-gtm.evidence.v1",
            "mode": "LOCAL_FFMPEG_REAL_RENDER",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "PASS",
            "human_approval": "REQUIRED_BEFORE_PUBLICATION",
            "publication": "DISABLED",
            "model_generation": "NOT_IMPLEMENTED",
            "manifest_sha256": sha256_file(manifest),
            "inputs_sha256": {"image": sha256_file(image), "audio": sha256_file(audio)},
            "output": {"filename": video.name, "sha256": sha256_file(video),
                       "size_bytes": video.stat().st_size, "duration_seconds": actual_duration},
            "checks": checks,
            "limitations": ["single static image scene", "existing input audio required",
                            "local ffprobe checks are not creative quality judgments",
                            "no external media generation, timeline editor or platform export"],
        }
        evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    except Exception:
        video.unlink(missing_ok=True)
        evidence.unlink(missing_ok=True)
        raise


def main() -> None:
    """CLI entrypoint: python -m company_os.multimodal manifest.json output-directory."""
    parser = argparse.ArgumentParser(description="Offline MP4 + audit evidence renderer")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    report = render(args.manifest, args.output_directory)
    print(json.dumps({"status": report["status"], "sha256": report["output"]["sha256"]}))


if __name__ == "__main__":
    main()
