#!/usr/bin/env python3
"""
Auto-Paper-Briefing v5
用法: python main.py [--config config.yaml] [--evolve-only] [--no-evolve] [--no-setup-prompt]
"""

# ── SSL 证书修复（PyInstaller 打包后 macOS 常见问题）────────────
# 必须在任何 urllib / http 调用之前执行
import os as _os
import ssl as _ssl

def _patch_ssl():
    """
    打包为可执行文件后，macOS 系统 SSL 证书路径与 Python 内置路径不一致。
    优先使用 certifi 提供的 CA bundle；不可用时回退到系统证书。
    直接运行 Python 脚本时此函数基本无副作用。
    """
    try:
        import certifi
        cert_path = certifi.where()
        _os.environ.setdefault("SSL_CERT_FILE", cert_path)
        _os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_path)
        # 同时替换默认 SSL context，覆盖 urllib 的全局行为
        _ssl._create_default_https_context = (
            lambda: _ssl.create_default_context(cafile=cert_path)
        )
    except ImportError:
        # certifi 未安装时，尝试 macOS 系统证书路径
        system_cert = "/etc/ssl/cert.pem"          # macOS / Linux
        if not _os.path.exists(system_cert):
            system_cert = "/etc/ssl/certs/ca-certificates.crt"   # Ubuntu
        if _os.path.exists(system_cert):
            _os.environ.setdefault("SSL_CERT_FILE", system_cert)

_patch_ssl()

# ── 工作目录修复（PyInstaller 打包后双击运行时 cwd 是用户主目录）──
# 必须在加载 config.yaml 之前执行，确保所有相对路径基于程序所在目录
def _fix_workdir():
    import sys as _sys, os as _os
    if getattr(_sys, "frozen", False):
        # PyInstaller 打包模式：切换到可执行文件所在目录
        app_dir = _os.path.dirname(_sys.executable)
    else:
        # 直接运行 Python 脚本：切换到脚本所在目录
        app_dir = _os.path.dirname(_os.path.abspath(__file__))
    _os.chdir(app_dir)

_fix_workdir()

import argparse
import sys
import os
import logging
import time
import subprocess
import threading
from pathlib import Path

from modules.config_loader   import load_config
from modules.history_manager import HistoryManager
from modules.arxiv_fetcher   import ArxivFetcher
from modules.pdf_processor   import PDFProcessor
from modules.ai_summarizer   import AISummarizer
from modules.report_generator import ReportGenerator
from modules.click_tracker   import ClickTrackerServer
from modules.keyword_evolver import KeywordEvolver


# ── 进度条 ────────────────────────────────────────────────────

class ProgressBar:
    """
    纯标准库终端进度条，支持预计剩余时间。
    不依赖 tqdm，Windows / macOS / Linux 均可用。
    """

    def __init__(self, total: int, width: int = 40):
        self.total     = total
        self.width     = width
        self.current   = 0
        self.start_time = time.time()
        self._lock     = threading.Lock()

    def update(self, step_title: str = ""):
        with self._lock:
            self.current += 1
            self._render(step_title)

    def _render(self, step_title: str):
        pct      = self.current / max(self.total, 1)
        filled   = int(self.width * pct)
        bar      = "█" * filled + "░" * (self.width - filled)
        elapsed  = time.time() - self.start_time
        eta_str  = ""
        if self.current > 0:
            eta_sec = elapsed / self.current * (self.total - self.current)
            if eta_sec < 60:
                eta_str = f"剩余约 {int(eta_sec)}s"
            else:
                eta_str = f"剩余约 {int(eta_sec/60)}m{int(eta_sec%60)}s"

        title_short = step_title[:35] + "…" if len(step_title) > 36 else step_title
        line = (f"\r  [{bar}] {self.current}/{self.total}"
                f"  {pct*100:5.1f}%  {eta_str}"
                f"  {title_short}")

        # 清行并写出（不换行，下一次 update 覆盖）
        sys.stdout.write(line.ljust(120)[:120])
        sys.stdout.flush()

        if self.current >= self.total:
            elapsed_fmt = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
            sys.stdout.write(f"\r  ✓ 全部 {self.total} 篇处理完毕，耗时 {elapsed_fmt}" + " " * 40 + "\n")
            sys.stdout.flush()


# ── Setup 向导集成 ────────────────────────────────────────────

def maybe_run_setup(config_path: str, force: bool = False) -> bool:
    """
    询问用户是否重新配置。
    - 若 config.yaml 不存在：强制运行向导
    - 若存在：询问 Y/N（--no-setup-prompt 时跳过）
    返回：是否重新运行了向导（用于决定是否重载配置）
    """
    if not os.path.exists(config_path):
        print(f"\n  [初始化] 未找到 {config_path}，启动配置向导…\n")
        _launch_setup(config_path)
        return True

    if force:
        _launch_setup(config_path)
        return True

    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │        Auto-Paper-Briefing v5 启动              │")
    print("  └─────────────────────────────────────────────────┘")
    print()
    print("  是否重新配置 API / 关键词 / 分类？（历史记录和种子文章不受影响）")
    print("  [Y] 打开配置向导    [N/Enter] 直接运行（默认）")
    print()
    try:
        answer = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer in ("y", "yes"):
        _launch_setup(config_path)
        return True
    return False


def _launch_setup(config_path: str):
    """
    启动 setup.py 向导进程，等待其退出。
    向导只会覆写 config.yaml，不碰数据文件。
    """
    setup_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.py")
    if not os.path.exists(setup_script):
        print("  [警告] 未找到 setup.py，跳过向导")
        return
    print()
    cmd = [sys.executable, setup_script, "--config", config_path]
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print(f"  [警告] 向导运行失败: {e}")
    print()


# ── 日志 ─────────────────────────────────────────────────────

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ── 主程序 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-Paper-Briefing v5")
    parser.add_argument("--config",           default="config.yaml")
    parser.add_argument("--evolve-only",      action="store_true", help="仅进化关键词，不抓论文")
    parser.add_argument("--no-evolve",        action="store_true", help="跳过关键词进化")
    parser.add_argument("--no-setup-prompt",  action="store_true", help="跳过启动时的配置询问")
    parser.add_argument("--setup",            action="store_true", help="强制打开配置向导")
    args = parser.parse_args()

    # ── Step 0: 配置向导（启动询问）─────────────────────────────
    # ran_setup=True 表示本次重新运行了向导，本次跳过关键词进化
    if not args.no_setup_prompt:
        ran_setup = maybe_run_setup(args.config, force=args.setup)
    elif args.setup:
        _launch_setup(args.config)
        ran_setup = True
    else:
        ran_setup = False

    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  Auto-Paper-Briefing v5 启动")
    logger.info("=" * 60)

    # ── Step 1: 加载配置 ──────────────────────────────────────
    logger.info(f"[Step 1] 加载配置: {args.config}")
    config = load_config(args.config)
    paths  = config["paths"]
    port   = config.get("click_tracking", {}).get("port", 19523)

    # ── Step 2: 启动事件追踪服务 ──────────────────────────────
    logger.info("[Step 2] 启动事件追踪服务...")
    tracker = ClickTrackerServer(
        clicks_file    = paths.get("clicks_file",    "./clicks.json"),
        reactions_file = paths.get("reactions_file", "./reactions.json"),
        seeds_file     = paths.get("seeds_file",     "./seeds.json"),
        history_file   = paths.get("history_file",   "./history.json"),
        port           = port,
    )
    tracker.start()

    # ── Step 3: 关键词进化 ────────────────────────────────────
    # 本次运行了 setup 向导时跳过进化：用户已手动指定关键词，
    # 直接使用向导写入的 config.yaml，不与历史信号混合。
    if ran_setup:
        logger.info("[Step 3] 本次已运行配置向导，跳过关键词进化（使用向导设定的关键词）")
    elif args.no_evolve:
        logger.info("[Step 3] 已跳过（--no-evolve）")
    else:
        logger.info("[Step 3] 检查关键词进化条件...")
        evolver = KeywordEvolver(config, args.config)
        if evolver.should_evolve():
            evolver.evolve()
            config = load_config(args.config)
        else:
            logger.info("  暂不满足条件，跳过")

    if args.evolve_only:
        logger.info("  --evolve-only 完成，退出")
        tracker.stop()
        return

    # ── Step 4: 历史记录 ──────────────────────────────────────
    logger.info("[Step 4] 加载历史处理记录...")
    history = HistoryManager(paths["history_file"])
    logger.info(f"  已处理 {history.count()} 篇")

    # ── Step 5: 检索 ──────────────────────────────────────────
    logger.info("[Step 5] 向 arXiv 检索（分页去重模式）...")
    history_ids = set(history._records.keys())
    new_papers  = ArxivFetcher(config["arxiv"], ai_config=config["ai"]).fetch(
                      history_ids=history_ids)
    logger.info(f"  检索完成，共 {len(new_papers)} 篇新论文")

    gen         = ReportGenerator(config)
    report_path = None

    if not new_papers:
        logger.info("  无新论文，跳过处理")
    else:
        # ── Step 6: 逐篇处理（带进度条）─────────────────────
        logger.info(f"[Step 6] 开始处理 {len(new_papers)} 篇论文...")
        pdf_proc   = PDFProcessor(config)
        summarizer = AISummarizer(config)
        processed  = []
        progress   = ProgressBar(total=len(new_papers))

        for idx, paper in enumerate(new_papers, 1):
            title_short = paper['title'][:55]
            # 进度条显示当前正在处理的标题（在 logger 输出前更新）
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

            # 更新进度条（每篇完成后）
            progress.update(title_short)

        # ── Step 7: 生成每日简报 ──────────────────────────────
        logger.info("[Step 7] 生成 HTML 简报...")
        report_path = gen.generate(processed)
        logger.info(f"  ✓ {report_path}")
        history.save()
        logger.info(f"  历史记录已保存，共 {history.count()} 篇")

    # ── Step 8: 确保反应历史页存在 ────────────────────────────
    logger.info("[Step 8] 确保反应历史页存在...")
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
