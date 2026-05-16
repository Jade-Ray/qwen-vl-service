# Qwen-VL 目标检测服务 · API 使用指南

本文档面向 **API 调用方**，帮助你快速接入基于 Qwen-VL 大模型的目标检测服务。

---

## 服务信息

| 项目 | 值 |
|------|----|
| 公网地址 | `http://118.31.37.161:8000` |
| 协议 | HTTP/1.1，JSON 请求与响应 |
| 鉴权 | 当前未启用（`X-API-Key` 头，暂时不需要填写） |
| 并发限制 | **同一时刻只处理 1 个检测请求**，其余请求返回 503 |
| 在线文档 | `http://118.31.37.161:8000/docs`（Swagger UI） |

---

## 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/v1/detect` | **目标检测主接口** |
| `POST` | `/v1/debug/echo-image` | 调试：图像编解码验证 |

---

## `POST /v1/detect` — 目标检测

### 请求

**Content-Type：** `application/json`

```json
{
  "image_base64": "<图像的 Base64 字符串>",
  "prompt": "检测图中的车辆和行人"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_base64` | `string` | ✅ | 图像的 Base64 编码，支持裸 Base64 或 `data:image/jpeg;base64,...` 格式 |
| `prompt` | `string` | ❌ | 检测指令，省略时使用内置默认提示词（检测图中所有可见目标） |

**图像限制：**
- Base64 字符串长度 ≤ 10 MB（`MAX_IMAGE_B64_CHARS`）
- 图像分辨率 ≤ 400 万像素（`MAX_IMAGE_PIXELS`），即 2000×2000 以内
- 支持格式：JPEG、PNG、WEBP 等常见格式

---

### 响应：检测到目标

```json
{
  "type": "detected",
  "objects": [
    {
      "label": "汽车",
      "bbox_2d": [704, 485, 863, 539],
      "score": null
    },
    {
      "label": "汽车",
      "bbox_2d": [781, 424, 941, 539],
      "score": null
    }
  ],
  "image_base64": "<渲染了边界框的图像 Base64>",
  "image_width": 960,
  "image_height": 540,
  "mime_type": "image/jpeg"
}
```

| 字段 | 说明 |
|------|------|
| `type` | 固定为 `"detected"` |
| `objects` | 检测到的目标列表 |
| `objects[].label` | 目标类别，中文或英文，取决于 prompt 语言 |
| `objects[].bbox_2d` | 边界框像素坐标 `[x1, y1, x2, y2]`，左上角到右下角 |
| `objects[].score` | 置信度（部分模型不返回，为 `null`） |
| `image_base64` | 在原图上绘制了彩色边界框和标签的渲染图，Base64 编码 |
| `image_width` / `image_height` | 图像像素尺寸 |
| `mime_type` | 渲染图的 MIME 类型，通常为 `image/jpeg` |

---

### 响应：未检测到目标

```json
{
  "type": "no_detection"
}
```

---

### 错误响应

| HTTP 状态码 | 场景 | `detail` 示例 |
|-------------|------|---------------|
| `422` | 缺少 `image_base64`，或图像解码失败，或图像超过尺寸限制 | `"image_base64: Field required"` |
| `401` | 鉴权失败（启用鉴权时） | `"Invalid or missing API key"` |
| `502` | Qwen-VL 模型 API 调用失败 | `"Qwen API error 429: Rate limit exceeded"` |
| `503` | 服务正忙（上一个请求尚未完成） | `"Service busy, please retry later"` |

---

## 调用示例

### curl

**最简调用（使用默认检测 prompt）：**

```bash
# 将图像编码为 Base64
IMAGE_B64=$(base64 -w 0 your_image.jpg)

curl -X POST http://118.31.37.161:8000/v1/detect \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$IMAGE_B64\"}" \
  -o result.json
```

**指定自定义 prompt：**

```bash
curl -X POST http://118.31.37.161:8000/v1/detect \
  -H "Content-Type: application/json" \
  -d "{
    \"image_base64\": \"$IMAGE_B64\",
    \"prompt\": \"只检测图中的行人，忽略车辆\"
  }" \
  -o result.json
```

**提取渲染图并保存（需要 jq）：**

```bash
cat result.json | jq -r '.image_base64' | base64 -d > rendered.jpg
```

---

### Python

```python
import base64
import json
import httpx

SERVICE_URL = "http://118.31.37.161:8000"

def detect_objects(image_path: str, prompt: str | None = None) -> dict:
    """调用检测服务，返回响应 JSON。"""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    payload = {"image_base64": image_b64}
    if prompt:
        payload["prompt"] = prompt

    response = httpx.post(
        f"{SERVICE_URL}/v1/detect",
        json=payload,
        timeout=120,  # 大模型推理耗时较长，建议 60~180s
    )
    response.raise_for_status()
    return response.json()


def save_rendered_image(result: dict, output_path: str) -> None:
    """将响应中的渲染图保存到本地。"""
    if result.get("type") != "detected":
        print("未检测到目标，无渲染图。")
        return
    img_bytes = base64.b64decode(result["image_base64"])
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    print(f"渲染图已保存至 {output_path}")


# 使用示例
if __name__ == "__main__":
    result = detect_objects("vehicle.jpg", prompt="检测图中所有车辆")

    if result["type"] == "detected":
        print(f"检测到 {len(result['objects'])} 个目标：")
        for obj in result["objects"]:
            x1, y1, x2, y2 = obj["bbox_2d"]
            print(f"  - {obj['label']}  bbox=({x1},{y1})-({x2},{y2})")
        save_rendered_image(result, "rendered.jpg")
    else:
        print("未检测到目标。")
```

**错误处理示例：**

```python
import httpx

try:
    result = detect_objects("image.jpg")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 503:
        print("服务繁忙，请稍后重试")
    elif e.response.status_code == 502:
        print(f"模型调用失败：{e.response.json()['detail']}")
    elif e.response.status_code == 422:
        print(f"请求参数有误：{e.response.json()['detail']}")
    else:
        raise
except httpx.TimeoutException:
    print("请求超时，请增大 timeout 或检查网络")
```

---

### JavaScript / Node.js

```javascript
const fs = require("fs");

const SERVICE_URL = "http://118.31.37.161:8000";

async function detectObjects(imagePath, prompt = null) {
  const imageBuffer = fs.readFileSync(imagePath);
  const imageB64 = imageBuffer.toString("base64");

  const payload = { image_base64: imageB64 };
  if (prompt) payload.prompt = prompt;

  const response = await fetch(`${SERVICE_URL}/v1/detect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(120_000),
  });

  if (!response.ok) {
    const err = await response.json();
    throw new Error(`HTTP ${response.status}: ${JSON.stringify(err.detail)}`);
  }

  return response.json();
}

// 使用示例
detectObjects("vehicle.jpg", "检测图中所有车辆").then((result) => {
  if (result.type === "detected") {
    console.log(`检测到 ${result.objects.length} 个目标`);
    result.objects.forEach(({ label, bbox_2d }) => {
      console.log(`  ${label}: [${bbox_2d}]`);
    });

    // 保存渲染图
    const imgBuffer = Buffer.from(result.image_base64, "base64");
    fs.writeFileSync("rendered.jpg", imgBuffer);
  } else {
    console.log("未检测到目标");
  }
});
```

---

## 常见问题

**Q: 返回 503，但我明明只发了一个请求？**  
A: 服务同一时刻只允许一个检测请求。如果上一次请求还未返回（大模型推理中），新请求会立即得到 503。建议客户端等待上一次响应后再发下一次，或加入重试逻辑（等待 3~5 秒后重试）。

**Q: 图像要压缩到多小？**  
A: 建议发送分辨率不超过 1920×1080、文件大小不超过 2 MB 的图像。过大的图像会被服务拒绝（422），同时更大的图像也不会显著提升检测效果。

**Q: bbox_2d 坐标系是什么？**  
A: `[x1, y1, x2, y2]` 均为**像素坐标**，原点在图像左上角，x 向右，y 向下。`(x1, y1)` 是边界框左上角，`(x2, y2)` 是右下角。

**Q: 如何用 Python 在本地把 bbox 画到图上？**  
```python
from PIL import Image, ImageDraw

img = Image.open("original.jpg")
draw = ImageDraw.Draw(img)
for obj in result["objects"]:
    draw.rectangle(obj["bbox_2d"], outline="red", width=2)
    draw.text((obj["bbox_2d"][0], obj["bbox_2d"][1] - 15), obj["label"], fill="red")
img.save("local_rendered.jpg")
```
> 注意：响应中的 `image_base64` 已经是渲染好的图，无需自行绘制。

**Q: prompt 应该怎么写？**  
A: prompt 支持自然语言描述，例如：
- `"检测图中所有的人和车辆"` — 多类别检测
- `"只检测行人，忽略车辆和背景"` — 类别过滤
- `"找出图中正在行驶的汽车"` — 带状态描述
- `"Detect all vehicles in the image"` — 英文也支持

---

## 健康检查 & 监控

```bash
# 快速确认服务是否在线
curl http://118.31.37.161:8000/health
# 返回 {"status":"ok"} 表示正常
```

建议接入方在业务层加入健康检查探针，间隔 30 秒轮询一次 `/health`，服务异常时触发告警。
