/**
 * OmniVoice TTS Plugin for OpenClaw
 * 
 * Adds OmniVoice as a TTS provider with:
 * - Voice Cloning: Clone any voice from 3-10s reference audio
 * - Voice Design: Create voices by description
 * - 600+ languages including Vietnamese
 * - Fast inference (40x realtime)
 * 
 * Usage in OpenClaw config:
 * {
 *   messages: {
 *     tts: {
 *       provider: "omnivoice",
 *       providers: {
 *         omnivoice: {
 *           model: "k2-fsa/OmniVoice",
 *           device: "cpu",
 *           defaultMode: "design",
 *           defaultInstruct: "female, vietnamese accent"
 *         }
 *       }
 *     }
 *   }
 * }
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

// Plugin state
let omnivoiceModel = null;
let config = {};

/**
 * Initialize the OmniVoice plugin
 */
function init(api, pluginConfig) {
  config = {
    model: pluginConfig?.model || 'k2-fsa/OmniVoice',
    device: pluginConfig?.device || 'cpu',
    defaultMode: pluginConfig?.defaultMode || 'design',
    defaultInstruct: pluginConfig?.defaultInstruct || 'female, vietnamese accent, natural',
    cacheDir: pluginConfig?.cacheDir || path.join(os.homedir(), '.openclaw', 'omnivoice'),
    ...pluginConfig
  };

  console.log('[OmniVoice] Plugin initialized');
  console.log(`[OmniVoice] Model: ${config.model}`);
  console.log(`[OmniVoice] Device: ${config.device}`);
  console.log(`[OmniVoice] Default mode: ${config.defaultMode}`);

  // Register TTS provider
  api.registerTtsProvider({
    id: 'omnivoice',
    name: 'OmniVoice',
    description: 'Voice cloning + 600 languages TTS',
    
    // Required methods
    synthesize: synthesize,
    getVoices: getVoices,
    getCapabilities: getCapabilities,
    
    // Optional
    supportsStreaming: false,
    maxTextLength: 10000,
  });

  // Register tools
  api.registerTool({
    name: 'omnivoice_tts',
    description: 'Generate speech using OmniVoice TTS with voice cloning or design',
    parameters: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'Text to speak' },
        mode: { 
          type: 'string', 
          enum: ['design', 'clone', 'auto'],
          description: 'Voice mode: design (describe voice), clone (use reference audio), auto (model chooses)'
        },
        instruct: { type: 'string', description: 'Voice design prompt (e.g., "female, vietnamese accent")' },
        refAudio: { type: 'string', description: 'Path to reference audio for cloning (3-10 seconds)' },
        refText: { type: 'string', description: 'Transcription of reference audio (optional, auto-transcribed)' },
        speed: { type: 'number', description: 'Speech speed (0.5-2.0)', default: 1.0 },
        outputFormat: { type: 'string', enum: ['wav', 'mp3'], default: 'wav' }
      },
      required: ['text']
    },
    handler: handleToolCall
  });

  return { success: true };
}

/**
 * Synthesize speech using OmniVoice
 */
async function synthesize(text, options = {}) {
  const {
    voice = config.defaultInstruct,
    mode = config.defaultMode,
    refAudio,
    refText,
    speed = 1.0,
    format = 'wav'
  } = options;

  // Create temp output file
  const tmpFile = path.join(os.tmpdir(), `omnivoice_${Date.now()}.${format}`);
  
  try {
    // Build Python command
    const pythonScript = buildPythonScript(text, tmpFile, {
      mode: mode,
      instruct: voice,
      refAudio: refAudio,
      refText: refText,
      speed: speed,
      format: format
    });

    // Execute Python script
    const result = execSync(`python3 -c '${pythonScript}'`, {
      timeout: 120000,  // 2 minutes
      encoding: 'utf-8',
      env: {
        ...process.env,
        HF_HOME: config.cacheDir,
        TRANSFORMERS_CACHE: config.cacheDir
      }
    });

    // Check output
    if (fs.existsSync(tmpFile)) {
      const audioBuffer = fs.readFileSync(tmpFile);
      
      // Cleanup
      try { fs.unlinkSync(tmpFile); } catch (e) {}
      
      return {
        success: true,
        audio: audioBuffer,
        format: format,
        sampleRate: 24000,
        duration: estimateDuration(audioBuffer, format)
      };
    }

    return { success: false, error: 'No output file generated' };

  } catch (error) {
    console.error('[OmniVoice] Synthesis error:', error.message);
    return { success: false, error: error.message };
  } finally {
    // Cleanup temp file
    try { if (fs.existsSync(tmpFile)) fs.unlinkSync(tmpFile); } catch (e) {}
  }
}

/**
 * Build Python script for OmniVoice
 */
function buildPythonScript(text, outputPath, options) {
  const { mode, instruct, refAudio, refText, speed, format } = options;
  
  // Escape text for Python
  const escapedText = text.replace(/'/g, "\\'").replace(/\n/g, "\\n");
  
  let pythonCode = `
import sys
import os

# Set cache directory
os.environ['HF_HOME'] = '${config.cacheDir}'
os.environ['TRANSFORMERS_CACHE'] = '${config.cacheDir}'

try:
    import torch
    from omnivoice import OmniVoice
    import soundfile as sf
    
    # Load model
    print("Loading OmniVoice model...", file=sys.stderr)
    model = OmniVoice.from_pretrained(
        "${config.model}",
        device_map="${config.device}",
        dtype=torch.float32
    )
    print("Model loaded!", file=sys.stderr)
    
    # Prepare generation kwargs
    gen_kwargs = {
        "text": "${escapedText}",
        "speed": ${speed}
    }
`;

  if (mode === 'clone' && refAudio) {
    pythonCode += `
    # Voice Cloning mode
    gen_kwargs["ref_audio"] = "${refAudio}"
`;
    if (refText) {
      pythonCode += `    gen_kwargs["ref_text"] = "${refText.replace(/"/g, '\\"')}"\n`;
    }
    pythonCode += `    print("Mode: Voice Cloning", file=sys.stderr)\n`;
  } else if (mode === 'design' || mode === 'auto') {
    const instructText = instruct || config.defaultInstruct;
    pythonCode += `
    # Voice Design mode
    gen_kwargs["instruct"] = "${instructText}"
    print("Mode: Voice Design (${instructText})", file=sys.stderr)
`;
  }

  pythonCode += `
    # Generate audio
    print("Generating speech...", file=sys.stderr)
    audio = model.generate(**gen_kwargs)
    
    # Save audio
    sf.write("${outputPath}", audio[0], 24000)
    print(f"Audio saved to ${outputPath}", file=sys.stderr)
    
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
`;

  return pythonCode;
}

/**
 * Get available voices (instruct options)
 */
function getVoices() {
  return [
    // Vietnamese
    { id: 'vi-female-natural', name: 'Vietnamese Female Natural', locale: 'vi-VN', gender: 'female', description: 'female, vietnamese accent, natural' },
    { id: 'vi-male-natural', name: 'Vietnamese Male Natural', locale: 'vi-VN', gender: 'male', description: 'male, vietnamese accent, natural' },
    { id: 'vi-female-southern', name: 'Vietnamese Female Southern', locale: 'vi-VN', gender: 'female', description: 'female, southern vietnamese accent' },
    { id: 'vi-male-southern', name: 'Vietnamese Male Southern', locale: 'vi-VN', gender: 'male', description: 'male, southern vietnamese accent' },
    { id: 'vi-female-northern', name: 'Vietnamese Female Northern', locale: 'vi-VN', gender: 'female', description: 'female, northern vietnamese accent' },
    { id: 'vi-male-northern', name: 'Vietnamese Male Northern', locale: 'vi-VN', gender: 'male', description: 'male, northern vietnamese accent' },
    
    // English
    { id: 'en-female-american', name: 'English Female American', locale: 'en-US', gender: 'female', description: 'female, american english' },
    { id: 'en-male-american', name: 'English Male American', locale: 'en-US', gender: 'male', description: 'male, american english' },
    { id: 'en-female-british', name: 'English Female British', locale: 'en-GB', gender: 'female', description: 'female, british accent' },
    
    // Chinese
    { id: 'zh-female-mandarin', name: 'Chinese Female Mandarin', locale: 'zh-CN', gender: 'female', description: 'female, mandarin chinese' },
    { id: 'zh-male-mandarin', name: 'Chinese Male Mandarin', locale: 'zh-CN', gender: 'male', description: 'male, mandarin chinese' },
    
    // Japanese
    { id: 'ja-female', name: 'Japanese Female', locale: 'ja-JP', gender: 'female', description: 'female, japanese' },
    { id: 'ja-male', name: 'Japanese Male', locale: 'ja-JP', gender: 'male', description: 'male, japanese' },
    
    // Korean
    { id: 'ko-female', name: 'Korean Female', locale: 'ko-KR', gender: 'female', description: 'female, korean' },
    { id: 'ko-male', name: 'Korean Male', locale: 'ko-KR', gender: 'male', description: 'male, korean' },
  ];
}

/**
 * Get plugin capabilities
 */
function getCapabilities() {
  return {
    provider: 'omnivoice',
    features: {
      voiceCloning: true,
      voiceDesign: true,
      streaming: false,
      ssml: false,
    },
    languages: [
      'vi', 'en', 'zh', 'ja', 'ko', 'fr', 'de', 'es', 'pt', 'ru',
      'ar', 'hi', 'th', 'id', 'ms', 'tl', 'tr', 'pl', 'nl', 'sv',
      // ... 600+ languages
    ],
    maxTextLength: 10000,
    sampleRate: 24000,
    formats: ['wav', 'mp3'],
  };
}

/**
 * Handle tool calls
 */
async function handleToolCall(params, context) {
  const { text, mode, instruct, refAudio, refText, speed, outputFormat } = params;
  
  if (!text) {
    return { success: false, error: 'No text provided' };
  }

  const result = await synthesize(text, {
    mode: mode || config.defaultMode,
    instruct: instruct || config.defaultInstruct,
    refAudio,
    refText,
    speed: speed || 1.0,
    format: outputFormat || 'wav'
  });

  if (result.success) {
    return {
      success: true,
      audio: result.audio,
      format: result.format,
      sampleRate: result.sampleRate,
      duration: result.duration,
      message: `Generated speech using OmniVoice (${mode || 'design'} mode)`
    };
  }

  return result;
}

/**
 * Estimate audio duration from buffer
 */
function estimateDuration(buffer, format) {
  // Rough estimate: WAV header contains duration info
  if (format === 'wav' && buffer.length > 44) {
    const sampleRate = buffer.readUInt32LE(24);
    const dataSize = buffer.readUInt32LE(40);
    return dataSize / (sampleRate * 2);  // 16-bit mono
  }
  return buffer.length / (24000 * 2);  // Estimate for 24kHz 16-bit
}

// Export for OpenClaw plugin system
module.exports = {
  init,
  synthesize,
  getVoices,
  getCapabilities,
  handleToolCall,
  name: 'omnivoice-tts',
  version: '1.0.0'
};
