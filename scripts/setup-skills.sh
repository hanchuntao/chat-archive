#!/usr/bin/env bash
# chat-archive Skill 按需挂载脚本
#
# 说明：skill 源在仓库 .claude/skills/chat-archive/（真实目录，git 跟踪，
#       Claude Code 打开仓库即自动发现，无需挂载）。
#       本脚本按需为指定工具创建符号链接：仓库内 .deepcode + skill（默认，跟随
#       仓库走），以及可选用户级 Codex / DeepSeek / WorkBuddy / 豆包。
#
# 用法（按需指定，装了什么就挂什么）：
#   bash scripts/setup-skills.sh              # 只挂仓库内（.deepcode + skill）
#   bash scripts/setup-skills.sh codex        # 挂 Codex
#   bash scripts/setup-skills.sh doubao       # 挂豆包（按平台自动探测目录）
#   bash scripts/setup-skills.sh codex deepseek workbuddy doubao   # 组合
#   bash scripts/setup-skills.sh all          # 全部
#   bash scripts/setup-skills.sh --help       # 查看可用参数
#
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
      echo "⚠️  链接创建失败: $dir/${name}（Windows 请用管理员终端执行: mklink /D \"$dir\\$name\" \"${SRC}\"）"
    fi
  fi
}

# 平台探测（豆包目录位置因系统而异，探测真实存在的目录才挂）
os="$(uname -s 2>/dev/null || echo unknown)"
case "$os" in
  Darwin)  platform="macos" ;;
  MINGW*|MSYS*|CYGWIN*) platform="windows" ;;
  Linux*)  platform="linux" ;;
  *)       platform="unknown" ;;
esac

# ---------- 参数解析：想挂哪个工具就指定哪个 ----------
targets=("$@")
if [ "$#" -eq 0 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  echo "== chat-archive Skill 按需挂载（平台: ${platform}）=="
  echo "源: $SRC"
  echo
  echo "用法: bash scripts/setup-skills.sh [工具...]   （不传 = 只挂仓库内）"
  echo "可选工具（可组合，空格分隔）:"
  echo "  codex      挂到 ~/.codex/skills/chat-archive"
  echo "  deepseek   挂到 ~/.agents/skills/chat-archive（DeepSeek 桌面版）"
  echo "  workbuddy  挂到 ~/.workbuddy/skills/chat-archive"
  echo "  doubao     挂到豆包 .user_skills/chat-archive（按平台自动探测目录）"
  echo "  all        以上全部"
  echo
  echo "示例:"
  echo "  bash scripts/setup-skills.sh codex doubao"
  echo "  bash scripts/setup-skills.sh all"
  echo
  echo "说明: 仓库内 .deepcode/skills 与根 skill 符号链接随本脚本默认挂载，跟随仓库走；"
  echo "      Claude Code 用 .claude/skills（真实目录），clone 即用，无需挂载。"
  exit 0
fi

want_all=0
want_codex=0; want_deepseek=0; want_workbuddy=0; want_doubao=0
for t in "${targets[@]}"; do
  case "$t" in
    all)    want_all=1 ;;
    codex)  want_codex=1 ;;
    deepseek) want_deepseek=1 ;;
    workbuddy) want_workbuddy=1 ;;
    doubao) want_doubao=1 ;;
    *)
      echo "❌ 未知工具: ${t}（可用: codex / deepseek / workbuddy / doubao / all）" >&2
      exit 1
      ;;
  esac
done
[ "$want_all" -eq 1 ] && want_codex=1 && want_deepseek=1 && want_workbuddy=1 && want_doubao=1

echo "== chat-archive Skill 按需挂载（平台: ${platform}）=="
echo "源: $SRC"
echo

# 仓库内挂载（默认，跟随仓库走）
link "$REPO/.deepcode/skills" chat-archive
link "$REPO" skill   # 兼容旧路径 skill/scripts/...（README 命令用）

# 用户级挂载（仅当参数指定）
if [ "$want_codex" -eq 1 ]; then
  link "$HOME/.codex/skills" chat-archive       # Codex 全局
fi
if [ "$want_deepseek" -eq 1 ]; then
  link "$HOME/.agents/skills" chat-archive      # DeepSeek 桌面版
fi
if [ "$want_workbuddy" -eq 1 ]; then
  link "$HOME/.workbuddy/skills" chat-archive   # WorkBuddy
fi

# 豆包：按平台探测（真实存在的 user_skills 目录才挂）
if [ "$want_doubao" -eq 1 ]; then
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
fi

echo
echo "完成。产物路径:  \$REPO/chat_archive_output/（每次运行一份独立目录）"
