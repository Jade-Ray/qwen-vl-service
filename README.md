# Qwen-VL 多模态目标检测服务

基于 **FastAPI** 构建的 HTTP 推理服务，接收 Base64 编码的图像，调用 **Qwen-VL** 大模型完成目标检测，返回带边界框的渲染图像与结构化 JSON。

> 📖 **面向 API 调用方？** 请直接查看 [docs/API_GUIDE.md](docs/API_GUIDE.md)，包含 curl / Python / JavaScript 完整调用示例。

---

## 目录

- [快速开始](#快速开始)
- [环境变量配置](#环境变量配置)
- [API 接口说明](#api-接口说明)
- [公网部署（Ubuntu）](#公网部署ubuntu--miniconda--systemd)

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
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## 环境变量配置

复制 `.env.example` 为 `.env` 并填写真实值（`.env` 已在 `.gitignore` 中，不会提交）。

| 变量名 | 必填 | 说明 | 默认值 |
|--------|------|------|--------|
| `QWEN_API_KEY` | ✅ | 通义千问 DashScope API Key | — |
| `QWEN_BASE_URL` | | API 基础地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_MODEL` | | 模型名称 | `qwen-vl-max` |
| `QWEN_TIMEOUT` | | 单次 API 调用超时秒数，0 = 不限 | `120` |
| `QWEN_MAX_RETRIES` | | 失败自动重试次数（指数退避） | `2` |
| `SERVICE_API_KEY` | | 服务鉴权密钥，空值表示禁用鉴权 | — |
| `SERVICE_PORT` | | HTTP 监听端口 | `8000` |
| `MAX_IMAGE_B64_CHARS` | | 图像 Base64 最大长度（字节） | `20971520` |
| `MAX_IMAGE_PIXELS` | | 图像最大分辨率（像素总数） | `4000000` |

---

## API 接口说明

所有业务接口均带 `/v1/` 版本前缀。

### `GET /health`

健康检查，无需鉴权。

```json
{"status": "ok"}
```

---

### `POST /v1/detect`

目标检测主接口。

**请求体：**

```json
{
  "image_base64": "<base64字符串或data URL>",
  "prompt": "检测图中的人和车辆"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_base64` | `string` | ✅ | 裸 Base64 或 `data:image/jpeg;base64,...` 格式均可 |
| `prompt` | `string` | ❌ | 检测指令，省略时使用内置默认提示词 |

**响应（有目标）：**

```json
{
  "type": "detected",
  "objects": [
    {"label": "汽车", "bbox_2d": [704, 485, 863, 539], "score": null}
  ],
  "image_base64": "<渲染了边界框的图像 Base64>",
  "image_width": 960,
  "image_height": 540,
  "mime_type": "image/jpeg"
}
```

**响应（无目标）：**

```json
{"type": "no_detection"}
```

**错误码：**

| 状态码 | 含义 |
|--------|------|
| `401` | 鉴权失败（`SERVICE_API_KEY` 已配置但请求未携带或密钥错误） |
| `422` | 缺少 `image_base64`，图像解码失败，或超过尺寸限制 |
| `502` | Qwen-VL API 调用失败，`detail` 包含上游错误信息 |
| `503` | 服务正忙，上一个请求尚未完成 |

---

### `POST /v1/debug/echo-image`

调试接口：验证图像 Base64 传输是否正常，原样解码并重新编码返回。

---

## 公网部署（Ubuntu + Miniconda + systemd）

适用于内存有限（< 2 GB）的轻量云服务器，无需 Docker。  
部署脚本 `scripts/deploy.sh` 会自动完成：Miniconda 安装 → conda 环境创建 → 依赖安装 → systemd 服务配置与启动。

### 首次部署

```bash
# 在服务器上执行（需要 root 或 sudo 权限）
bash <(curl -fsSL https://raw.githubusercontent.com/Jade-Ray/qwen-vl-service/main/scripts/deploy.sh) \
  --tag v0.4.0

# 或者 SSH 到服务器后手动操作：
# ssh root@your-server-ip
# bash <(curl -fsSL ...) --tag v0.4.0
```

脚本首次运行时，若 `/opt/qwen-vl-service/.env` 不存在，会自动从 `.env.example` 创建模板并提示填写：

```bash
# 填写真实的 API Key（.env 不会进入 Git 仓库）
nano /opt/qwen-vl-service/.env
systemctl restart qwen-vl
```

`.env` 关键配置项：

```ini
QWEN_API_KEY=your-dashscope-api-key-here   # 必填
QWEN_MODEL=qwen-vl-max                     # 可选，默认 qwen-vl-max
```

完整环境变量说明见 [环境变量配置](#环境变量配置) 章节和 `.env.example`。

### 版本更新

开发端推送新版本后，在服务器上一行命令完成更新：

```bash
# 更新到指定 tag
bash /opt/qwen-vl-service/scripts/deploy.sh --tag v0.5.0

# 或从本地远程触发（无需登录服务器）
ssh root@your-server-ip "bash /opt/qwen-vl-service/scripts/deploy.sh --tag v0.5.0"
```

### 版本回滚

```bash
bash /opt/qwen-vl-service/scripts/deploy.sh --tag v0.4.0
```

### 发布新版本（开发端）

```bash
git tag v0.5.0
git push origin v0.5.0
```

### 常用运维命令

```bash
systemctl status qwen-vl           # 查看服务状态
journalctl -u qwen-vl -f           # 实时日志
systemctl restart qwen-vl          # 重启服务
curl http://localhost:$(grep SERVICE_PORT /opt/qwen-vl-service/.env | cut -d= -f2)/health  # 健康检查
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
sudo apt install nginx -y
sudo nano /etc/nginx/sites-available/qwen-vl
sudo ln -s /etc/nginx/sites-available/qwen-vl /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS（需要域名）
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```
