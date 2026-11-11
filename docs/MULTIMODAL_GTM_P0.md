# Multimodal GTM Agent — P0 implementation and evidence boundary

**Status:** branch-only local rendering component; not merged, not deployed.

## Reviewed source boundaries

- **RepoRevenue** `src/lib/store.tsx`: asynchronous draft generation is `setTimeout` over mock data. The app's README explicitly states that GitHub, Postiz, Stripe and Supabase are not wired. It is a UI/proposal reference, **not** a media executor.
- **ai-company-os** `company_os/agents.py`, `jobs.py`, `worker.py`: existing five job kinds are designed for bounded, offline workflows with tenant and budget controls. P0 does **not** add a new queue kind or an API endpoint: doing so without media storage, tenancy, authorization, limits and worker isolation could weaken the current contract.
- **EvalForge** `finance_eval/evidence.py`: a useful precedent for hashes and explicit maturity labels. P0 uses standalone JSON plus SHA-256, **not** an EvalForge run or an LLM-evaluated artifact.

## Delivered P0

The module `company_os/multimodal.py` takes an already-created still image and an already-created audio track. It uses real local FFmpeg encoding to create `campaign.mp4` and uses FFprobe to inspect that encoded file. It writes `evidence.json` only after all deterministic checks pass.

**Requirements:** Python 3.11+, `ffmpeg`, `ffprobe` on PATH, an FFmpeg build with `libx264` and AAC encoding. No cloud credentials or external API calls.

Example in a temporary directory (create an image and audio using the FFmpeg test generators):

```bash
mkdir -p demo/out
ffmpeg -nostdin -f lavfi -i "color=c=blue:s=640x360" -frames:v 1 -y demo/frame.png
ffmpeg -nostdin -f lavfi -i "sine=frequency=440:duration=2" -y demo/voice.wav
cat > demo/campaign.json <<'JSON'
{"image":"frame.png","audio":"voice.wav","duration_seconds":2,"width":640,"height":360}
JSON
python -m company_os.multimodal demo/campaign.json demo/out
ffprobe -v error -show_streams demo/out/campaign.mp4
cat demo/out/evidence.json
```

Use a new empty output directory for each run. Inputs must be local regular files inside the manifest directory. No remote URLs, absolute source paths, symlinks or path traversal accepted. Images: PNG/JPEG. Audio: WAV/MP3/M4A. One image plus one audio file per render. Up to 60 seconds, with bounded dimensions and input sizes. Duration comparison tolerance is 0.3 seconds.

**Evidence contract (`kozphy.multimodal-gtm.evidence.v1`):**

- Hash of input manifest and each source file, plus produced MP4 hash/byte length.
- Actual `ffprobe` duration, video/audio stream presence, dimensions and deterministic PASS checks.
- Explicit required human sign-off and disabled publication.
- Local test results are not proof of production reliability or creative quality.

**Validation:**

```bash
python -m pytest tests/test_multimodal.py -q
ruff check company_os/multimodal.py tests/test_multimodal.py
```

CI runs Python 3.11/3.12 and the existing entire test suite. The media test uses synthetic stills and synthetic test tones; no AI-generated film or real customer creative is claimed.

## P1/P2 deliberately not implemented

- P1: authenticated tenant media store; durable async queue with per-tenant budget and rate limits; time-line/scene editing, many assets, version lineage, retry recovery and captions; explicit approval workflow. Implement a safe media/job boundary before enabling any queue integration.
- P2: optional image, audio and video model adapters with provider permissions and metering; platform-specific cuts; RepoRevenue server integration; EvalForge multimodal quality/regression evaluation; publish connectors with final human approval.

No merges, releases, external publication, production deployment, provider API keys or user data uploads are performed by P0.
