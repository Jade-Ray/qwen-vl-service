# Qwen-VL 多模态目标检测服务

基于 **FastAPI** 构建的 HTTP 推理服务，接收 Base64 编码的图像，调用 **Qwen-VL** 大模型完成目标检测，返回带边界框的渲染图像与结构化 JSON。

---

## 目录

- [快速开始](#快速开始)
- [环境变量配置](#环境变量配置)
- [API 接口说明](#api-接口说明)
- [公网部署（Ubuntu）](#公网部署ubuntu)

---

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填写 QWEN_API_KEY

# 3. 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> ⚠️ 必须使用 `--workers 1`。服务通过进程内锁保证同一时刻只处理一个检测请求；多进程模式下锁失效。

### 运行测试

```bash
pytest tests/ -v
```

---

## 环境变量配置

复制 `.env.example` 为 `.env` 并填写真实值（`.env` 已在 `.gitignore` 中，不会提交）。

| 变量名 | 必填 | 说明 | 默认值 |
|---|---|---|---|
| `QWEN_API_KEY` | ✅ | 通义千问 API Key | — |
| `QWEN_BASE_URL` | | API 基础地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_MODEL` | | 模型名称 | `qwen-vl-max` |
| `QWEN_MAX_TOKENS` | | 最大输出 token 数 | `1024` |

---

## API 接口说明

### `GET /health`

健康检查。

**响应示例：**
```json
{"status": "ok"}
```

---

### `POST /detect`

目标检测主接口。

**请求体：**

```json
{
  "image_base64": "<base64字符串或data URL>",
  "prompt": "检测图中的人和车辆"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_base64` | `string` | ✅ | 原始 Base64 或 `data:image/png;base64,...` 格式 |
| `prompt` | `string` | | 检测指令，省略时使用默认"检测所有目标" |

**响应示例（有检测目标）：**

```json
{
  "type": "detected",
  "objects": [
    {"label": "人", "bbox_2d": [120, 45, 280, 390], "score": null},
    {"label": "汽车", "bbox_2d": [400, 200, 750, 450], "score": null}
  ],
  "image_base64": "<渲染了边界框的图像 base64>",
  "image_width": 1280,
  "image_height": 720,
  "mime_type": "image/png"
}
```

**响应示例（无检测目标）：**

```json
{
  "type": "no_detection"
}
```

**错误响应：**

| HTTP 状态码 | 含义 |
|---|---|
| `422` | 请求体缺少 `image_base64`，或图像解码失败 |
| `502` | 调用 Qwen-VL 模型失败，`detail` 字段包含上游错误信息 |
| `503` | 当前有检测请求正在处理，请稍后重试 |

---

### `POST /debug/echo-image`

调试接口，原样解码并重新编码返回图像，用于验证图像传输是否正常。

**请求体：**
```json
{"image_base64": "<base64字符串>"}
```

---

## 公网部署（Ubuntu）

### 方案：Docker + Nginx 反向代理

**前提条件：** Ubuntu 20.04+，已安装 Docker 和 Docker Compose。

```bash
# 安装 Docker（未安装时执行）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 1. 上传项目到服务器
scp -r . user@your-server:/opt/qwen-detect

# 2. 进入目录，配置 API Key
cd /opt/qwen-detect
cp .env.example .env
nano .env   # 填写 QWEN_API_KEY

# 3. 构建并启动
docker compose up -d --build

# 4. 查看日志
docker compose logs -f
```

**验证服务：**
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 可选：Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 180s;
    }
}
```

```bash
# 安装并配置 Nginx
sudo apt install nginx -y
sudo nano /etc/nginx/sites-available/qwen-detect
# 粘贴上述配置，将 your-domain.com 替换为真实域名

sudo ln -s /etc/nginx/sites-available/qwen-detect /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS 可使用 [Certbot](https://certbot.eff.org/) 一键签发：
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

### 更新部署

```bash
cd /opt/qwen-detect
git pull
docker compose up -d --build
```
