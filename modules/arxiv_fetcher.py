"""
arxiv_fetcher.py — arXiv 检索模块（分页去重版）

解决问题：
  arXiv API 每次从 start=0 开始返回固定顺序的论文。
  当 history.json 中已有大量记录时，取回的前 N 篇大多是旧文章，
  导致去重后实际新论文数量远低于 max_results。

解决方案：滚动分页，直到凑满 max_results 篇「历史中没有」的新论文为止。

  每批拉取 PAGE_SIZE 篇
      ↓
  过滤：已在 seen_ids（本次跨关键词去重）或 history_ids（历史去重）中 → 丢弃
      ↓
  过滤：超出 days_lookback 时间窗口 → 丢弃，且标记「触底」（按时间降序，后续只会更旧）
      ↓
  积累到 max_results 篇，或 arXiv 真的没有更多结果 → 停止
"""

import time
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "arxiv":  "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

ARXIV_API_URL = "http://export.arxiv.org/api/query"

# 每次向 arXiv 请求的批次大小。
# 不宜过大（arXiv 建议单次 ≤ 100），不宜过小（请求次数多、慢）。
PAGE_SIZE = 25

# 连续拉取到的论文全部超出时间窗口后停止翻页（时间序降序，后面只会更旧）
MAX_EMPTY_PAGES = 2


class ArxivFetcher:
    """通过 arXiv 官方 API 检索论文，分页直到凑满新论文"""

    def __init__(self, arxiv_config: dict):
        # 支持 query 既可以是纯字符串，也可以是 {query: "...", pin: true} 字典
        raw_queries = arxiv_config.get("queries", [])
        self.queries = [
            q["query"] if isinstance(q, dict) else q
            for q in raw_queries
        ]
        self.categories   = arxiv_config.get("categories", [])
        self.max_results  = arxiv_config.get("max_results_per_query", 5)
        self.days_lookback = arxiv_config.get("days_lookback", 7)

    # ── 公开接口 ──────────────────────────────────────────────

    def fetch(self, history_ids: set[str] | None = None) -> list[dict]:
        """
        执行所有配置的查询，返回跨查询去重后的论文列表。

        Args:
            history_ids: 已处理过的 arXiv ID 集合（来自 HistoryManager）。
                         传入后会在翻页循环中实时过滤，确保凑满的都是真正的新论文。
                         不传则只做跨关键词去重，不排除历史记录。
        """
        history_ids  = history_ids or set()
        seen_ids: dict[str, dict] = {}   # arxiv_id → paper，跨关键词去重

        for raw_q in self.queries:
            query = raw_q["query"] if isinstance(raw_q, dict) else raw_q
            logger.info(f"  检索关键词: [{query}]")
            try:
                papers = self._fetch_until_full(query, history_ids, seen_ids)
                added  = 0
                for p in papers:
                    if p["arxiv_id"] not in seen_ids:
                        seen_ids[p["arxiv_id"]] = p
                        added += 1
                logger.info(f"    → 本关键词新增 {added} 篇（累计 {len(seen_ids)} 篇）")
                time.sleep(1)  # arXiv 礼貌间隔
            except Exception as e:
                logger.error(f"    → 检索失败: {e}")

        return list(seen_ids.values())

    # ── 核心：滚动分页 ────────────────────────────────────────

    def _fetch_until_full(
        self,
        query:       str,
        history_ids: set[str],
        seen_ids:    dict[str, dict],
    ) -> list[dict]:
        """
        对单个关键词滚动翻页，直到收集够 max_results 篇新论文，
        或 arXiv 确实没有更多符合条件的结果为止。
        """
        search_expr = self._build_search_expr(query)
        cutoff_dt   = self._cutoff()

        collected:    list[dict] = []   # 本关键词收集到的新论文
        offset        = 0
        empty_pages   = 0               # 连续"无新内容"页计数
        total_on_arxiv = None           # arXiv 报告的总结果数（首次请求后获取）

        while len(collected) < self.max_results:
            batch, total_on_arxiv = self._api_call(search_expr, offset, total_on_arxiv)

            if not batch:
                logger.debug(f"    [分页] offset={offset} 返回空，停止")
                break

            new_in_batch    = 0
            too_old_in_batch = 0

            for paper in batch:
                aid = paper["arxiv_id"]

                # 跨关键词去重 + 历史去重
                if aid in seen_ids or aid in history_ids:
                    continue

                # 时间窗口过滤
                if cutoff_dt and paper.get("published_dt"):
                    if paper["published_dt"] < cutoff_dt:
                        too_old_in_batch += 1
                        continue

                collected.append(paper)
                new_in_batch += 1

                if len(collected) >= self.max_results:
                    break

            logger.debug(
                f"    [分页] offset={offset} | 批次={len(batch)} | "
                f"新增={new_in_batch} | 过旧={too_old_in_batch} | "
                f"已收={len(collected)}/{self.max_results}"
            )

            # 判断是否触底：整批论文都超出时间窗口
            if cutoff_dt and too_old_in_batch == len(batch) and new_in_batch == 0:
                logger.debug("    [分页] 论文已全部超出时间窗口，停止翻页")
                break

            # 判断空页（批次中没有任何新论文，且不是时间原因）
            if new_in_batch == 0 and too_old_in_batch == 0:
                empty_pages += 1
                if empty_pages >= MAX_EMPTY_PAGES:
                    logger.debug(f"    [分页] 连续 {MAX_EMPTY_PAGES} 页无新内容，停止")
                    break
            else:
                empty_pages = 0

            # arXiv 总结果数检查
            if total_on_arxiv is not None and offset + PAGE_SIZE >= total_on_arxiv:
                logger.debug(f"    [分页] 已到达 arXiv 结果末尾（总={total_on_arxiv}），停止")
                break

            offset += PAGE_SIZE
            time.sleep(0.5)  # 翻页间礼貌等待

        logger.info(
            f"    [分页] 关键词 [{query}] 共翻 {offset // PAGE_SIZE + 1} 页，"
            f"收集到 {len(collected)} 篇新论文"
        )
        return collected

    # ── API 调用 ──────────────────────────────────────────────

    def _api_call(
        self,
        search_expr:    str,
        start:          int,
        known_total:    int | None,
    ) -> tuple[list[dict], int | None]:
        """
        向 arXiv API 发一次请求，返回 (论文列表, arXiv报告的总数)。
        """
        params = {
            "search_query": search_expr,
            "start":        start,
            "max_results":  PAGE_SIZE,
            "sortBy":       "submittedDate",
            "sortOrder":    "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        logger.debug(f"    GET {url}")

        req = urllib.request.Request(url, headers={"User-Agent": "AutoPaperBriefing/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()

        return self._parse_xml(xml_data)

    # ── XML 解析 ──────────────────────────────────────────────

    def _parse_xml(self, xml_data: bytes) -> tuple[list[dict], int | None]:
        """解析 Atom XML，同时提取 opensearch:totalResults"""
        root      = ET.fromstring(xml_data)
        papers    = []
        total_tag = root.find("opensearch:totalResults", NS)
        total     = int(total_tag.text) if total_tag is not None else None

        for entry in root.findall("atom:entry", NS):
            paper = self._parse_entry(entry)
            if paper:
                papers.append(paper)

        return papers, total

    def _parse_entry(self, entry) -> dict | None:
        try:
            raw_id   = entry.find("atom:id", NS).text.strip()
            arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]

            title    = entry.find("atom:title",   NS).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", NS).text.strip().replace("\n", " ")

            authors = [
                a.find("atom:name", NS).text.strip()
                for a in entry.findall("atom:author", NS)
                if a.find("atom:name", NS) is not None
            ]

            published_str = entry.find("atom:published", NS).text.strip()
            published_dt  = datetime.fromisoformat(published_str.replace("Z", "+00:00"))

            pdf_url = abs_url = None
            for link in entry.findall("atom:link", NS):
                href = link.get("href", "").replace("http://", "https://")
                if link.get("title") == "pdf":
                    pdf_url = href
                elif link.get("rel") == "alternate":
                    abs_url = href

            pdf_url = pdf_url or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            abs_url = abs_url or f"https://arxiv.org/abs/{arxiv_id}"

            categories = [
                tag.get("term", "")
                for tag in entry.findall("atom:category", NS)
            ]

            return {
                "arxiv_id":    arxiv_id,
                "title":       title,
                "authors":     authors,
                "abstract":    abstract,
                "published":   published_str,
                "published_dt": published_dt,
                "pdf_url":     pdf_url,
                "abs_url":     abs_url,
                "categories":  categories,
            }
        except Exception as e:
            logger.warning(f"    解析 entry 失败: {e}")
            return None

    # ── 工具方法 ──────────────────────────────────────────────

    def _build_search_expr(self, query: str) -> str:
        expr = f"all:{query}"
        if self.categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in self.categories)
            expr = f"({expr}) AND ({cat_filter})"
        return expr

    def _cutoff(self) -> datetime | None:
        if self.days_lookback > 0:
            return datetime.now(timezone.utc) - timedelta(days=self.days_lookback)
        return None
