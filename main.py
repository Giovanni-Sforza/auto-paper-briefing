#!/usr/bin/env python3
"""
Auto-Paper-Briefing v4
用法: python main.py [--config config.yaml] [--evolve-only] [--no-evolve]
"""

import argparse
import sys
import logging
import time
from pathlib import Path

from modules.config_loader   import load_config
from modules.history_manager import HistoryManager
from modules.arxiv_fetcher   import ArxivFetcher
from modules.pdf_processor   import PDFProcessor
from modules.ai_summarizer   import AISummarizer
from modules.report_generator import ReportGenerator
from modules.click_tracker   import ClickTrackerServer
from modules.keyword_evolver import KeywordEvolver


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Auto-Paper-Briefing v4")
    parser.add_argument("--config",      default="config.yaml")
    parser.add_argument("--evolve-only", action="store_true", help="仅进化关键词，不抓论文")
    parser.add_argument("--no-evolve",   action="store_true", help="跳过关键词进化")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  Auto-Paper-Briefing v4 启动")
    logger.info("=" * 60)

    # ── Step 1: 加载配置 ──────────────────────────────────────
    logger.info(f"[Step 1] 加载配置: {args.config}")
    config = load_config(args.config)
    paths  = config["paths"]
    port   = config.get("click_tracking", {}).get("port", 19523)

    # ── Step 2: 启动统一事件追踪服务 ─────────────────────────
    logger.info("[Step 2] 启动事件追踪服务...")
    tracker = ClickTrackerServer(
        clicks_file = paths.get("clicks_file", "./clicks.json"),
        reactions_file = paths.get("reactions_file", "./reactions.json"),
        seeds_file  = paths.get("seeds_file",  "./seeds.json"),
        port        = port,
    )
    tracker.start()

    # ── Step 3: 关键词进化 ────────────────────────────────────
    if not args.no_evolve:
        logger.info("[Step 3] 检查关键词进化条件...")
        evolver = KeywordEvolver(config, args.config)
        if evolver.should_evolve():
            evolver.evolve()
            config = load_config(args.config)
        else:
            logger.info("  暂不满足条件，跳过")
    else:
        logger.info("[Step 3] 已跳过（--no-evolve）")

    if args.evolve_only:
        logger.info("  --evolve-only 完成，退出")
        tracker.stop()
        return

    # ── Step 4: 历史记录 & 检索 ──────────────────────────────
    logger.info("[Step 4] 加载历史处理记录...")
    history = HistoryManager(paths["history_file"])
    logger.info(f"  已处理 {history.count()} 篇")

    logger.info("[Step 5] 向 arXiv 检索（分页去重模式）...")
    history_ids = set(history._records.keys())  # 传给 fetcher，翻页时实时过滤
    new_papers  = ArxivFetcher(config["arxiv"], ai_config=config["ai"]).fetch(history_ids=history_ids)
    logger.info(f"  检索完成，共 {len(new_papers)} 篇新论文")

    gen         = ReportGenerator(config)
    report_path = None

    if not new_papers:
        logger.info("  无新论文，跳过处理")
    else:
        # ── Step 5: 逐篇处理 ──────────────────────────────────
        pdf_proc   = PDFProcessor(config)
        summarizer = AISummarizer(config)
        processed  = []

        for idx, paper in enumerate(new_papers, 1):
            logger.info("-" * 50)
            logger.info(f"[{idx}/{len(new_papers)}] {paper['title'][:72]}...")
            pdf_path = None
            try:
                logger.info("  → 下载 PDF...")
                pdf_path = pdf_proc.download(paper)
                logger.info("  → 提取文本...")
                text = pdf_proc.extract_text(pdf_path)
                logger.info("  → AI 总结...")
                paper["summary"] = summarizer.summarize(paper, text)
                processed.append(paper)
                history.add(paper)
                logger.info("  ✓ 完成")
            except Exception as e:
                logger.error(f"  ✗ 失败: {e}")
                paper["summary"] = {"error": str(e)}
                processed.append(paper)
            finally:
                if pdf_path and Path(pdf_path).exists():
                    Path(pdf_path).unlink()
                    logger.info("  → PDF 已删除（阅后即焚）")

        # ── Step 6: 生成每日简报 ──────────────────────────────
        logger.info("[Step 6] 生成 HTML 简报...")
        report_path = gen.generate(processed)
        logger.info(f"  ✓ {report_path}")
        history.save()
        logger.info(f"  历史记录已保存，共 {history.count()} 篇")

    # ── Step 7: 确保点赞历史页存在（常驻，只生成一次）────────
    logger.info("[Step 7] 确保反应历史页存在...")
    likes_path = gen.generate_reactions_history()
    logger.info(f"  ✓ {likes_path}")

    # ── 完成，保持运行 ────────────────────────────────────────
    logger.info("=" * 60)
    if report_path:
        logger.info(f"  ✓ 每日简报:   {report_path}")
    logger.info(f"  ✓ 反应历史:   {likes_path}（纯前端，实时更新）")
    logger.info(f"  ✓ 种子管理:   http://127.0.0.1:{port}/")
    logger.info(f"  ✓ 追踪服务:   端口 {port}，Ctrl+C 停止")
    logger.info("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("  正在停止…")
        tracker.stop()
        logger.info("  已退出。")


if __name__ == "__main__":
    main()
