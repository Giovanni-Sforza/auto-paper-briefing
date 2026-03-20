"""
config_loader.py — 配置文件加载模块
支持 YAML 格式，自动从环境变量读取 API Key
"""

import os
import sys
import logging
import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """加载并校验配置文件，返回配置字典"""
    if not os.path.exists(config_path):
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # ── 自动从环境变量读取 API Key ─────────────────────────────
    api_key = config.get("ai", {}).get("api_key", "").strip()
    if not api_key:
        api_key = os.environ.get("AI_API_KEY", "").strip()
        if api_key:
            config["ai"]["api_key"] = api_key
            logger.info("  API Key 已从环境变量 AI_API_KEY 读取")
        else:
            logger.error("未找到 API Key！请在 config.yaml 中设置 ai.api_key，或设置环境变量 AI_API_KEY")
            sys.exit(1)

    # ── 确保必要目录存在 ───────────────────────────────────────
    for dir_key in ["temp_pdf_dir", "output_dir"]:
        dir_path = config["paths"].get(dir_key, ".")
        os.makedirs(dir_path, exist_ok=True)

    logger.info(f"  配置加载成功 | 模型: {config['ai']['model']} | "
                f"查询数: {len(config['arxiv']['queries'])}")
    return config
