#!/usr/bin/env python3
"""
migrate_likes.py — 将旧版 likes.json 迁移为新版 reactions.json

旧格式（列表）：
  [
    { "arxiv_id": "...", "title": "...", "authors": [...],
      "abs_url": "...", "liked_at": "...", "summary_snippet": "..." },
    ...
  ]

新格式（字典）：
  {
    "2401.12345": {
      "arxiv_id": "...", "title": "...", "authors": [...],
      "abs_url": "...", "reaction": "like", "comment": "",
      "summary_snippet": "...", "reacted_at": "...", "updated_at": "...",
      "report_date": ""
    },
    ...
  }

用法：
  python migrate_likes.py                        # 使用默认路径
  python migrate_likes.py --likes path/to/likes.json --reactions path/to/reactions.json
"""

import argparse
import json
import os
import shutil
from datetime import datetime


def migrate(likes_path: str, reactions_path: str):
    # ── 检查源文件 ────────────────────────────────────────────
    if not os.path.exists(likes_path):
        print(f"❌ 未找到 likes.json：{likes_path}")
        print("   如果你从未使用过旧版，不需要迁移，直接运行新版即可。")
        return

    with open(likes_path, "r", encoding="utf-8") as f:
        likes = json.load(f)

    if not isinstance(likes, list):
        print(f"❌ likes.json 格式异常（期望列表，实际是 {type(likes).__name__}），跳过迁移。")
        return

    print(f"✓ 读取 likes.json：共 {len(likes)} 条记录")

    # ── 读取已有 reactions.json（如果存在，做合并）─────────────
    existing_reactions = {}
    if os.path.exists(reactions_path):
        with open(reactions_path, "r", encoding="utf-8") as f:
            existing_reactions = json.load(f)
        print(f"  reactions.json 已存在，包含 {len(existing_reactions)} 条，将合并（不覆盖已有条目）")

    # ── 迁移 ─────────────────────────────────────────────────
    converted = 0
    skipped   = 0
    now       = datetime.now().isoformat()

    for item in likes:
        arxiv_id = item.get("arxiv_id", "").strip()
        if not arxiv_id:
            skipped += 1
            continue

        # 已在 reactions.json 中存在的不覆盖
        if arxiv_id in existing_reactions:
            skipped += 1
            continue

        # liked_at 字段名在新版里叫 reacted_at
        liked_at = item.get("liked_at") or item.get("reacted_at") or now

        existing_reactions[arxiv_id] = {
            "arxiv_id":        arxiv_id,
            "title":           item.get("title", ""),
            "authors":         item.get("authors", []),
            "abs_url":         item.get("abs_url",
                                        f"https://arxiv.org/abs/{arxiv_id}"),
            "reaction":        "like",   # 原来在 likes.json 的全部是点赞
            "comment":         "",       # 旧版没有评论字段
            "summary_snippet": item.get("summary_snippet", ""),
            "reacted_at":      liked_at,
            "updated_at":      liked_at,
            "report_date":     item.get("report_date", ""),
        }
        converted += 1

    # ── 写出 ─────────────────────────────────────────────────
    # 备份旧 likes.json
    backup_path = likes_path + ".bak"
    shutil.copy2(likes_path, backup_path)
    print(f"  likes.json 已备份至：{backup_path}")

    with open(reactions_path, "w", encoding="utf-8") as f:
        json.dump(existing_reactions, f, ensure_ascii=False, indent=2)

    # ── 结果 ─────────────────────────────────────────────────
    print(f"\n✅ 迁移完成")
    print(f"   新增转换：{converted} 条")
    print(f"   跳过（已存在或无效）：{skipped} 条")
    print(f"   reactions.json 共：{len(existing_reactions)} 条")
    print(f"   输出路径：{reactions_path}")


def main():
    parser = argparse.ArgumentParser(description="likes.json → reactions.json 迁移工具")
    parser.add_argument("--likes",     default="./likes.json",
                        help="旧版 likes.json 路径（默认：./likes.json）")
    parser.add_argument("--reactions", default="./reactions.json",
                        help="新版 reactions.json 路径（默认：./reactions.json）")
    args = parser.parse_args()

    migrate(args.likes, args.reactions)


if __name__ == "__main__":
    main()
