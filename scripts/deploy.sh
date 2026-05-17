#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Qwen-VL Detection Service 部署脚本（Ubuntu + Miniconda + systemd）
#
# 用法（在目标服务器上执行）：
#   # 首次部署
#   bash deploy.sh --tag v0.4.0 --repo https://github.com/Jade-Ray/qwen-vl-service
#
#   # 更新到新版本
#   bash deploy.sh --tag v0.5.0
#
#   # 不指定 tag，拉取 main 最新提交（开发/测试用）
#   bash deploy.sh
#
# 也可从本地通过 SSH 一键触发：
#   ssh root@<SERVER_IP> "bash -s -- --tag v0.4.0" < scripts/deploy.sh
#
# 敏感信息：
#   .env 文件不在仓库中，首次部署时脚本会从 .env.example 复制一份，
#   请手动编辑 /opt/qwen-vl-service/.env 填入真实 QWEN_API_KEY。
#   后续更新不会覆盖已有的 .env 文件。
# =============================================================================
set -euo pipefail

# ---------- 配置 ----------
SERVICE_DIR="/opt/qwen-vl-service"
CONDA_DIR="/opt/miniconda3"
CONDA_ENV="qwen-vl-service"
PYTHON_VERSION="3.11"
SERVICE_NAME="qwen-vl"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
MINICONDA_INSTALLER="/tmp/miniconda_installer.sh"
MINICONDA_URL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh"
REPO_URL="https://gitee.com/ambitionqi/qwen-vl-service"
DEPLOY_TAG=""

# ---------- 参数解析 ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)    DEPLOY_TAG="$2";  shift 2 ;;
    --repo)   REPO_URL="$2";    shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------- 1. 检测 / 安装 conda ----------
# 优先使用系统中已有的 conda（任意位置），找不到才安装 Miniconda
if command -v conda &>/dev/null; then
  CONDA="$(command -v conda)"
  # 推断 conda 根目录（bin/conda → 上两级）
  CONDA_DIR="$(dirname "$(dirname "${CONDA}")")"
  log "Found existing conda at ${CONDA} (prefix: ${CONDA_DIR})"
elif [[ -f "${CONDA_DIR}/bin/conda" ]]; then
  CONDA="${CONDA_DIR}/bin/conda"
  log "Found Miniconda at ${CONDA_DIR}"
else
  log "conda not found. Installing Miniconda3 to ${CONDA_DIR} ..."
  curl -fsSL "${MINICONDA_URL}" -o "${MINICONDA_INSTALLER}"
  bash "${MINICONDA_INSTALLER}" -b -p "${CONDA_DIR}"
  rm -f "${MINICONDA_INSTALLER}"
  CONDA="${CONDA_DIR}/bin/conda"
  log "Miniconda installed."
fi
PIP="${CONDA_DIR}/envs/${CONDA_ENV}/bin/pip"
PYTHON="${CONDA_DIR}/envs/${CONDA_ENV}/bin/python"

# ---------- 2. 接受 Anaconda ToS ----------
"${CONDA}" tos accept --override-channels \
  --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main \
  --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r 2>/dev/null || true

# ---------- 3. 拉取代码 ----------
if [[ ! -d "${SERVICE_DIR}/.git" ]]; then
  log "Cloning repository from ${REPO_URL} ..."
  git clone "${REPO_URL}" "${SERVICE_DIR}"
  cd "${SERVICE_DIR}"
else
  log "Repository already cloned. Fetching updates ..."
  cd "${SERVICE_DIR}"
  git fetch --tags origin
fi

if [[ -n "${DEPLOY_TAG}" ]]; then
  log "Checking out tag ${DEPLOY_TAG} ..."
  git checkout "${DEPLOY_TAG}"
else
  log "No --tag specified. Pulling latest main ..."
  git checkout main
  git pull origin main
fi

log "Deployed commit: $(git log -1 --oneline)"

# ---------- 4. 创建 / 更新 conda 环境 ----------
if "${CONDA}" env list | grep -q "^${CONDA_ENV} "; then
  log "Conda env '${CONDA_ENV}' already exists."
else
  log "Creating conda env '${CONDA_ENV}' (Python ${PYTHON_VERSION}) ..."
  "${CONDA}" create -y -n "${CONDA_ENV}" python="${PYTHON_VERSION}" pip \
    -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge \
    --override-channels
fi

# ---------- 5. 安装 / 更新 Python 依赖 ----------
log "Installing Python dependencies ..."
"${PIP}" install --quiet -r "${SERVICE_DIR}/requirements.txt"

# ---------- 6. 检查 .env 文件 ----------
ENV_FILE="${SERVICE_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${SERVICE_DIR}/.env.example" ]]; then
    log "WARNING: .env not found. Copying .env.example → .env"
    cp "${SERVICE_DIR}/.env.example" "${ENV_FILE}"
    echo ""
    echo "============================================================"
    echo "  请编辑 ${ENV_FILE} 填写正确的 QWEN_API_KEY 后重新运行："
    echo "    nano ${ENV_FILE}"
    echo "    systemctl restart ${SERVICE_NAME}"
    echo "============================================================"
    echo ""
  else
    echo "ERROR: .env file not found. Aborting."
    exit 1
  fi
else
  log ".env file present (not overwritten)."
fi

# ---------- 7. 写入 systemd 服务文件 ----------
# Read SERVICE_PORT from .env (default 8000)
SERVICE_PORT=$(grep -m1 '^SERVICE_PORT=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '[:space:]')
SERVICE_PORT="${SERVICE_PORT:-8000}"

log "Writing systemd unit to ${SERVICE_FILE} (port ${SERVICE_PORT}) ..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Qwen VL Detection Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${SERVICE_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port ${SERVICE_PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------- 8. 启动 / 重启服务 ----------
log "Reloading systemd and (re)starting ${SERVICE_NAME} ..."
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 3
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  log "Service is running."
  curl -s http://localhost:${SERVICE_PORT}/health
  echo ""
  log "=== Deployment complete: ${DEPLOY_TAG:-main} (port ${SERVICE_PORT}) ✓ ==="
else
  log "ERROR: Service failed to start. Check logs:"
  log "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi

# =============================================================================
# deploy.sh — Qwen-VL Detection Service 部署脚本（Ubuntu + Miniconda + systemd）
#
# 用法（在目标服务器上执行）：
#   bash deploy.sh [--env-file /path/to/.env]
#
# 也可从本地通过 SSH 一键触发：
#   ssh root@<SERVER_IP> "bash -s" < scripts/deploy.sh
#
# 前置条件：
#   - Ubuntu 20.04+，root 或 sudo 权限
#   - 目标目录 /opt/qwen-vl-service 已包含项目代码（rsync 或 git clone）
#   - .env 文件已就绪（或通过 --env-file 参数传入）
# =============================================================================
set -euo pipefail

# ---------- 配置 ----------
SERVICE_DIR="/opt/qwen-vl-service"
CONDA_DIR="/opt/miniconda3"
CONDA_ENV="qwen-vl-service"
PYTHON_VERSION="3.11"
SERVICE_NAME="qwen-vl"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
MINICONDA_INSTALLER="/tmp/miniconda_installer.sh"
MINICONDA_URL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh"
ENV_FILE="${SERVICE_DIR}/.env"

# ---------- 参数解析 ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------- 1. 安装 Miniconda（如未安装）----------
if [[ ! -f "${CONDA_DIR}/bin/conda" ]]; then
  log "Installing Miniconda3 to ${CONDA_DIR} ..."
  curl -fsSL "${MINICONDA_URL}" -o "${MINICONDA_INSTALLER}"
  bash "${MINICONDA_INSTALLER}" -b -p "${CONDA_DIR}"
  rm -f "${MINICONDA_INSTALLER}"
  "${CONDA_DIR}/bin/conda" init bash
  log "Miniconda installed."
else
  log "Miniconda already present at ${CONDA_DIR}."
fi

CONDA="${CONDA_DIR}/bin/conda"
PIP="${CONDA_DIR}/envs/${CONDA_ENV}/bin/pip"
PYTHON="${CONDA_DIR}/envs/${CONDA_ENV}/bin/python"

# ---------- 2. 接受 Anaconda ToS ----------
log "Accepting conda ToS ..."
"${CONDA}" tos accept --override-channels \
  --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main \
  --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r 2>/dev/null || true

# ---------- 3. 创建 / 更新 conda 环境 ----------
if "${CONDA}" env list | grep -q "^${CONDA_ENV} "; then
  log "Conda env '${CONDA_ENV}' already exists."
else
  log "Creating conda env '${CONDA_ENV}' (Python ${PYTHON_VERSION}) ..."
  "${CONDA}" create -y -n "${CONDA_ENV}" python="${PYTHON_VERSION}" pip \
    -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge \
    --override-channels
fi

# ---------- 4. 安装 / 更新 Python 依赖 ----------
log "Installing Python dependencies ..."
"${PIP}" install --quiet -r "${SERVICE_DIR}/requirements.txt"

# ---------- 5. 检查 .env 文件 ----------
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${SERVICE_DIR}/.env.example" ]]; then
    log "WARNING: .env not found. Copying .env.example → .env"
    cp "${SERVICE_DIR}/.env.example" "${ENV_FILE}"
    echo ""
    echo "!!! 请编辑 ${ENV_FILE} 填写正确的 QWEN_API_KEY 后再启动服务 !!!"
    echo ""
  else
    echo "ERROR: .env file not found at ${ENV_FILE}. Aborting."
    exit 1
  fi
else
  log ".env file present."
fi

# ---------- 6. 写入 systemd 服务文件 ----------
log "Writing systemd unit to ${SERVICE_FILE} ..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Qwen VL Detection Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${SERVICE_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------- 7. 启动 / 重启服务 ----------
log "Reloading systemd and (re)starting ${SERVICE_NAME} ..."
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 3
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  log "Service is running."
  curl -s http://localhost:8000/health
  echo ""
  log "Deployment complete ✓"
else
  log "ERROR: Service failed to start. Check logs with:"
  log "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi
