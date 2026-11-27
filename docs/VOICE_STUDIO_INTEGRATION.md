# Voice Studio Integration

The editor talks to [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio)
(inspected at commit `6fe6f4dd62b477ab5fbf4d94500e3c0298d05232`) over HTTP only.
**Nothing is installed or downloaded on the editor machine.** Voice Studio runs on the
Windows GPU PC; the editor connects to it.

## Status

- Implemented: connection settings, `GET /health`, `/engines`, `/v1/audio/voices` discovery,
  and editor routes `GET /api/voiceover/capabilities` and `GET /api/voiceover/voices`.
- Not implemented yet: speech generation (`POST /v1/audio/speech`), narration jobs.
- Live test against a real instance: **pending** (server not installed yet).

## Windows PC setup (when you are ready)

1. Install Voice Studio on Windows following its upstream README (NVIDIA driver + CUDA as it requires).
2. Pick and warm a model in its own UI. Do not use the default `k2-fsa/OmniVoice`
   weights (CC-BY-NC) for a commercial channel; record the weights/terms you choose.
3. Make it reachable from the Mac: bind to the LAN (not the public internet), allow the port
   (default 3900) through Windows Firewall for your private network only, and set
   `OMNIVOICE_API_KEY` on the server since loopback-only auth-free access no longer applies.
   Prefer a private network such as Tailscale over exposing the port.

## Editor configuration (`.env`)

```
VOICEOVER_PROVIDER=voice_studio
VOICE_STUDIO_BASE_URL=http://<windows-pc-ip>:3900
VOICE_STUDIO_API_KEY=<same value as OMNIVOICE_API_KEY>
VOICE_STUDIO_MODEL=<engine id chosen in Voice Studio>
```

Optional: `VOICE_STUDIO_CONNECT_TIMEOUT` (default 5s), `VOICE_STUDIO_GENERATION_TIMEOUT` (default 600s).
The key stays server-side and is never returned by the API.

## Verify the connection

```bash
curl http://localhost:8000/api/voiceover/capabilities   # reachable: true
curl http://localhost:8000/api/voiceover/voices
```

`reachable` only proves `/health` answers, not that a model is loaded.
If the server is down, manual narration import remains the fallback.
