# Example take: coral reefs (synthetic voice)

**Load example take** (Report tab or Takes tab) copies this folder into a new take and analyzes it. No microphone and no speech model are needed: the transcript is committed.

- `audio.wav`: the synthetic fixture from `tests/fixtures/fixture.wav`. It is 33.7 s of Windows text-to-speech with planted delivery: one `[KEY]` line sped up 1.3×, one slowed to 0.8×, a missing `/`, a short `/` and a long `//`. Ground truth is in `tests/fixtures/fixture_truth.json`.
- `script.md`: `tests/fixtures/fixture_script.md`.
- `transcript.json`: one run of the local speech-to-text on `audio.wav`, committed as produced. It was made on the dev machine with faster-whisper `small.en` on `cuda/float16`; the model and device are recorded in the file. Whisper heard "bleaching" as "leaching" and added a "Thanks." before "Thank you." Those are real recognizer errors, left in on purpose.

To regenerate the transcript (the result may differ slightly by model and device):

```powershell
uv run python -c "import json; from take_two.audio import load_audio; from take_two.stt import get_transcriber; t = get_transcriber().transcribe(load_audio('examples/coral/audio.wav')); open('examples/coral/transcript.json', 'w', encoding='utf-8', newline='\n').write(json.dumps(t.to_dict(), indent=1) + '\n')"
```

The voice is synthetic. Use this take to see what the report looks like, not as evidence about a real speaker.
