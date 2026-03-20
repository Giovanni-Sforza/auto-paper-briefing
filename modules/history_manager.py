"""
history_manager.py — 历史记录管理模块
使用 JSON 文件维护已处理论文的去重记录
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class HistoryManager:
    """管理已处理论文的持久化记录，用于去重"""

    def __init__(self, history_file: str):
        self.history_file = history_file
        self._records: dict = {}  # arxiv_id -> record
        self._load()

    def _load(self):
        """从磁盘加载历史记录"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 兼容旧版（list格式）和新版（dict格式）
                    if isinstance(data, list):
                        self._records = {item["arxiv_id"]: item for item in data if "arxiv_id" in item}
                    elif isinstance(data, dict):
                        self._records = data
                logger.debug(f"  历史记录加载完毕，共 {len(self._records)} 条")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"  历史记录文件解析失败，将重新创建: {e}")
                self._records = {}
        else:
            logger.debug("  历史记录文件不存在，将创建新记录")
            self._records = {}

    def exists(self, arxiv_id: str) -> bool:
        """检查给定 arxiv_id 是否已处理过"""
        return arxiv_id in self._records

    def add(self, paper: dict):
        """将论文信息添加到内存记录中（不立即写磁盘）"""
        record = {
            "arxiv_id": paper["arxiv_id"],
            "title": paper.get("title", ""),
            "authors": paper.get("authors", []),
            "processed_at": datetime.now().isoformat(),
        }
        self._records[paper["arxiv_id"]] = record

    def save(self):
        """将当前内存中的记录持久化到磁盘"""
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)
        logger.debug(f"  历史记录已保存至 {self.history_file}")

    def count(self) -> int:
        """返回已记录的论文数量"""
        return len(self._records)
