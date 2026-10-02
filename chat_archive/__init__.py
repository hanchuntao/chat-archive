"""chat-archive: 微信群聊消息过滤归档工具。

架构: wechat-cli/WeFlow JSON → 清洗 → 脱敏 → SQLite+FTS5 主库
      → 检索/过滤/统计 | Markdown 周报/FAQ | (可选) Chroma 语义检索

数据全程本地处理, 不上传第三方云端。
"""

__version__ = "0.1.0"
