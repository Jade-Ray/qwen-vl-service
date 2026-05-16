# 更新日志

本文档记录每次版本发布的变更内容。

---

## [0.3.0] - 2026-05-17

### 新增

- **API 鉴权**：`X-API-Key` 请求头鉴权；`SERVICE_API_KEY` 未配置时自动禁用（开发友好）；`/health` 始终公开。
- **API 版本号**：所有业务路由迁移至 `/v1/` 前缀，便于后续平滑升级。
- **Qwen API 超时**：`detect_objects` 调用加入可配置超时（`QWEN_TIMEOUT`，默认 120 s），防止请求永久挂起。
- **指数退避重试**：对限流（429）、连接错误、服务端 5xx 错误自动重试，最多 `QWEN_MAX_RETRIES` 次（默认 2）。
- **QwenVLClient 单例**：通过 FastAPI lifespan + `app.state` 管理单一实例，FastAPI `Depends` 注入，消除每次请求重建 HTTP 连接池的开销。
- **结构化 JSON 日志**：HTTP 中间件记录 `request_id`、`method`、`path`、`status`、`elapsed_ms`，JSON 格式输出，方便日志收集。
- **启动配置校验**：lifespan 启动时检查 `QWEN_API_KEY`，未配置时输出 warning 而非崩溃。
- **图像大小限制**：Base64 长度超限返回 422（`MAX_IMAGE_B64_CHARS`）；图像分辨率超限返回 422（`MAX_IMAGE_PIXELS`）。
- **Dockerfile 安全**：以非 root 用户（`appuser`）运行容器；仅安装运行时依赖。
- **docker-compose 资源限制**：`cpus: 2.0`、`memory: 2G`，防止单服务耗尽宿主机资源。
- **依赖分层**：`requirements.txt` 仅包含运行时依赖；新增 `requirements-dev.txt` 管理测试工具。
- **测试覆盖扩充**：新增 `test_qwen_client.py`（JSON 解析边界测试）、鉴权测试、图像大小限制测试，共 75 个测试。

### 变更

- `/debug/echo-image` → `/v1/debug/echo-image`
- `/detect` → `/v1/detect`
- `smoke_test.py` 路由同步更新，新增 `--service-key` 参数。
- 服务版本号更新为 `0.3.0`。

---

## [0.2.0] - 2026-05-17

### 新增

- **并发保护**：同一时刻只允许一个检测请求，并发时返回 `503 当前服务忙，请稍后再试`。
- **可选 prompt**：`/detect` 接口的 `prompt` 字段改为可选，省略时自动使用默认"检测所有目标"提示词。
- **响应类型区分**：响应新增 `type` 字段：
  - `"detected"`：检测到目标，返回 `objects`（含 `bbox_2d` 和 `label`）及渲染图像；
  - `"no_detection"`：未检测到目标，仅返回类型标识。
- **规范 bbox 字段名**：`DetectionObject` 中边界框字段统一为 `bbox_2d`，与 Qwen-VL 输出格式一致。
- **图像校验**：图像缺失或 Base64 解码失败时返回 `422` 及详细错误信息，而非 500。
- **上游错误透传**：Qwen-VL 调用失败时将错误信息通过 `502` 响应透传给调用方。
- **环境变量管理**：通过 `.env` 文件注入 API Key，新增 `.env.example` 模板，避免密钥硬编码。
- **测试套件**：新增 `tests/` 目录，覆盖图像编解码、数据模型、渲染器和 API 端点的单元测试。
- **容器化部署**：新增 `Dockerfile` 和 `docker-compose.yml`，支持一键部署到公网服务器。
- **文档**：新增 `README.md`（含 API 使用说明和部署指南）和 `CHANGELOG.md`。

### 变更

- `/detect` 响应结构调整：移除顶层 `result_json` 包装，`objects` 直接暴露在响应根节点。
- 服务版本号更新为 `0.2.0`。

---

## [0.1.0] - 初始版本

- FastAPI 服务骨架搭建。
- `/health` 健康检查接口。
- `/debug/echo-image` 图像回显调试接口。
- `/detect` 目标检测接口，调用 Qwen-VL 模型并渲染边界框。
- 支持 PNG / JPEG / WebP 图像格式，自动处理 data URL 前缀。
- 通过 `.env` 文件和环境变量注入 Qwen API 配置。
