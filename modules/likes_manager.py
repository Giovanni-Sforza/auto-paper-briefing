"""
likes_manager.py — 点赞历史管理模块

只存储用户主动点赞的文章，按时间倒序排列。
数据结构与 clicks.json 完全独立，互不干扰。
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class LikesManager:
    """管理点赞历史记录（仅点赞，不含普通点击）"""

    def __init__(self, likes_file: str):
        self.likes_file = likes_file
        self._likes: list[dict] = []
        self._liked_ids: set[str] = set()
        self._load()

    def add_like(self, arxiv_id: str, title: str, authors: list,
                 abs_url: str, summary: dict = None) -> bool:
        """
        添加一条点赞记录。
        同一篇文章重复点赞不重复记录，返回 False 表示已存在。
        """
        if arxiv_id in self._liked_ids:
            return False

        record = {
            "arxiv_id":  arxiv_id,
            "title":     title,
            "authors":   authors[:5],
            "abs_url":   abs_url,
            "liked_at":  datetime.now().isoformat(),
            "summary_snippet": self._extract_snippet(summary),
        }
        self._likes.insert(0, record)  # 新记录插在最前（倒序）
        self._liked_ids.add(arxiv_id)
        self._save()
        logger.info(f"  [Likes] 已记录点赞: {arxiv_id} — {title[:50]}")
        return True

    def all_likes(self) -> list[dict]:
        """返回全部点赞记录（已按时间倒序）"""
        return self._likes

    def count(self) -> int:
        return len(self._likes)

    def has_liked(self, arxiv_id: str) -> bool:
        return arxiv_id in self._liked_ids

    def for_prompt(self) -> str:
        """将点赞记录格式化为 prompt 文本，供 KeywordEvolver 使用"""
        lines = []
        for r in self._likes[:30]:  # 最多取 30 条
            date = r.get("liked_at", "")[:10]
            lines.append(f"👍 [点赞] {r['title']} （{date}）")
        return "\n".join(lines)

    # ── 私有 ─────────────────────────────────────────────────

    def _extract_snippet(self, summary: dict | None) -> str:
        """从 AI 总结中提取简短摘要（用于历史页展示）"""
        if not summary or not isinstance(summary, dict):
            return ""
        for val in summary.values():
            if isinstance(val, str) and len(val) > 10:
                return val[:100] + ("…" if len(val) > 100 else "")
        return ""

    def _load(self):
        if os.path.exists(self.likes_file):
            try:
                with open(self.likes_file, "r", encoding="utf-8") as f:
                    self._likes = json.load(f)
                self._liked_ids = {r["arxiv_id"] for r in self._likes}
            except Exception as e:
                logger.warning(f"  [Likes] 加载失败，将重建: {e}")
                self._likes = []
                self._liked_ids = set()

    def _save(self):
        with open(self.likes_file, "w", encoding="utf-8") as f:
            json.dump(self._likes, f, ensure_ascii=False, indent=2)
