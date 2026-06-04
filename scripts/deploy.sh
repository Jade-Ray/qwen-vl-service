#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Qwen-VL Detection Service 部署脚本（Ubuntu + Miniconda + systemd）
#
# 用法（在目标服务器上执行，需要 root 权限）：
#
#   # 推荐：下载后执行（兼容 root 和 sudo）
#   curl -fsSL https://gitee.com/ambitionqi/qwen-vl-service/raw/main/scripts/deploy.sh \
#     -o /tmp/deploy.sh && bash /tmp/deploy.sh --tag v0.4.0
#
#   # 非 root 用户加 sudo（注意：sudo 不支持进程替换 <()，必须先下载）
#   curl -fsSL ... -o /tmp/deploy.sh && sudo bash /tmp/deploy.sh --tag v0.4.0
#
#   # 已在服务器上克隆仓库后，拉取 main 最新部署：
#   bash /opt/qwen-vl-service/scripts/deploy.sh
#
#   # 从本地通过 SSH 触发（服务器已有 deploy.sh）：
#   ssh root@<SERVER_IP> "bash /opt/qwen-vl-service/scripts/deploy.sh"
#
#   # 交互式：逐步选择执行步骤（例如只执行重启）
#   bash /opt/qwen-vl-service/scripts/deploy.sh --interactive
#
#   # 仅重启服务（代码已更新、环境不变）
#   bash /opt/qwen-vl-service/scripts/deploy.sh --restart-only
#
#   # 服务器网络受限：代码通过 scp 上传后，跳过 git 只做部署步骤
#   bash /opt/qwen-vl-service/scripts/deploy.sh --skip-git
#
# 敏感信息：
#   .env 文件不在仓库中，首次部署时脚本会从 .env.example 复制一份，
#   请手动编辑 /opt/qwen-vl-service/.env 填入真实 QWEN_API_KEY。
#   后续更新不会覆盖已有的 .env 文件。
# =============================================================================

# Guard: if invoked by sh/dash, re-exec with bash to support bash-only syntax.
if [ -z "${BASH_VERSION:-}" ]; then
  if command -v bash >/dev/null 2>&1; then
    exec bash "$0" "$@"
  fi
  echo "ERROR: 当前 shell 不支持本脚本，请使用 bash 执行："
  echo "  bash $0 $*"
  exit 1
fi

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
ENV_FILE_ARG=""

INTERACTIVE=0
MODE="full" # full | restart-only | update-code-only | init-only
SKIP_CONDA=0
SKIP_GIT=0
SKIP_DEPS=0
SKIP_SYSTEMD=0
SKIP_ENV_INIT=0

usage() {
  cat <<EOF
Usage: bash deploy.sh [options]

General:
  --tag <tag>            指定发布 tag（仅在 git 仓库模式生效）
  --repo <url>           指定仓库地址
  --env-file <path>      指定 .env 文件路径（用于 systemd EnvironmentFile）
  --interactive          交互式选择每个步骤是否执行
  --help                 显示帮助

Modes (mutually exclusive):
  --restart-only         仅执行服务重启与健康检查
  --update-code-only     仅执行代码更新（git/scp判定）
  --init-only            执行环境初始化（不写 systemd、不重启）

Skip switches:
  --skip-conda           跳过 conda 检测/安装与 ToS
  --skip-git             跳过 git 更新（适配 scp 上传代码）
  --skip-deps            跳过 pip 依赖安装
  --skip-systemd         跳过 systemd 写入与服务重启
  --skip-env-init        跳过 .env 初始化检查

Examples:
  bash deploy.sh
  bash deploy.sh --interactive
  bash deploy.sh --restart-only
  bash deploy.sh --skip-git --env-file /opt/qwen-vl-service/.env
EOF
}

# ---------- 参数解析 ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)    DEPLOY_TAG="$2";  shift 2 ;;
    --repo)   REPO_URL="$2";    shift 2 ;;
    --env-file) ENV_FILE_ARG="$2"; shift 2 ;;
    --interactive) INTERACTIVE=1; shift ;;
    --restart-only) MODE="restart-only"; shift ;;
    --update-code-only) MODE="update-code-only"; shift ;;
    --init-only) MODE="init-only"; shift ;;
    --skip-conda) SKIP_CONDA=1; shift ;;
    --skip-git) SKIP_GIT=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --skip-systemd) SKIP_SYSTEMD=1; shift ;;
    --skip-env-init) SKIP_ENV_INIT=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ---------- root 权限检查 ----------
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: 此脚本需要 root 权限。请切换到 root 用户或使用 sudo 执行："
  echo "  sudo bash deploy.sh $*"
  exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

warn() { echo "WARN: $*"; }

error_exit() {
  echo "ERROR: $*"
  exit 1
}

ask_step() {
  local var_name="$1"
  local label="$2"
  local current="${!var_name}"
  local default="n"
  if [[ "$current" -eq 1 ]]; then
    default="y"
  fi

  local ans=""
  read -r -p "执行步骤${label}? [y/n] (default: ${default}) " ans
  ans="${ans:-$default}"
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    printf -v "$var_name" 1
  else
    printf -v "$var_name" 0
  fi
}

is_code_tree_present() {
  [[ -d "${SERVICE_DIR}/app" && -f "${SERVICE_DIR}/requirements.txt" ]]
}

# ---------- 步骤开关初始化 ----------
RUN_A=1 # conda 检测/安装
RUN_B=1 # conda ToS
RUN_C=1 # 代码更新
RUN_D=1 # conda env 创建
RUN_E=1 # pip 依赖安装
RUN_F=1 # .env 检查/初始化
RUN_G=1 # 写 systemd 文件
RUN_H=1 # 重启服务 + 健康检查

case "${MODE}" in
  full)
    ;;
  restart-only)
    RUN_A=0; RUN_B=0; RUN_C=0; RUN_D=0; RUN_E=0; RUN_F=0; RUN_G=0; RUN_H=1
    ;;
  update-code-only)
    RUN_A=0; RUN_B=0; RUN_C=1; RUN_D=0; RUN_E=0; RUN_F=0; RUN_G=0; RUN_H=0
    ;;
  init-only)
    RUN_A=1; RUN_B=1; RUN_C=1; RUN_D=1; RUN_E=1; RUN_F=1; RUN_G=0; RUN_H=0
    ;;
  *)
    error_exit "Unsupported mode: ${MODE}"
    ;;
esac

if [[ "${SKIP_CONDA}" -eq 1 ]]; then
  RUN_A=0
  RUN_B=0
fi
if [[ "${SKIP_GIT}" -eq 1 ]]; then
  RUN_C=0
fi
if [[ "${SKIP_DEPS}" -eq 1 ]]; then
  RUN_E=0
fi
if [[ "${SKIP_SYSTEMD}" -eq 1 ]]; then
  RUN_G=0
  RUN_H=0
fi
if [[ "${SKIP_ENV_INIT}" -eq 1 ]]; then
  RUN_F=0
fi

if [[ "${INTERACTIVE}" -eq 1 ]]; then
  echo ""
  echo "==== 交互式步骤选择 ===="
  echo "A. conda 检测/安装"
  echo "B. conda ToS 接受"
  echo "C. 代码更新（git）"
  echo "D. conda 环境创建"
  echo "E. 安装 Python 依赖"
  echo "F. .env 检查/初始化"
  echo "G. 写入 systemd 服务文件"
  echo "H. 重启服务 + 健康检查"
  echo ""

  ask_step RUN_A "A"
  ask_step RUN_B "B"
  ask_step RUN_C "C"
  ask_step RUN_D "D"
  ask_step RUN_E "E"
  ask_step RUN_F "F"
  ask_step RUN_G "G"
  ask_step RUN_H "H"
fi

if [[ "${RUN_A}" -eq 0 && "${RUN_B}" -eq 1 ]]; then
  error_exit "步骤B依赖 conda。请启用步骤A或关闭步骤B。"
fi

if [[ "${RUN_C}" -eq 0 && -n "${DEPLOY_TAG}" ]]; then
  warn "已指定 --tag ${DEPLOY_TAG}，但代码更新步骤被跳过；tag 不会生效。"
fi

if [[ "${RUN_A}" -eq 0 && "${RUN_D}" -eq 1 ]]; then
  warn "步骤D将假设系统已可用 conda。"
fi

if [[ "${RUN_A}" -eq 0 && "${RUN_E}" -eq 1 ]]; then
  warn "步骤E将假设 conda env 已存在。"
fi

if [[ "${RUN_A}${RUN_B}${RUN_C}${RUN_D}${RUN_E}${RUN_F}${RUN_G}${RUN_H}" == "00000000" ]]; then
  error_exit "没有可执行步骤，请调整参数或交互选择。"
fi

# ---------- 1. 检测 / 安装 conda ----------
# sudo bash 不继承用户 PATH，需同时搜索常见安装路径
_find_conda() {
  # 1. 当前 PATH 中查找
  if command -v conda &>/dev/null; then
    command -v conda; return
  fi
  # 2. 搜索常见安装路径（覆盖 ~/miniconda3、~/anaconda3、/opt/* 等）
  local _candidates=(
    "${HOME}/miniconda3/bin/conda"
    "${HOME}/miniconda/bin/conda"
    "${HOME}/anaconda3/bin/conda"
    "${HOME}/anaconda/bin/conda"
    "${HOME}/mambaforge/bin/conda"
    "${HOME}/miniforge3/bin/conda"
    "/opt/miniconda3/bin/conda"
    "/opt/anaconda3/bin/conda"
    "/opt/mambaforge/bin/conda"
    "/usr/local/miniconda3/bin/conda"
    "/usr/local/anaconda3/bin/conda"
  )
  # 3. 搜索所有用户 home 目录下的 conda
  for _home in /home/*/; do
    _candidates+=(
      "${_home}miniconda3/bin/conda"
      "${_home}anaconda3/bin/conda"
      "${_home}mambaforge/bin/conda"
      "${_home}miniforge3/bin/conda"
    )
  done
  for _c in "${_candidates[@]}"; do
    [[ -x "${_c}" ]] && echo "${_c}" && return
  done
  return 1
}

CONDA=""
PIP=""
PYTHON=""
SERVICE_PORT=""
ENV_FILE="${ENV_FILE_ARG:-${SERVICE_DIR}/.env}"

executed_steps=()
skipped_steps=()

mark_executed() { executed_steps+=("$1"); }
mark_skipped() { skipped_steps+=("$1"); }

# ---------- A. 检测 / 安装 conda ----------
if [[ "${RUN_A}" -eq 1 ]]; then
  if _CONDA_BIN="$(_find_conda)"; then
    CONDA="${_CONDA_BIN}"
    CONDA_DIR="$("${CONDA}" info --base 2>/dev/null)"
    log "Found conda: ${CONDA} (base: ${CONDA_DIR})"
  else
    log "conda not found."
    echo ""
    echo "未检测到 conda，需要安装 Miniconda3 到 ${CONDA_DIR}"
    read -r -p "是否继续安装？[y/N] " _answer
    case "${_answer}" in
      [yY][eE][sS]|[yY]) ;;
      *)
        error_exit "已取消。请手动安装 conda 后重新运行此脚本。"
        ;;
    esac
    log "Installing Miniconda3 to ${CONDA_DIR} ..."
    curl -fsSL "${MINICONDA_URL}" -o "${MINICONDA_INSTALLER}"
    bash "${MINICONDA_INSTALLER}" -b -p "${CONDA_DIR}"
    rm -f "${MINICONDA_INSTALLER}"
    CONDA="${CONDA_DIR}/bin/conda"
    log "Miniconda installed."
  fi
  mark_executed "A"
else
  mark_skipped "A"
fi

# 对需要 conda 的步骤做兜底检测
if [[ -z "${CONDA}" && ( "${RUN_B}" -eq 1 || "${RUN_D}" -eq 1 || "${RUN_E}" -eq 1 ) ]]; then
  if _CONDA_BIN="$(_find_conda)"; then
    CONDA="${_CONDA_BIN}"
    CONDA_DIR="$("${CONDA}" info --base 2>/dev/null)"
    log "Found conda for subsequent steps: ${CONDA} (base: ${CONDA_DIR})"
  else
    error_exit "后续步骤需要 conda，但未找到 conda。请启用步骤A或手动安装 conda。"
  fi
fi

if [[ -n "${CONDA_DIR}" ]]; then
  PIP="${CONDA_DIR}/envs/${CONDA_ENV}/bin/pip"
  PYTHON="${CONDA_DIR}/envs/${CONDA_ENV}/bin/python"
else
  PIP="${CONDA_DIR}/envs/${CONDA_ENV}/bin/pip"
  PYTHON="${CONDA_DIR}/envs/${CONDA_ENV}/bin/python"
fi

# ---------- B. 接受 Anaconda ToS ----------
if [[ "${RUN_B}" -eq 1 ]]; then
  "${CONDA}" tos accept --override-channels \
    --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main \
    --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r 2>/dev/null || true
  mark_executed "B"
else
  mark_skipped "B"
fi

# ---------- C. 拉取代码（或识别 scp 上传） ----------
if [[ "${RUN_C}" -eq 1 ]]; then
  if [[ -d "${SERVICE_DIR}/.git" ]]; then
    log "Repository already cloned. Fetching updates ..."
    cd "${SERVICE_DIR}"
    git fetch --tags origin

    if [[ -n "${DEPLOY_TAG}" ]]; then
      if ! git rev-parse -q --verify "refs/tags/${DEPLOY_TAG}" >/dev/null; then
        echo "Available tags (latest 10):"
        git tag --sort=-creatordate | head -n 10
        error_exit "指定 tag 不存在: ${DEPLOY_TAG}"
      fi
      log "Checking out tag ${DEPLOY_TAG} ..."
      git checkout "${DEPLOY_TAG}"
    else
      log "No --tag specified. Pulling latest main ..."
      git checkout main
      git pull origin main
    fi
    log "Deployed commit: $(git log -1 --oneline)"
  else
    if is_code_tree_present; then
      if [[ -n "${DEPLOY_TAG}" ]]; then
        error_exit "当前代码目录无 .git，无法使用 --tag。请改用 main/git 仓库方式，或移除 --tag。"
      fi
      log "Detected uploaded source tree (scp mode). Skip git sync."
    else
      log "Creating service directory ${SERVICE_DIR} ..."
      mkdir -p "${SERVICE_DIR}"
      log "Cloning repository from ${REPO_URL} ..."
      git clone "${REPO_URL}" "${SERVICE_DIR}"
      cd "${SERVICE_DIR}"
      git fetch --tags origin
      if [[ -n "${DEPLOY_TAG}" ]]; then
        if ! git rev-parse -q --verify "refs/tags/${DEPLOY_TAG}" >/dev/null; then
          echo "Available tags (latest 10):"
          git tag --sort=-creatordate | head -n 10
          error_exit "指定 tag 不存在: ${DEPLOY_TAG}"
        fi
        git checkout "${DEPLOY_TAG}"
      else
        git checkout main
      fi
      log "Deployed commit: $(git log -1 --oneline)"
    fi
  fi
  mark_executed "C"
else
  mark_skipped "C"
  if [[ "${SKIP_GIT}" -eq 1 ]]; then
    log "Git sync skipped by --skip-git."
  fi
fi

# ---------- D. 创建 / 更新 conda 环境 ----------
if [[ "${RUN_D}" -eq 1 ]]; then
  if "${CONDA}" env list | grep -Eq "^${CONDA_ENV}[[:space:]]"; then
    log "Conda env '${CONDA_ENV}' already exists."
  else
    log "Creating conda env '${CONDA_ENV}' (Python ${PYTHON_VERSION}) ..."
    "${CONDA}" create -y -n "${CONDA_ENV}" python="${PYTHON_VERSION}" pip \
      -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge \
      --override-channels
  fi
  mark_executed "D"
else
  mark_skipped "D"
fi

# ---------- E. 安装 / 更新 Python 依赖 ----------
if [[ "${RUN_E}" -eq 1 ]]; then
  if [[ ! -f "${SERVICE_DIR}/requirements.txt" ]]; then
    error_exit "未找到 ${SERVICE_DIR}/requirements.txt。若使用 scp，请确认代码上传完整。"
  fi
  log "Installing Python dependencies ..."
  "${PIP}" install --quiet -r "${SERVICE_DIR}/requirements.txt"
  mark_executed "E"
else
  mark_skipped "E"
fi

# ---------- F. 检查 .env 文件 ----------
if [[ "${RUN_F}" -eq 1 ]]; then
  if [[ -n "${ENV_FILE_ARG}" ]]; then
    if [[ ! -f "${ENV_FILE_ARG}" ]]; then
      error_exit "--env-file 指定文件不存在: ${ENV_FILE_ARG}"
    fi
    log "Using external env file: ${ENV_FILE_ARG}"
  else
    if [[ ! -f "${ENV_FILE}" ]]; then
      if [[ -f "${SERVICE_DIR}/.env.example" ]]; then
        log "WARNING: .env not found. Copying .env.example → .env"
        cp "${SERVICE_DIR}/.env.example" "${ENV_FILE}"
        echo ""
        echo "============================================================"
        echo "  请编辑 ${ENV_FILE} 填写正确的 QWEN_API_KEY 后继续。"
        echo "============================================================"
        echo ""
      else
        error_exit ".env file not found and .env.example missing."
      fi
    else
      log ".env file present (not overwritten)."
    fi
  fi
  mark_executed "F"
else
  mark_skipped "F"
fi

if [[ "${RUN_G}" -eq 1 || "${RUN_H}" -eq 1 ]]; then
  if [[ ! -f "${ENV_FILE}" ]]; then
    error_exit "需要读取 env，但未找到: ${ENV_FILE}。请执行步骤F或通过 --env-file 指定。"
  fi
fi

# ---------- G. 写入 systemd 服务文件 ----------
if [[ "${RUN_G}" -eq 1 ]]; then
  SERVICE_PORT="$(grep -m1 '^SERVICE_PORT=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '[:space:]' || true)"
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
  mark_executed "G"
else
  mark_skipped "G"
fi

# ---------- H. 启动 / 重启服务 ----------
if [[ "${RUN_H}" -eq 1 ]]; then
  if [[ -z "${SERVICE_PORT}" ]]; then
    SERVICE_PORT="$(grep -m1 '^SERVICE_PORT=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '[:space:]' || true)"
    SERVICE_PORT="${SERVICE_PORT:-8000}"
  fi

  log "Reloading systemd and (re)starting ${SERVICE_NAME} ..."
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"

  sleep 3
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    log "Service is running."
    if command -v curl >/dev/null 2>&1; then
      curl -fsS "http://localhost:${SERVICE_PORT}/health" || true
    fi
    echo ""
    log "=== Deployment complete: ${DEPLOY_TAG:-main-or-local} (port ${SERVICE_PORT}) ✓ ==="
  else
    log "ERROR: Service failed to start. Check logs:"
    log "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
    exit 1
  fi
  mark_executed "H"
else
  mark_skipped "H"
fi

echo ""
log "Executed steps: ${executed_steps[*]:-(none)}"
log "Skipped steps: ${skipped_steps[*]:-(none)}"

