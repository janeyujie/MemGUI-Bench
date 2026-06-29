#!/bin/bash

# 检查是否传入了目录名参数
if [ -z "$1" ]; then
    echo "❌ 错误: 未指定目录名。"
    echo "💡 用法: $0 <目录名>"
    echo "例如: $0 experiment_01"
    exit 1
fi

# 赋值变量
DIR_NAME="$1"
CONTAINER="${CONTAINER:-memgui-bench}"
SRC_BASE="/root/MemGUI-Bench/results/$DIR_NAME"
DEST_BASE="/home/zhengyujie_lzk/src/MemGUI-Bench/new_results/$DIR_NAME"

# 定义需要复制的文件列表
FILES=(
    "config.yaml"
    "generale2e.json"
    "metrics_history.jsonl"
    "metrics_summary.csv"
    "metrics_summary.json"
    "progress_timing.json"
    "results.csv"
)

# 确保本地目标目录存在，如果不存在则自动创建
mkdir -p "$DEST_BASE"

echo "🚀 开始从容器复制文件到本地目录: $DIR_NAME"
echo "------------------------------------------------"

# 遍历文件列表并执行 docker cp
for FILE in "${FILES[@]}"; do
    echo "正在复制: $FILE ..."
    docker cp "${CONTAINER}:${SRC_BASE}/${FILE}" "${DEST_BASE}/"
    
    # 检查上一条命令是否执行成功
    if [ $? -eq 0 ]; then
        echo "  ✅ 成功"
    else
        echo "  ⚠️  失败 (可能是容器内缺少此文件)"
    fi
done

echo "------------------------------------------------"
echo "🎉 所有操作已完成！文件保存在: $DEST_BASE"

echo ""
echo "📦 开始额外复制 001 task 的完整 attempt 日志目录..."

TASK_DIR_IN_CONTAINER=$(docker exec "${CONTAINER}" sh -lc "find '${SRC_BASE}' -maxdepth 1 -mindepth 1 -type d -name '001-*' | head -n 1")

if [ -n "$TASK_DIR_IN_CONTAINER" ]; then
    TASK_DIR_NAME=$(basename "$TASK_DIR_IN_CONTAINER")
    echo "找到任务目录: $TASK_DIR_NAME"
    docker cp "${CONTAINER}:${TASK_DIR_IN_CONTAINER}" "${DEST_BASE}/"
    if [ $? -eq 0 ]; then
        echo "  ✅ 已复制 001 task 全目录到: ${DEST_BASE}/${TASK_DIR_NAME}"
    else
        echo "  ⚠️ 复制 001 task 目录失败"
    fi
else
    echo "  ⚠️ 未找到 001-* 任务目录，可能该 session 未运行 001 task"
fi
