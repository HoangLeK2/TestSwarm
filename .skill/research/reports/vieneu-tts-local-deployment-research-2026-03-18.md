# Research Report: Vieneu TTS SDK & Local ElevenLabs Alternative Implementation

**Research Date**: 2026-03-18
**Sources Consulted**: 5+ (Vieneu SDK docs, GitHub repos, WebSearch)
**Key Terms**: Vieneu TTS, Vietnamese TTS, local TTS deployment, ElevenLabs alternative, voice cloning

---

## Executive Summary

Vieneu-TTS is an open-source Vietnamese TTS SDK offering instant voice cloning and on-device inference, making it viable local alternative to ElevenLabs. SDK supports multiple operational modes (CPU/GPU/Remote) with models ranging 0.3B-0.5B parameters. For replacing ElevenLabs locally, best alternatives include: **Fish-Speech** (1-3s cloning), **GPT-SoVITS** (Vietnamese excellence), and **Vieneu-TTS** itself (CPU-optimized). Migration requires API wrapper layer, GPU hardware (RTX 3060+), and streaming implementation for latency reduction.

---

## Key Findings

### 1. Vieneu SDK Technology Overview

**What is Vieneu SDK?**
- Python library for Vietnamese text-to-speech with ultra-low latency
- Zero-shot voice cloning from 3-5 second audio samples
- Architecture: Transformer LLM (backbone) + NeuCodec (decoder)
- Models: 0.3B and 0.5B parameter variants
- Auto-downloads from HuggingFace, caches at `~/.cache/huggingface/hub/`

**Operational Modes:**

| Mode | Backend | Use Case | Hardware |
|------|---------|----------|----------|
| **standard** | GGUF/PyTorch | Universal CPU | Any CPU |
| **fast** | LMDeploy | High throughput | NVIDIA GPU |
| **remote** | HTTP API | Client-server | Network |
| **xpu** | Intel XPU | Intel optimization | Intel Arc GPU |

**Key Capabilities:**
- Real-time streaming inference
- Instant voice cloning (no retraining needed)
- 24kHz audio quality
- Fully offline/on-device operation
- Docker containerization support

### 2. Installation & Setup

**SDK Installation:**

Windows (avoid llama-cpp build errors):
```bash
pip install vieneu --extra-index-url https://pnnbao97.github.io/llama-cpp-python-v0.3.16/cpu/
```

Linux/macOS:
```bash
pip install vieneu
```

**From Source (with uv):**
```bash
git clone https://github.com/pnnbao97/VieNeu-TTS.git
cd VieNeu-TTS
uv sync
uv run vieneu-web  # Opens web UI at http://127.0.0.1:7860
```

**Docker Deployment:**
```bash
docker run --gpus all -p 23333:23333 pnnbao/vieneu-tts:serve --tunnel
```

### 3. Code Examples

**Basic TTS Implementation:**
```python
from vieneu import Vieneu

# Context manager approach (recommended)
with Vieneu(mode="standard") as tts:
    audio = tts.infer(
        text="Chào mừng bạn đến với công nghệ giọng nói của Vieneu.",
        voice_id="vi_female_standard"  # Or path to ref audio for cloning
    )
    tts.save(audio, "output_welcome.wav")
```

**Voice Cloning:**
```python
from vieneu import Vieneu

with Vieneu(mode="standard") as tts:
    # Clone voice from reference audio (3-5 seconds)
    audio = tts.infer(
        text="Đây là giọng nói được nhân bản.",
        ref_audio="path/to/reference_voice.wav"
    )
    tts.save(audio, "cloned_output.wav")
```

**Streaming Mode (GPU):**
```python
from vieneu import Vieneu

with Vieneu(mode="fast") as tts:  # Requires GPU
    for chunk in tts.stream_infer(text="Đoạn văn bản dài..."):
        # Process audio chunk immediately
        play_audio_chunk(chunk)
```

### 4. Local TTS Alternatives to ElevenLabs (2024-2025)

#### Top Contenders:

**1. Fish-Speech** (Emerging Leader)
- **Cloning**: 1-3 seconds reference audio
- **Quality**: Very high, multilingual
- **Latency**: Extremely low
- **Vietnamese**: Supported
- **GitHub**: [fishaudio/fish-speech](https://github.com/fishaudio/fish-speech)

**2. GPT-SoVITS** (Vietnamese Champion)
- **Cloning**: 5 seconds - 1 minute (requires fine-tuning 15-30 min)
- **Quality**: Exceptional for Vietnamese/Chinese
- **Latency**: Medium (fine-tuning overhead)
- **Vietnamese**: Excellent
- **GitHub**: [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)

**3. XTTS v2 (Coqui)** (Stable Standard)
- **Cloning**: ~1 minute reference
- **Quality**: High, very stable
- **Latency**: Medium
- **Vietnamese**: Supported (multilingual)
- **Note**: Coqui AI closed, but model remains powerful

**4. Piper** (Performance King)
- **Cloning**: Pre-trained voices only
- **Quality**: Medium (lower than above)
- **Latency**: Lowest (CPU optimized)
- **Vietnamese**: Available models
- **Use case**: Raspberry Pi, low-resource

**5. Vieneu-TTS** (Vietnamese Specialist)
- **Cloning**: 3-5 seconds
- **Quality**: High for Vietnamese
- **Latency**: Very low (CPU friendly)
- **Vietnamese**: Native optimization

### 5. Migration Strategy from ElevenLabs

#### API Compatibility Layer

Build FastAPI wrapper to mimic ElevenLabs API:

```python
# Before: ElevenLabs
# from elevenlabs import generate
# audio = generate(text="Xin chào", voice="Bella")

# After: Local Migration with GPT-SoVITS
import requests

def generate_local_tts(text: str, voice_id: str):
    url = "http://localhost:9880"
    payload = {
        "text": text,
        "refer_wav_path": f"voices/{voice_id}.wav",
        "prompt_text": "Reference text matching voice",
        "language": "vi"
    }
    response = requests.post(url, json=payload)
    return response.content  # Returns audio bytes like ElevenLabs
```

#### Voice Cloning Comparison

| Feature | ElevenLabs | GPT-SoVITS | Fish-Speech | Vieneu |
|---------|------------|------------|-------------|---------|
| Reference audio | 1 min+ | 5s-1min | 1-3s | 3-5s |
| Quality | Very high | Very high (Vi/Zh) | High | High (Vi) |
| Clone speed | Instant | 15-30min fine-tune | Instant | Instant |
| Method | Cloud API | Local fine-tuning | In-context learning | In-context |

### 6. Performance Optimization Techniques

**1. Quantization (Model Compression)**
- Use 4-bit/8-bit quantized models
- Reduces VRAM usage 50-75%
- Minimal quality loss
- Example: GGUF Q4 quantization in Vieneu

**2. TensorRT/ONNX Acceleration**
- Convert models to TensorRT (NVIDIA)
- 2-4x inference speedup
- Requires NVIDIA GPU with CUDA 12.8+

**3. Streaming Implementation**
- Use WebSocket for real-time delivery
- Start audio playback as first bytes arrive
- Reduces perceived latency significantly

**4. Caching Strategy**
- Cache common phrases with Redis
- Reduces GPU load for repeated text
- Example: "Welcome", "Thank you", etc.

### 7. Hardware Requirements

**Minimum (CPU-only):**
- CPU: 4+ cores (Intel i5/AMD Ryzen 5)
- RAM: 8GB
- Storage: 10GB for models
- Models: Vieneu 0.3B-Q4, Piper

**Recommended (GPU):**
- GPU: NVIDIA RTX 3060 (12GB VRAM) or higher
- CPU: 8+ cores
- RAM: 16GB
- Storage: 50GB SSD
- Models: GPT-SoVITS, Fish-Speech, XTTS v2

**Optimal (Production):**
- GPU: NVIDIA RTX 4090 (24GB VRAM) or A100
- CPU: 16+ cores
- RAM: 32GB
- Storage: 100GB NVMe SSD
- Multiple GPU workers with load balancing

### 8. Cost Comparison

| Item | ElevenLabs (Scale) | Local Self-Hosted |
|------|-------------------|------------------|
| **Price/1000 chars** | ~$0.30 | $0 (after hardware amortization) |
| **Hardware cost** | None | $500-$1500 (RTX 3060-4060) |
| **Electricity** | N/A | $10-$20/month continuous |
| **Break-even point** | N/A | 3-6 months (high usage) |
| **Scalability** | Easy (pay more) | Manual (add GPUs) |
| **Privacy** | Data sent to API | Fully local |

**ROI Calculation:**
- If using 100k chars/month ($30/month with ElevenLabs)
- Hardware: $1000 (RTX 3060)
- Break-even: ~33 months
- High usage (500k chars/month): Break-even in ~7 months

---

## Implementation Recommendations

### Phase 1: Quick Start (Local Testing)

**Choose Vieneu-TTS for Vietnamese-first approach:**

```bash
# Install
pip install vieneu --extra-index-url https://pnnbao97.github.io/llama-cpp-python-v0.3.16/cpu/

# Test basic TTS
python -c "
from vieneu import Vieneu
with Vieneu() as tts:
    audio = tts.infer('Xin chào')
    tts.save(audio, 'test.wav')
"
```

**Or try Fish-Speech for multilingual:**

```bash
git clone https://github.com/fishaudio/fish-speech
cd fish-speech
pip install -r requirements.txt
python inference.py --text "Hello world" --reference audio.wav
```

### Phase 2: API Wrapper Development

Build FastAPI server wrapping chosen TTS:

```python
# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from vieneu import Vieneu
import base64

app = FastAPI()
tts = Vieneu(mode="standard")

class TTSRequest(BaseModel):
    text: str
    voice_id: str = "default"

@app.post("/v1/tts")
async def generate_speech(request: TTSRequest):
    try:
        audio = tts.infer(text=request.text)
        audio_b64 = base64.b64encode(audio).decode()
        return {"audio": audio_b64, "format": "wav"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Run: uvicorn server:app --host 0.0.0.0 --port 8000
```

### Phase 3: Production Deployment

**Docker Compose Setup:**

```yaml
# docker-compose.yml
version: '3.8'
services:
  tts-worker-1:
    image: pnnbao/vieneu-tts:serve
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports:
      - "8001:23333"

  tts-worker-2:
    image: pnnbao/vieneu-tts:serve
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports:
      - "8002:23333"

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - tts-worker-1
      - tts-worker-2

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
```

**Load Balancing (nginx.conf):**

```nginx
http {
    upstream tts_backend {
        least_conn;
        server tts-worker-1:23333;
        server tts-worker-2:23333;
    }

    server {
        listen 80;

        location /v1/tts {
            proxy_pass http://tts_backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_buffering off;
        }
    }
}
```

### Phase 4: Monitoring & Optimization

**Prometheus Metrics:**

```python
from prometheus_client import Counter, Histogram, Gauge
import time

tts_requests = Counter('tts_requests_total', 'Total TTS requests')
tts_duration = Histogram('tts_generation_seconds', 'Time to generate TTS')
gpu_temp = Gauge('gpu_temperature_celsius', 'GPU temperature')

@app.post("/v1/tts")
async def generate_speech(request: TTSRequest):
    tts_requests.inc()
    start = time.time()

    audio = tts.infer(text=request.text)

    tts_duration.observe(time.time() - start)
    return {"audio": base64.b64encode(audio).decode()}
```

---

## Common Pitfalls & Solutions

### 1. CUDA/GPU Issues

**Problem**: Model fails to load on GPU
**Solution**:
```bash
# Check CUDA version
nvidia-smi
# Ensure CUDA 12.8+ for latest models
# Reinstall PyTorch with correct CUDA version
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

### 2. Out of Memory (OOM)

**Problem**: GPU OOM errors
**Solution**:
- Use quantized models (Q4/Q8)
- Reduce batch size
- Enable gradient checkpointing
- Split large texts into chunks

### 3. Poor Voice Quality

**Problem**: Generated audio sounds robotic
**Solution**:
- Use longer reference audio (10-30s better than 3s)
- Ensure reference audio is high quality (24kHz+, no noise)
- Try different models (GPT-SoVITS often best for Vi)
- Adjust inference parameters (temperature, top_p)

### 4. High Latency

**Problem**: Slow generation speed
**Solution**:
- Enable streaming mode
- Use faster model variant (0.3B vs 0.5B)
- Quantize to INT8/FP16
- Deploy on faster GPU
- Implement caching for common phrases

---

## Migration Roadmap

### Week 1-2: Evaluation Phase
1. Install Vieneu-TTS on local machine
2. Test voice cloning with Vietnamese samples
3. Compare quality vs ElevenLabs
4. Benchmark inference speed (RTF - Real Time Factor)
5. Select final model (Vieneu/Fish-Speech/GPT-SoVITS)

### Week 3-4: Development Phase
1. Build FastAPI wrapper matching ElevenLabs API structure
2. Implement voice management (upload/store reference audios)
3. Add authentication/rate limiting
4. Create Docker image
5. Write migration script for existing code

### Week 5-6: Testing Phase
1. A/B test local vs ElevenLabs (blind listening tests)
2. Load testing with concurrent requests
3. Monitor GPU utilization and temperature
4. Optimize caching strategy
5. Stress test error handling

### Week 7-8: Deployment Phase
1. Setup production infrastructure (GPU server/cloud)
2. Deploy with load balancing
3. Implement monitoring (Prometheus + Grafana)
4. Gradual traffic migration (10% → 50% → 100%)
5. Setup fallback to ElevenLabs for critical failures

---

## Resources & References

### Official Documentation
- [Vieneu SDK Overview](https://docs.vieneu.io/docs/sdk/overview/)
- [Vieneu-TTS GitHub](https://github.com/pnnbao97/VieNeu-TTS)
- [Vieneu-TTS PyPI Package](https://github.com/pnnbao97/VieNeu-TTS/blob/main/README_PYPI.md)
- [Vieneu-TTS Deployment Guide](https://github.com/pnnbao97/VieNeu-TTS/blob/main/docs/Deploy.md)

### Alternative Solutions
- [Fish-Speech GitHub](https://github.com/fishaudio/fish-speech)
- [GPT-SoVITS GitHub](https://github.com/RVC-Boss/GPT-SoVITS)
- [Coqui XTTS Documentation](https://docs.coqui.ai/)
- [Piper TTS Models](https://github.com/rhasspy/piper)

### Community Resources
- [Vieneu HuggingFace Models](https://huggingface.co/pnnbao-ump/VieNeu-TTS)
- [Vietnamese TTS Installation Guide](https://sonusahani.com/blogs/vieneu-tts)

---

## Appendices

### A. Glossary

- **RTF (Real Time Factor)**: Ratio of generation time to audio duration. RTF < 1.0 means real-time capable
- **GGUF**: Quantized model format optimized for CPU inference
- **Voice Cloning**: Creating synthetic voice matching reference audio
- **Zero-shot**: Cloning without model retraining
- **Quantization**: Reducing model precision (FP32 → INT8) for speed
- **Inference**: Process of generating audio from text using trained model

### B. Hardware Recommendations by Use Case

**Personal/Development:**
- CPU: Intel i5-12400 or AMD Ryzen 5 5600
- RAM: 16GB DDR4
- GPU: Optional (use CPU mode)
- Model: Vieneu 0.3B-Q4

**Small Business (< 10k requests/day):**
- CPU: Intel i7-12700 or AMD Ryzen 7 5800X
- RAM: 32GB DDR4
- GPU: NVIDIA RTX 3060 (12GB)
- Model: Vieneu 0.5B or Fish-Speech

**Enterprise (> 100k requests/day):**
- CPU: AMD EPYC or Intel Xeon (16+ cores)
- RAM: 64GB DDR5
- GPU: 2x NVIDIA RTX 4090 or A100
- Model: GPT-SoVITS or Fish-Speech
- Infrastructure: Kubernetes cluster with auto-scaling

### C. Unresolved Questions

1. **Vieneu SDK Pricing**: Official commercial pricing for Vieneu Cloud API not documented. Contact vendor required.

2. **Production SLA**: No published uptime guarantees or performance SLAs for self-hosted deployment.

3. **Model Updates**: Unclear update frequency and backward compatibility policy for Vieneu models.

4. **Edge Deployment**: Viability of deploying on ARM-based edge devices (Raspberry Pi 5, Jetson Nano) needs testing.

5. **Batch Processing**: Optimal batch sizes and GPU memory management for concurrent requests undocumented.

---

**Research Completion Note**: This report provides comprehensive guidance for implementing Vieneu TTS locally as ElevenLabs replacement. Focus on Vietnamese TTS use case with Vieneu-TTS or GPT-SoVITS recommended. For multilingual requirements, Fish-Speech offers best balance of quality and speed. Production deployment requires GPU infrastructure and careful monitoring implementation.

**Next Steps**: Install Vieneu locally, run quality comparison tests, then build API wrapper if results satisfactory.
