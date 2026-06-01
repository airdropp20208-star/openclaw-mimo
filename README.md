# 📋 TỔNG QUAN DỰ ÁN: AI Agent TỰ ĐỘNG EDIT VIDEO + TẠO GIỌNG TIẾNG VIỆT

## 1. Mục tiêu của dự án

Xây dựng một AI Agent tự động, có khả năng:

- Nhận yêu cầu bằng ngôn ngữ tự nhiên (qua terminal hoặc web/Telegram)
- Tự động viết code (Python + FFmpeg/MoviePy) để edit video (cắt ghép, vietsub, che phụ đề)
- Tạo giọng đọc tiếng Việt từ văn bản bằng OmniVoice
- Chạy 24/7 trên VPS chỉ có terminal (không màn hình desktop)

**Yêu cầu đặc biệt:**

- Dùng **MiMo API** (của Xiaomi) làm "bộ não" (LLM suy luận, ra lệnh)
- Dùng **OmniVoice** (của k2-fsa) làm "cổ họng" (TTS tiếng Việt)
- Tất cả cài đặt và chạy qua terminal, không cần GUI

---

## 2. Kiến trúc tổng thể

```
Người dùng (lệnh text)
        │
        ▼
┌─────────────────────────────────────────────┐
│  OpenClaw Gateway (framework chính)         │
│  - Nhận lệnh tự nhiên                        │
│  - Quản lý tools                             │
│  - Gọi MiMo API để suy luận                  │
└─────────────────────────────────────────────┘
        │
        ├──────────────┬──────────────┐
        ▼              ▼              ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ Tool:      │  │ Tool:      │  │ Tool:      │
│ Edit video │  │ OmniVoice  │  │ File I/O   │
│ (Python)   │  │ TTS API    │  │ (upload/   │
└────────────┘  └────────────┘  │ download)  │
        │              │         └────────────┘
        ▼              ▼
┌────────────┐  ┌────────────┐
│ FFmpeg /   │  │ OmniVoice  │
│ MoviePy    │  │ (API       │
│ (render)   │  │  server)   │
└────────────┘  └────────────┘
```

---

## 3. Công nghệ sử dụng

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Framework chính | OpenClaw (TypeScript) | Hỗ trợ MiMo sẵn, dễ thêm tool |
| Bộ não (LLM) | MiMo API (Xiaomi) | Model: mimo-v2-pro hoặc mimo-v2-omni |
| Giọng nói (TTS) | OmniVoice (k2-fsa) | Hỗ trợ tiếng Việt, clone giọng, 600+ ngôn ngữ |
| Edit video | FFmpeg + MoviePy (Python) | MiMo tự viết script theo yêu cầu |
| Môi trường chạy | VPS Linux (Ubuntu 22.04) | Chỉ terminal, khuyến nghị có GPU (NVIDIA) |
| CI/CD / Test | GitHub Actions | Test script trước khi deploy lên VPS |

---

## 4. Luồng hoạt động chi tiết

### Bước 1: Người dùng ra lệnh

Ví dụ: *"Hãy lấy file video1.mp4, cắt 10 giây đầu, thêm phụ đề tiếng Việt, và đọc đoạn text này thành giọng nữ"*

### Bước 2: OpenClaw nhận lệnh, gửi cho MiMo

- MiMo phân tích ý đồ
- MiMo quyết định cần gọi tool nào (EditVideo / OmniVoice)

### Bước 3: MiMo viết code edit video

```python
# MiMo tự sinh ra code tương tự:
from moviepy import VideoFileClip

clip = VideoFileClip("video1.mp4").subclipped(0, 10)
# ... thêm phụ đề
clip.write_videofile("output.mp4")
```

### Bước 4: Gọi OmniVoice để tạo giọng

```python
# Nếu cần, gọi OmniVoice API server
POST http://localhost:8080/synthesize
{
  "text": "Xin chào các bạn",
  "instruct": "female, medium pitch"
}
# Trả về file .wav
```

### Bước 5: Trả kết quả

- Gửi link tải video đã edit
- (Tùy chọn) Gửi file âm thanh

---

## 5. Các thành phần cần code

### 5.1. Cài đặt OpenClaw + tích hợp MiMo

**Việc cần làm:**

- Cài OpenClaw trên VPS (Ubuntu)
- Cấu hình để dùng MiMo API key
- Bật Gateway chạy nền 24/7

```bash
# Cài OpenClaw
curl -fsSL https://openclaw.ai/install.sh | bash

# Thêm MiMo API key
openclaw models auth add --key $MIMO_API_KEY

# Chạy gateway
openclaw gateway install
openclaw gateway start
```

### 5.2. Tool edit video (MiMo tự viết script)

**Yêu cầu tool này:**

- Nhận đầu vào: đường dẫn video + mô tả chỉnh sửa (text)
- MiMo sẽ tự sinh code Python xử lý video (dùng FFmpeg hoặc MoviePy)
- Code được chạy và xuất ra video mới

**Cách implement:**
Tạo một tool trong OpenClaw có tên `edit_video`:

```python
def edit_video(video_path: str, instruction: str) -> str:
    """
    Args:
        video_path: Đường dẫn đến file video
        instruction: Yêu cầu chỉnh sửa bằng tiếng Việt
                     (ví dụ: "cắt 10 giây đầu, thêm chữ màu đỏ")
    Returns:
        Đường dẫn đến video đã chỉnh sửa
    """
    # Gọi MiMo API để sinh code xử lý
    code = call_mimo(f"Viết Python code dùng moviepy để {instruction}")

    # Chạy code trong sandbox
    result = exec(code)
    return result.output_path
```

### 5.3. OmniVoice API server (dạng REST)

**Mục đích:** Chạy OmniVoice như một service riêng để OpenClaw gọi qua HTTP.

**File cần viết:** `omnivoice_server.py`

```python
from fastapi import FastAPI
from omnivoice import OmniVoice
import soundfile as sf

app = FastAPI()
model = OmniVoice.from_pretrained("k2-fsa/OmniVoice")

@app.post("/synthesize")
async def synthesize(data: dict):
    text = data["text"]
    instruct = data.get("instruct", "")  # ví dụ: "female, vietnamese accent"

    audio = model.generate(text=text, instruct=instruct)

    # Lưu tạm file .wav
    sf.write("output.wav", audio[0], 24000)
    return {"audio_url": "http://localhost/output.wav"}
```

**Chạy server:**

```bash
python omnivoice_server.py --port 8080
```

### 5.4. Tool gọi OmniVoice trong OpenClaw

```python
def text_to_speech(text: str, voice_style: str = "") -> str:
    """
    Args:
        text: Văn bản tiếng Việt cần đọc
        voice_style: "male", "female", "low pitch", "high pitch",...
    Returns:
        Đường dẫn đến file .wav
    """
    import requests
    response = requests.post(
        "http://localhost:8080/synthesize",
        json={"text": text, "instruct": voice_style}
    )
    return response.json()["audio_url"]
```

### 5.5. GitHub Actions workflow (test & deploy)

**File:** `.github/workflows/deploy.yml`

```yaml
name: Deploy OpenClaw + OmniVoice to VPS

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Test cài OpenClaw
        run: curl -fsSL https://openclaw.ai/install.sh | bash
      - name: Test OmniVoice
        run: |
          pip install omnivoice
          python -c "from omnivoice import OmniVoice; print('OK')"

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: SSH to VPS and install
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_IP }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            # Cài OpenClaw
            curl -fsSL https://openclaw.ai/install.sh | bash
            openclaw models auth add --key ${{ secrets.MIMO_API_KEY }}

            # Cài OmniVoice server
            git clone https://github.com/k2-fsa/OmniVoice.git
            cd OmniVoice
            pip install -e .
            nohup python omnivoice_server.py &

            # Chạy OpenClaw
            openclaw gateway install
            openclaw gateway start
```

---

## 6. Cấu hình VPS tối thiểu

| Thành phần | Yêu cầu |
|---|---|
| Hệ điều hành | Ubuntu 22.04 LTS (Linux) |
| CPU | 2 vCPU trở lên |
| RAM | 4 GB (8 GB khuyến nghị nếu dùng OmniVoice) |
| GPU | Không bắt buộc, nhưng có NVIDIA GPU sẽ giúp OmniVoice nhanh hơn |
| Storage | 20 GB SSD (có thể lưu video tạm) |
| Mạng | Cần port mở: 18789 (OpenClaw web UI), 8080 (OmniVoice API) |

---

## 7. Các bước triển khai (cho lập trình viên)

1. Cài đặt OpenClaw trên VPS (dùng script 1 dòng)
2. Tích hợp MiMo API key vào OpenClaw
3. Code OmniVoice API server (FastAPI + omnivoice)
4. Tạo tool OpenClaw để gọi OmniVoice
5. Tạo tool edit video (dùng MiMo tự sinh code MoviePy)
6. Viết GitHub Actions workflow tự động test và deploy
7. Chạy thử với lệnh: *"edit video1.mp4: cắt 5 giây đầu, thêm chữ 'Xin chào', đọc bằng giọng nữ"*

---

## 8. Tham khảo tài liệu

- OpenClaw + MiMo: https://docs.openclaw.ai/model-providers/openrouter
- OmniVoice GitHub: https://github.com/k2-fsa/OmniVoice
- MiMo API docs: (bạn đã có key)
- MoviePy docs: https://zulko.github.io/moviepy/

---

## 9. Notes cho dev

- Ưu tiên dùng OpenClaw vì nó hỗ trợ MiMo sẵn, không phải code nhiều từ đầu
- OmniVoice chạy riêng thành API server để OpenClaw gọi qua HTTP, dễ debug và tái sử dụng
- Test trên GitHub Actions trước để tránh lỗi cài đặt trên VPS
- Dùng Ubuntu 22.04, không dùng Windows vì OmniVoice chạy ổn định hơn trên Linux
