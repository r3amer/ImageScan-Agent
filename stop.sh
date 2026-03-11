#!/bin/bash
#
# ImageScan 停止脚本
# 用于停止后端和前端服务
#

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}ℹ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# 停止服务
stop_services() {
    echo "停止 ImageScan 服务..."

    # 读取 PID 文件
    if [ -f ".backend.pid" ]; then
        BACKEND_PID=$(cat .backend.pid)
        echo "停止后端服务 (PID: $BACKEND_PID)..."
        kill $BACKEND_PID 2>/dev/null || print_error "后端进程已停止"
        rm .backend.pid
    fi

    if [ -f ".frontend.pid" ]; then
        FRONTEND_PID=$(cat .frontend.pid)
        echo "停止前端服务 (PID: $FRONTEND_PID)..."
        kill $FRONTEND_PID 2>/dev/null || print_error "前端进程已停止"
        rm .frontend.pid
    fi

    # 强制停止 uvicorn 和 npm (备用方案)
    pkill -f "uvicorn imagescan.api.main:app" 2>/dev/null
    pkill -f "next dev" 2>/dev/null

    echo "服务已停止"
}

stop_services
