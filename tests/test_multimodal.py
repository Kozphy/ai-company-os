"""Real-media integration and safety tests for the P0 renderer."""
import hashlib
import json
import shutil
import subprocess

import pytest

from company_os.multimodal import render

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _manifest(tmp_path, **patch):
    spec = {"image": "frame.png", "audio": "voice.wav",
            "duration_seconds": 1.0, "width": 320, "height": 180}
    spec.update(patch)
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_rejects_traversal_and_extra_fields_before_encoder(tmp_path):
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(ValueError, match="invalid or out-of-root"):
        render(_manifest(tmp_path, image="../secrets.png"), destination)
    with pytest.raises(ValueError, match="unexpected manifest"):
        render(_manifest(tmp_path, unknown=True), destination)
    with pytest.raises(ValueError, match="dimensions"):
        render(_manifest(tmp_path, width=319), destination)
    assert not list(destination.iterdir())


def test_rejects_symlink_source(tmp_path):
    (tmp_path / "real.png").write_bytes(b"placeholder")
    (tmp_path / "frame.png").symlink_to(tmp_path / "real.png")
    (tmp_path / "out").mkdir()
    with pytest.raises(ValueError, match="symlink"):
        render(_manifest(tmp_path), tmp_path / "out")


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg and FFprobe required for real-media test")
def test_real_mp4_audio_video_probe_and_evidence(tmp_path):
    image = tmp_path / "frame.png"
    audio = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=320x180", "-frames:v", "1",
                    "-y", str(image)], check=True, timeout=30)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1", "-ac", "1",
                    "-y", str(audio)], check=True, timeout=30)
    destination = tmp_path / "out"
    destination.mkdir()
    manifest = _manifest(tmp_path)
    report = render(manifest, destination)
    video = destination / "campaign.mp4"
    evidence = json.loads((destination / "evidence.json").read_text())
    assert video.read_bytes()[:1] != b"{"  # actual media, not a fabricated JSON artifact
    assert b"ftyp" in video.read_bytes()[:64]
    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert evidence["output"]["sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert evidence["human_approval"] == "REQUIRED_BEFORE_PUBLICATION"
    with pytest.raises(FileExistsError):
        render(manifest, destination)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg and FFprobe required")
def test_missing_audio_fails_closed_without_artifacts(tmp_path):
    (tmp_path / "frame.png").write_bytes(b"unused")
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(ValueError, match="invalid or out-of-root"):
        render(_manifest(tmp_path), destination)
    assert not list(destination.iterdir())
