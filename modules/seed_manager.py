"""
seed_manager.py — 种子文章管理模块

支持手动添加 arXiv 文章作为关键词进化的高权重信号。
权重等级（3档）：
  1 = 普通推荐  (weight=1.0)  — 同学顺口提到
  2 = 重要      (weight=3.0)  — 导师建议读
  3 = 核心必读  (weight=6.0)  — 与自己研究直接相关

去重逻辑：
  - 相同 arXiv ID 再次添加时，等级自动升档（不降档）
  - 升档时更新 updated_at 字段
"""

import json
import os
import re
import logging
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

# 权重等级定义
LEVELS = {
    1: {"name": "普通推荐", "emoji": "📌", "weight": 1.0},
    2: {"name": "重要",     "emoji": "⭐", "weight": 3.0},
    3: {"name": "核心必读", "emoji": "🔥", "weight": 6.0},
}

# 点赞的隐式权重（介于普通和重要之间）
LIKE_WEIGHT = 2.0


def _parse_arxiv_id(url_or_id: str) -> str | None:
    """
    从各种格式中提取干净的 arXiv ID。
    支持：
      2401.12345
      2401.12345v2
      https://arxiv.org/abs/2401.12345
      https://arxiv.org/pdf/2401.12345v1
      http://arxiv.org/abs/2401.12345
    """
    s = url_or_id.strip()
    # 先尝试从 URL 提取
    match = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})', s, re.IGNORECASE)
    if match:
        return match.group(1).split("v")[0]
    # 纯 ID 格式
    match = re.match(r'^([0-9]{4}\.[0-9]{4,5})', s)
    if match:
        return match.group(1)
    return None


def _fetch_arxiv_meta(arxiv_id: str) -> dict:
    """通过 arXiv API 获取论文元数据（标题、作者）"""
    import xml.etree.ElementTree as ET
    NS = {"atom": "http://www.w3.org/2005/Atom"}
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoPaperBriefing/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
        entry = root.find("atom:entry", NS)
        if entry is None:
            return {}
        title = entry.find("atom:title", NS)
        authors = entry.findall("atom:author", NS)
        return {
            "title":   title.text.strip().replace("\n", " ") if title is not None else "",
            "authors": [a.find("atom:name", NS).text.strip() for a in authors if a.find("atom:name", NS) is not None],
        }
    except Exception as e:
        logger.warning(f"  [Seed] 获取元数据失败 ({arxiv_id}): {e}")
        return {}


class SeedManager:
    """管理手动添加的种子文章"""

    def __init__(self, seeds_file: str):
        self.seeds_file = seeds_file
        self._seeds: dict[str, dict] = {}  # arxiv_id -> record
        self._load()

    # ── 公开接口 ──────────────────────────────────────────────

    def add(self, url_or_id: str, level: int, note: str = "") -> dict:
        """
        添加或升档一篇种子文章。
        返回操作结果字典（供 CLI 展示）。
        """
        level = max(1, min(3, level))  # 钳位到 1~3
        arxiv_id = _parse_arxiv_id(url_or_id)
        if not arxiv_id:
            raise ValueError(f"无法解析 arXiv ID: {url_or_id!r}")

        now = datetime.now().isoformat()

        if arxiv_id in self._seeds:
            old = self._seeds[arxiv_id]
            old_level = old["level"]
            if level > old_level:
                old["level"]      = level
                old["weight"]     = LEVELS[level]["weight"]
                old["updated_at"] = now
                old["note"]       = note or old.get("note", "")
                self._save()
                logger.info(f"  [Seed] 升档: {arxiv_id}  {old_level}→{level}  {old['title'][:50]}")
                return {"status": "upgraded", "arxiv_id": arxiv_id,
                        "old_level": old_level, "new_level": level, **old}
            else:
                logger.info(f"  [Seed] 已存在且等级不低于输入，无需更新: {arxiv_id}")
                return {"status": "exists", "arxiv_id": arxiv_id, **old}

        # 新文章：先拉元数据
        logger.info(f"  [Seed] 正在获取论文信息: {arxiv_id} ...")
        meta = _fetch_arxiv_meta(arxiv_id)
        record = {
            "arxiv_id":   arxiv_id,
            "title":      meta.get("title", "（元数据获取失败）"),
            "authors":    meta.get("authors", []),
            "level":      level,
            "weight":     LEVELS[level]["weight"],
            "note":       note,
            "abs_url":    f"https://arxiv.org/abs/{arxiv_id}",
            "added_at":   now,
            "updated_at": now,
        }
        self._seeds[arxiv_id] = record
        self._save()
        logger.info(f"  [Seed] 已添加 [Lv{level}] {record['title'][:60]}")
        return {"status": "added", **record}

    def remove(self, arxiv_id: str) -> bool:
        """删除一条种子记录"""
        arxiv_id = _parse_arxiv_id(arxiv_id) or arxiv_id
        if arxiv_id in self._seeds:
            del self._seeds[arxiv_id]
            self._save()
            return True
        return False

    def all_seeds(self) -> list[dict]:
        """返回全部种子文章，按权重降序排列"""
        return sorted(self._seeds.values(), key=lambda x: -x["weight"])

    def for_prompt(self) -> str:
        """
        将种子文章格式化为 prompt 文本，供 KeywordEvolver 使用。
        高权重文章会被重复列出以增强影响力。
        """
        lines = []
        for s in self.all_seeds():
            level    = s["level"]
            emoji    = LEVELS[level]["emoji"]
            repeats  = level  # Lv1=出现1次, Lv2=出现2次, Lv3=出现3次
            note_str = f"（备注：{s['note']}）" if s.get("note") else ""
            for _ in range(repeats):
                lines.append(f"{emoji} [种子Lv{level}] {s['title']}{note_str}")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._seeds)

    # ── 私有方法 ──────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.seeds_file):
            try:
                with open(self.seeds_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._seeds = {r["arxiv_id"]: r for r in data if "arxiv_id" in r}
                elif isinstance(data, dict):
                    self._seeds = data
            except Exception as e:
                logger.warning(f"  [Seed] 加载失败，将重建: {e}")
                self._seeds = {}

    def _save(self):
        with open(self.seeds_file, "w", encoding="utf-8") as f:
            json.dump(self._seeds, f, ensure_ascii=False, indent=2)
