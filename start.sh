#!/bin/bash
#
# ImageScan 启动脚本
# 用于同时启动后端 API 和前端服务
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_section() {
    echo -e "\n${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}\n"
}

# 检查依赖
check_dependencies() {
    print_section "检查依赖"

    # 检查 Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 未安装"
        exit 1
    fi
    print_success "Python 3: $(python3 --version)"

    # 检查 Node.js
    if ! command -v node &> /dev/null; then
        print_error "Node.js 未安装"
        exit 1
    fi
    print_success "Node.js: $(node --version)"

    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装"
        exit 1
    fi
    print_success "Docker: $(docker --version)"

    # 检查 Docker 是否运行
    if ! docker info &> /dev/null; then
        print_error "Docker 守护进程未运行"
        exit 1
    fi
    print_success "Docker 守护进程运行中"
}

# 安装后端依赖
install_backend() {
    print_section "安装后端依赖"

    if [ ! -d "venv" ]; then
        print_info "创建 Python 虚拟环境..."
        python3 -m venv venv
    fi

    print_info "激活虚拟环境..."
    source venv/bin/activate

    print_info "安装 Python 依赖..."
    pip install -q --upgrade pip
    pip install -q -e .

    print_success "后端依赖安装完成"
}

# 安装前端依赖
install_frontend() {
    print_section "安装前端依赖"

    if [ ! -d "frontend/node_modules" ]; then
        print_info "安装 Node.js 依赖..."
        cd frontend
        npm install
        cd ..
    fi

    print_success "前端依赖安装完成"
}

# 启动后端
start_backend() {
    print_section "启动后端服务"

    # 检查是否已激活虚拟环境
    if [ -z "$VIRTUAL_ENV" ]; then
        source venv/bin/activate
    fi

    print_info "启动 FastAPI 服务..."
    print_info "API 地址: http://0.0.0.0:8000"
    print_info "API 文档: http://localhost:8000/docs"

    # 后台启动服务（监听所有网络接口）
    nohup uvicorn imagescan.api.main:app --host 0.0.0.0 --reload --port 8000 > backend.log 2>&1 &
    BACKEND_PID=$!

    # 保存 PID
    echo $BACKEND_PID > .backend.pid

    print_success "后端服务已启动 (PID: $BACKEND_PID)"

    # 等待服务启动
    print_info "等待后端服务启动..."
    sleep 5

    # 检查服务是否运行
    if curl -s http://localhost:8000/health > /dev/null; then
        print_success "后端服务就绪"
    else
        print_error "后端服务启动失败，请检查 backend.log"
        exit 1
    fi
}

# 启动前端
start_frontend() {
    print_section "启动前端服务"

    print_info "启动 Next.js 开发服务器..."
    print_info "前端地址: http://localhost:3000"

    # 后台启动服务
    cd frontend
    nohup npm run dev > ../frontend.log 2>&1 &
    FRONTEND_PID=$!
    cd ..

    # 保存 PID
    echo $FRONTEND_PID > .frontend.pid

    print_success "前端服务已启动 (PID: $FRONTEND_PID)"

    # 等待服务启动
    print_info "等待前端服务启动..."
    sleep 10

    # 检查服务是否运行
    if curl -s http://localhost:3000 > /dev/null; then
        print_success "前端服务就绪"
    else
        print_error "前端服务启动失败，请检查 frontend.log"
    fi
}

# 显示使用说明
show_instructions() {
    print_section "使用说明"

    echo -e "${GREEN}服务已启动！${NC}\n"

    echo -e "  ${BOLD}前端界面:${NC}"
    echo -e "    ${BLUE}http://localhost:3000${NC}\n"

    echo -e "  ${BOLD}后端 API:${NC}"
    echo -e "    ${BLUE}http://localhost:8000${NC}"
    echo -e "    ${BLUE}http://localhost:8000/docs${NC} (API 文档)\n"

    echo -e "  ${BOLD}日志文件:${NC}"
    echo -e "    后端: ${YELLOW}backend.log${NC}"
    echo -e "    前端: ${YELLOW}frontend.log${NC}\n"

    echo -e "  ${BOLD}停止服务:${NC}"
    echo -e "    ${YELLOW}./stop.sh${NC} 或 ${YELLOW}kill \$(cat .backend.pid) \$(cat .frontend.pid)${NC}\n"

    echo -e "  ${BOLD}运行测试:${NC}"
    echo -e "    ${YELLOW}python test_integration.py${NC}\n"
}

# 主函数
main() {
    print_section "ImageScan 启动"

    # 检查是否在项目根目录
    if [ ! -f "CLAUDE.md" ] || [ ! -d "imagescan" ]; then
        print_error "请在项目根目录运行此脚本"
        exit 1
    fi

    # 检查依赖
    check_dependencies

    # 安装依赖
    install_backend
    install_frontend

    # 启动服务
    start_backend
    start_frontend

    # 显示说明
    show_instructions
}

# 运行主函数
main
