#!/usr/bin/env bash
# chat-archive Skill 一键挂载脚本
#
# 说明：skill 源在仓库 .claude/skills/chat-archive/（真实目录，git 跟踪，
#       Claude Code 打开仓库即自动发现，无需挂载）。
#       本脚本为其它工具创建符号链接：.deepcode（仓库内）+ 用户级
#       Codex / DeepSeek / WorkBuddy / 豆包（按平台自动探测目录）。
#
# 用法:  bash scripts/setup-skills.sh
# 幂等:  已存在的挂载点自动跳过，可重复执行。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/.claude/skills/chat-archive"

if [ ! -d "$SRC" ]; then
  echo "❌ skill 源不存在: $SRC" >&2
  exit 1
fi

link() { # link <目标目录> <名称>
  local dir="$1" name="$2"
  mkdir -p "$dir"
  if [ -L "$dir/$name" ] || [ -e "$dir/$name" ]; then
    echo "已存在（跳过）: $dir/$name"
  else
    if ln -s "$SRC" "$dir/$name" 2>/dev/null; then
      echo "已挂载: $dir/$name → $SRC"
    else
      echo "⚠️  链接创建失败: $dir/$name（Windows 请用管理员终端执行: mklink /D \"$dir\\$name\" \"${SRC}\"）"
    fi
  fi
}

# 平台探测：仅从候选路径中挑"真实存在的目录"挂载，探测不到才提示
# （各平台豆包/工具的 skill 目录位置不同，且可能未安装）
os="$(uname -s 2>/dev/null || echo unknown)"
case "$os" in
  Darwin)  platform="macos" ;;
  MINGW*|MSYS*|CYGWIN*) platform="windows" ;;
  Linux*)  platform="linux" ;;
  *)       platform="unknown" ;;
esac

echo "== chat-archive Skill 挂载（平台: ${platform}）=="
echo "源: $SRC"
echo

# 仓库内挂载（跟随仓库走，clone 后跑一次本脚本即可）
link "$REPO/.deepcode/skills" chat-archive
link "$REPO" skill   # 兼容旧路径 skill/scripts/...（README 命令用）

# 用户级挂载（可选，按你实际安装的工具）
link "$HOME/.codex/skills" chat-archive       # Codex 全局
link "$HOME/.agents/skills" chat-archive      # DeepSeek 桌面版
link "$HOME/.workbuddy/skills" chat-archive   # WorkBuddy

# 豆包（Doubao Work / 豆包办公）：按平台探测用户 skill 目录
case "$platform" in
  macos)
    DOUBAO_DIRS=(
      "$HOME/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills"
      "$HOME/Library/Application Support/DoubaoWork/agent_mode/workspace/.user_skills"
    )
    ;;
  windows)
    DOUBAO_DIRS=(
      "$LOCALAPPDATA/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills"
      "$APPDATA/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills"
    )
    ;;
  linux)
    DOUBAO_DIRS=(
      "$HOME/.config/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills"
      "$HOME/.doubaowork/Default/.doubaowork/agent_mode/workspace/.user_skills"
    )
    ;;
  *)
    DOUBAO_DIRS=()
    ;;
esac

doubao_linked=0
for d in "${DOUBAO_DIRS[@]:-}"; do
  if [ -n "$d" ] && [ -d "$d" ]; then
    link "$d" chat-archive
    doubao_linked=1
  fi
done
if [ "$doubao_linked" -eq 0 ]; then
  echo
  echo "豆包 skill 目录未探测到（可能未安装，或路径与下列候选不同）："
  for d in "${DOUBAO_DIRS[@]:-}"; do
    [ -n "$d" ] && echo "  $d"
  done
  echo "如已安装豆包，请把实际 user_skills 目录路径告诉我，或在对应目录执行:"
  echo "  ln -s \"$SRC\" \"<实际 user_skills 目录>/chat-archive\""
fi

echo
echo "完成。产物路径:  \$REPO/chat_archive_output/（每次运行一份独立目录）"
