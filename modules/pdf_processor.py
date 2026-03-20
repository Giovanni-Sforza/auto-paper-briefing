"""
pdf_processor.py — PDF 下载与文本提取模块
下载论文 PDF 到临时目录，提取文本后立即标记可删除
"""

import os
import time
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class PDFProcessor:
    """负责 PDF 的下载与文本提取"""

    def __init__(self, config: dict):
        self.temp_dir = config["paths"]["temp_pdf_dir"]
        self.max_pages = config["performance"]["max_pdf_pages"]
        self.max_chars = config["performance"]["max_text_chars"]
        self.max_retries = config["performance"]["max_retries"]
        self.retry_delay = config["performance"]["retry_delay"]
        os.makedirs(self.temp_dir, exist_ok=True)

    def download(self, paper: dict) -> str:
        """
        下载论文 PDF 到临时目录
        返回本地文件路径
        """
        arxiv_id = paper["arxiv_id"].replace("/", "_")
        pdf_path = os.path.join(self.temp_dir, f"{arxiv_id}.pdf")
        pdf_url = paper["pdf_url"]

        headers = {
            "User-Agent": "AutoPaperBriefing/1.0 (academic research tool)",
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(pdf_url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    content = resp.read()

                if len(content) < 1000:
                    raise ValueError(f"下载内容过小（{len(content)} bytes），可能不是有效 PDF")

                with open(pdf_path, "wb") as f:
                    f.write(content)

                logger.debug(f"    PDF 下载完成: {pdf_path} ({len(content)//1024} KB)")
                return pdf_path

            except Exception as e:
                logger.warning(f"    下载失败 (第{attempt}次): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError(f"PDF 下载失败（已重试 {self.max_retries} 次）: {e}")

    def extract_text(self, pdf_path: str) -> str:
        """
        从 PDF 文件提取文本
        优先使用 PyMuPDF (fitz)，降级使用 pdfminer
        """
        text = ""

        # 尝试 PyMuPDF（最佳效果）
        try:
            import fitz  # PyMuPDF
            text = self._extract_with_pymupdf(pdf_path)
            logger.debug(f"    文本提取成功 (PyMuPDF): {len(text)} 字符")
        except ImportError:
            logger.debug("    PyMuPDF 未安装，尝试 pdfminer...")
            # 降级到 pdfminer
            try:
                text = self._extract_with_pdfminer(pdf_path)
                logger.debug(f"    文本提取成功 (pdfminer): {len(text)} 字符")
            except ImportError:
                logger.warning("    pdfminer 也未安装，使用基础提取...")
                text = self._extract_basic(pdf_path)

        # 清理文本
        text = self._clean_text(text)

        # 截断到最大字符数
        if len(text) > self.max_chars:
            text = text[:self.max_chars] + "\n\n[... 文本已截断，仅保留前段内容 ...]"
            logger.debug(f"    文本已截断至 {self.max_chars} 字符")

        return text

    def _extract_with_pymupdf(self, pdf_path: str) -> str:
        """使用 PyMuPDF 提取文本"""
        import fitz
        doc = fitz.open(pdf_path)
        pages_to_read = min(self.max_pages, len(doc))
        texts = []
        for page_num in range(pages_to_read):
            page = doc[page_num]
            texts.append(page.get_text())
        doc.close()
        return "\n".join(texts)

    def _extract_with_pdfminer(self, pdf_path: str) -> str:
        """使用 pdfminer 提取文本"""
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        import io

        output = io.StringIO()
        with open(pdf_path, "rb") as f:
            extract_text_to_fp(f, output, laparams=LAParams(), page_numbers=list(range(self.max_pages)))
        return output.getvalue()

    def _extract_basic(self, pdf_path: str) -> str:
        """最基础的文本提取（无依赖）"""
        with open(pdf_path, "rb") as f:
            data = f.read()
        # 简单提取可打印字符
        text = data.decode("latin-1", errors="ignore")
        import re
        text = re.sub(r'[^\x20-\x7E\n]', ' ', text)
        text = re.sub(r' {3,}', ' ', text)
        return text[:self.max_chars]

    def _clean_text(self, text: str) -> str:
        """清理提取的文本：去除多余空白、控制字符等"""
        import re
        # 合并多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 去除行首行尾空白
        lines = [line.strip() for line in text.splitlines()]
        # 过滤纯符号行（通常是页眉页脚）
        lines = [l for l in lines if len(l) > 2 or l == ""]
        return "\n".join(lines).strip()
