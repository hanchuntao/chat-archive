"""向量化(可选): 把脱敏后的消息灌入本地 Chroma 向量库做语义检索。

依赖可选: pip install chat-archive[vector] (chromadb)。
未安装时命令给出友好提示, 不影响其余功能。
"""

from __future__ import annotations

from .db import Database

_EMBED_MSG_TAKE = 500


def vectorize(db: Database, *, chat_id: str | None = None,
              persist_dir: str = "chroma_data", collection: str = "chat_archive",
              batch_size: int = 200) -> dict:
    try:
        import chromadb
    except ImportError:
        raise RuntimeError(
            "未安装 chromadb. 请执行: pip install chromadb, 再重试。"
        )

    where = "chat_id = ?" if chat_id else "1=1"
    params = [chat_id] if chat_id else []
    rows = db.conn.execute(
        f"SELECT msg_id, sender, time, content, type FROM messages WHERE {where} "
        f"ORDER BY time ASC", params
    ).fetchall()

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_or_create_collection(collection)

    docs = [
        (r["msg_id"], (r["content"] or "")[_EMBED_MSG_TAKE],
         {"sender": r["sender"] or "", "time": r["time"] or "", "type": r["type"] or ""})
        for r in rows if (r["content"] or "").strip()
    ]
    existing = col.get(ids=[d[0] for d in docs[:batch_size]])["ids"] if docs else []

    added = 0
    for i in range(0, len(docs), batch_size):
        chunk = docs[i:i + batch_size]
        ids = [d[0] for d in chunk]
        texts = [d[1] for d in chunk]
        metas = [d[2] for d in chunk]
        col.upsert(ids=ids, documents=texts, metadatas=metas)
        added += len(chunk)

    return {"collection": collection, "persist_dir": persist_dir,
            "total_docs": len(docs), "upserted": added}
