#!/bin/bash
# CapsWriter-Offline Server Launcher
# 专为 Qwen3-ASR HuggingFace 后端配置（复用 .venv-qwen3 隔离环境）

set -e

# ── 定位到项目根目录 ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv-qwen3"
CONFIG_FILE="config_server.py"
LOG_DIR="logs"

# ── 检查虚拟环境 ─────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[✗] 虚拟环境不存在: $SCRIPT_DIR/$VENV_DIR"
    echo ""
    echo "请按以下步骤创建环境（只需执行一次）:"
    echo "  1. cd $SCRIPT_DIR"
    echo "  2. uv venv $VENV_DIR --python python3.12 --system-site-packages"
    echo "  3. uv pip install --python $VENV_DIR/bin/python 'transformers==4.57.6' 'qwen-asr'"
    echo "  4. uv pip install --python $VENV_DIR/bin/python rich websockets watchdog pypinyin pystray Pillow markdown tkhtmlview numpy"
    echo ""
    exit 1
fi

# ── 自动切换 model_type（如非 qwen_asr_hf）────────────────────────────
# 仅修改赋值行，跳过注释行
current_model=$(grep -E '^[[:space:]]*model_type[[:space:]]*=' "$CONFIG_FILE" | grep -v '#' | head -n 1 | sed "s/.*=[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/" || true)

if [ "$current_model" != "qwen_asr_hf" ]; then
    echo "[*] 检测到当前 model_type='${current_model:-未识别}'，自动切换为 'qwen_asr_hf'"
    # 精准替换非注释行的 model_type 赋值
    sed -i "0,/^\([[:space:]]*\)model_type[[:space:]]*=[[:space:]]*'[^']*'/s//\1model_type = 'qwen_asr_hf'/" "$CONFIG_FILE"
    echo "[*] 已更新 $CONFIG_FILE"
fi

# ── 激活虚拟环境 ─────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"

# ── 打印环境信息 ─────────────────────────────────────────────────────
echo "──────────────────────────────────────────────"
echo "  CapsWriter-Offline Server (Qwen3-ASR-HF)"
echo "──────────────────────────────────────────────"
echo "  Python : $(python --version 2>&1)"
echo "  Path   : $(which python)"
echo "  Backend: $(grep -E '^[[:space:]]*backend[[:space:]]*=' "$CONFIG_FILE" | grep -v '#' | head -n 1 | sed "s/.*=[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/" || echo 'transformers')"
echo "──────────────────────────────────────────────"
echo ""

# ── 创建日志目录 ─────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/server_$(date +%Y%m%d_%H%M%S).log"

# ── 启动服务器 ───────────────────────────────────────────────────────
# 支持两种模式：
#   前台运行（默认）: ./start_server_qwen3_hf.sh
#   后台运行        : nohup ./start_server_qwen3_hf.sh > /dev/null 2>&1 &
echo "[*] 启动中... 日志同时写入: $LOG_FILE"
echo "[*] 按 Ctrl+C 停止服务"
echo ""

exec python start_server.py 2>&1 | tee -a "$LOG_FILE"
