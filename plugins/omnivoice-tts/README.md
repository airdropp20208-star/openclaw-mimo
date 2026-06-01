# OmniVoice TTS Plugin for OpenClaw

Voice cloning + 600 languages TTS provider for OpenClaw.

## Features

- **Voice Cloning**: Clone any voice from 3-10s reference audio
- **Voice Design**: Create voices by description (female, vietnamese accent...)
- **600+ Languages**: Including Vietnamese, Chinese, English, Japanese, Korean
- **Fast Inference**: 40x faster than real-time

## Install

```bash
# Copy plugin to OpenClaw plugins directory
cp -r plugins/omnivoice-tts ~/.openclaw/plugins/

# Or install via npm
cd plugins/omnivoice-tts
npm install
```

## Configuration

Add to `~/.openclaw/config.yaml`:

```yaml
messages:
  tts:
    provider: omnivoice
    providers:
      omnivoice:
        model: k2-fsa/OmniVoice
        device: cpu  # or "cuda:0" for GPU
        defaultMode: design
        defaultInstruct: "female, vietnamese accent, natural"
```

## Usage

### Via OpenClaw Agent

```
/tts on
/tts provider omnivoice
/tts audio Xin chào các bạn
```

### Via Slash Commands

```
/tts audio Xin chào
/tts audio Hello world
/tts audio こんにちは
```

### Via Config

```yaml
messages:
  tts:
    auto: always
    provider: omnivoice
```

## Voice Modes

### Voice Design

Create a voice by description:

```yaml
# In config
defaultInstruct: "female, vietnamese accent, natural"

# Or per-call
/tts audio Xin chào --instruct "male, deep voice"
```

### Voice Cloning

Clone a voice from reference audio:

```yaml
# In config
refAudio: /path/to/voice_sample.wav
refText: "Transcription of reference"  # Optional
```

## Available Voices

| ID | Description | Locale |
|----|-------------|--------|
| vi-female-natural | Vietnamese Female Natural | vi-VN |
| vi-male-natural | Vietnamese Male Natural | vi-VN |
| en-female-american | English Female American | en-US |
| zh-female-mandarin | Chinese Female Mandarin | zh-CN |
| ja-female | Japanese Female | ja-JP |
| ko-female | Korean Female | ko-KR |

## Requirements

- Python 3.10+
- PyTorch (CPU or GPU)
- OmniVoice: `pip install omnivoice`
- Node.js 22+ (for OpenClaw)

## Troubleshooting

### Model download fails

```bash
# Set HuggingFace mirror
export HF_ENDPOINT=https://hf-mirror.com

# Or pre-download model
python3 -c "from omnivoice import OmniVoice; OmniVoice.from_pretrained('k2-fsa/OmniVoice')"
```

### Slow inference

- Use GPU: Set `device: "cuda:0"` in config
- Reduce text length: Split long text into chunks
- Use simpler voice design prompts

### Audio quality issues

- Ensure reference audio is 3-10 seconds
- Use clear audio without background noise
- For voice cloning, use same language as target

## License

MIT
