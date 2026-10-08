#!/usr/bin/env bash
# chat-archive Skill 一键挂载脚本
#
# 说明：skill 源在仓库 .claude/skills/chat-archive/（真实目录，git 跟踪，
#       Claude Code 打开仓库即自动发现，无需挂载）。
#       本脚本为其它工具创建符号链接：.deepcode（仓库内）+
#       用户级 Codex / DeepSeek / WorkBuddy。
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
    ln -s "$SRC" "$dir/$name"
    echo "已挂载: $dir/$name → $SRC"
  fi
}

echo "== chat-archive Skill 挂载 =="
echo "源: $SRC"
echo

# 仓库内挂载（跟随仓库走，clone 后跑一次本脚本即可）
link "$REPO/.deepcode/skills" chat-archive
link "$REPO" skill   # 兼容旧路径 skill/scripts/...（README 命令用）

# 用户级挂载（可选，按你实际安装的工具）
link "$HOME/.codex/skills" chat-archive       # Codex 全局
link "$HOME/.agents/skills" chat-archive      # DeepSeek 桌面版
link "$HOME/.workbuddy/skills" chat-archive   # WorkBuddy

echo
echo "豆包（Doubao Work / 豆包办公）需手动挂载（路径因机器而异，Windows 见 README）："
echo "  mkdir -p \"\$HOME/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills\""
echo "  ln -s \"$SRC\" \"\$HOME/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills/chat-archive\""
echo
echo "完成。产物路径:  \$REPO/chat_archive_output/（每次运行一份独立目录）"
