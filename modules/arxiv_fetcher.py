"""
arxiv_fetcher.py — arXiv 检索模块（分页去重 + 关键词扩展补充版）

完整流程：

  第一轮：主检索
  ─────────────────────────────────────────────────────────────
  对每个关键词滚动分页，直到凑满 max_results 篇新论文，
  或 arXiv 已无更多符合条件的结果为止。

  收集"欠收"的关键词：
    deficit = [(原词, 还差几篇), ...]   ← 实际收到 < max_results

  第二轮：扩展补充（仅当有欠收时触发）
  ─────────────────────────────────────────────────────────────
  批量请求 AI：对每个欠收关键词生成 K 个扩展词
    策略 A（多词组合）：删掉其中 1~2 个词，得到更宽泛的子查询
    策略 B（近义替换）：同义词/上位词替换某个核心词
  用扩展词补充检索，每个扩展词只补"还差的量"，凑满即停

  AI 调用是一次批量请求，返回所有扩展词，不是逐个调用。
"""

import json
import re
import time
import logging
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

NS = {
    "atom":       "http://www.w3.org/2005/Atom",
    "arxiv":      "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

ARXIV_API_URL = "http://export.arxiv.org/api/query"
PAGE_SIZE      = 25
MAX_EMPTY_PAGES = 2

# 每个欠收关键词最多生成几个扩展词
EXPANSIONS_PER_QUERY = 3


class ArxivFetcher:
    """arXiv 检索：分页去重 + AI 关键词扩展补充"""

    def __init__(self, arxiv_config: dict, ai_config: dict | None = None):
        raw_queries = arxiv_config.get("queries", [])
        self.queries = [
            q["query"] if isinstance(q, dict) else q
            for q in raw_queries
        ]
        self.categories    = arxiv_config.get("categories", [])
        self.max_results   = arxiv_config.get("max_results_per_query", 5)
        self.days_lookback = arxiv_config.get("days_lookback", 7)

        # AI 配置（可选；不传则跳过扩展步骤）
        self._ai = ai_config  # dict 含 api_key / base_url / model，或 None

    # ── 公开接口 ──────────────────────────────────────────────

    def fetch(self, history_ids: set[str] | None = None) -> list[dict]:
        """
        执行全部查询，返回跨查询去重后的论文列表。

        Args:
            history_ids: 已处理过的 arXiv ID 集合，翻页时实时过滤。
        """
        history_ids = history_ids or set()
        seen_ids: dict[str, dict] = {}   # arxiv_id → paper

        # ── 第一轮：主检索 ────────────────────────────────────
        deficit: list[tuple[str, int]] = []   # (原词, 还差几篇)

        for query in self.queries:
            logger.info(f"  检索关键词: [{query}]")
            try:
                papers = self._fetch_until_full(query, history_ids, seen_ids,
                                                self.max_results)
                added = self._merge(papers, seen_ids)
                gap   = self.max_results - added
                logger.info(f"    → 新增 {added} 篇（累计 {len(seen_ids)} 篇）"
                            + (f"，欠收 {gap} 篇" if gap > 0 else ""))
                if gap > 0:
                    deficit.append((query, gap))
                time.sleep(1)
            except Exception as e:
                logger.error(f"    → 检索失败: {e}")

        # ── 第二轮：扩展补充 ──────────────────────────────────
        if deficit and self._ai:
            logger.info(f"  [扩展] {len(deficit)} 个关键词欠收，启动 AI 扩展...")
            self._fetch_with_expansion(deficit, history_ids, seen_ids)
        elif deficit:
            logger.info(f"  [扩展] {len(deficit)} 个关键词欠收，但未配置 AI，跳过扩展")

        return list(seen_ids.values())

    # ── 扩展补充 ──────────────────────────────────────────────

    def _fetch_with_expansion(
        self,
        deficit:     list[tuple[str, int]],
        history_ids: set[str],
        seen_ids:    dict[str, dict],
    ):
        """对所有欠收关键词批量请求 AI 扩展词，然后补充检索。"""

        # 一次 AI 调用，获取所有扩展词
        expansion_map = self._ai_expand_queries(deficit)

        for original_query, gap in deficit:
            expansions = expansion_map.get(original_query, [])
            if not expansions:
                logger.info(f"    [扩展] [{original_query}] 未获得扩展词，跳过")
                continue

            remaining = gap  # 还需要补几篇
            logger.info(f"    [扩展] [{original_query}] "
                        f"扩展词: {expansions}，需补 {remaining} 篇")

            for exp_query in expansions:
                if remaining <= 0:
                    break
                logger.info(f"      → 使用扩展词 [{exp_query}] 补充检索")
                try:
                    papers = self._fetch_until_full(exp_query, history_ids,
                                                    seen_ids, remaining)
                    added = self._merge(papers, seen_ids)
                    remaining -= added
                    logger.info(f"        补充 {added} 篇，还差 {remaining} 篇")
                    time.sleep(1)
                except Exception as e:
                    logger.warning(f"        扩展词检索失败: {e}")

    def _ai_expand_queries(
        self,
        deficit: list[tuple[str, int]],
    ) -> dict[str, list[str]]:
        """
        一次 AI 调用，为所有欠收关键词批量生成扩展词。
        返回 {原词: [扩展词1, 扩展词2, ...]} 的字典。
        """
        queries_text = "\n".join(
            f'  - "{q}" （欠收 {gap} 篇）' for q, gap in deficit
        )

        prompt = f"""你是一位学术文献检索专家，帮助用户扩展 arXiv 搜索词以找到更多相关文章。

以下关键词在 arXiv 上搜索后结果不足（在限定时间范围内没有足够的新文章）：
{queries_text}

请为每个关键词生成 {EXPANSIONS_PER_QUERY} 个扩展搜索词，按以下两种策略操作：
  策略 A（化繁为简）：原词是多个词的组合时，删掉其中 1~2 个限定词，
    得到覆盖范围更广的子查询。例如 "chain-of-thought reasoning in math" → "chain-of-thought reasoning"
  策略 B（近义替换）：替换其中一个核心词为同义词、上位词或相关技术词。
    例如 "reinforcement learning from human feedback" → "preference learning language model"

要求：
1. 扩展词必须是英文，可直接用于 arXiv 全文搜索
2. 与原词有明确的语义关联，不能偏离原有研究方向
3. 不要重复原词本身
4. 仅输出一个 JSON 对象，key 为原词，value 为扩展词数组，不含其他文字：
{{
  "原词1": ["扩展词A", "扩展词B", "扩展词C"],
  "原词2": ["扩展词A", "扩展词B", "扩展词C"]
}}"""

        cfg     = self._ai
        url     = cfg["base_url"].rstrip("/") + "/chat/completions"
        payload = {
            "model":       cfg["model"],
            "temperature": 0.3,
            "max_tokens":  600,
            "messages":    [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {cfg['api_key']}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            content = result["choices"][0]["message"]["content"].strip()

            # 去除 markdown 代码块
            content = re.sub(r"```[a-z]*\n?|```", "", content).strip()
            s = content.find("{")
            e = content.rfind("}") + 1
            if s >= 0 and e > s:
                raw = json.loads(content[s:e])
                # 规范化：确保每个值是字符串列表，截断到上限
                result_map = {}
                for k, v in raw.items():
                    if isinstance(v, list):
                        result_map[k] = [
                            x.strip() for x in v
                            if isinstance(x, str) and x.strip()
                        ][:EXPANSIONS_PER_QUERY]
                logger.info(f"  [扩展] AI 返回扩展词: {result_map}")
                return result_map
            else:
                logger.warning(f"  [扩展] AI 返回格式异常: {content[:120]}")
                return {}
        except urllib.error.HTTPError as ex:
            logger.error(f"  [扩展] AI API HTTP {ex.code}: {ex.read().decode()[:150]}")
        except Exception as ex:
            logger.error(f"  [扩展] AI 调用失败: {ex}")
        return {}

    # ── 核心：滚动分页 ────────────────────────────────────────

    def _fetch_until_full(
        self,
        query:       str,
        history_ids: set[str],
        seen_ids:    dict[str, dict],
        target:      int,
    ) -> list[dict]:
        """
        对单个关键词滚动翻页，直到收集够 target 篇新论文，
        或 arXiv 已无更多符合条件的结果为止。
        返回本次收集的论文（不写入 seen_ids，由调用方决定是否合并）。
        """
        search_expr    = self._build_search_expr(query)
        cutoff_dt      = self._cutoff()
        collected:     list[dict] = []
        offset         = 0
        empty_pages    = 0
        total_on_arxiv = None

        while len(collected) < target:
            batch, total_on_arxiv = self._api_call(search_expr, offset,
                                                    total_on_arxiv)
            if not batch:
                logger.debug(f"    [分页] offset={offset} 返回空，停止")
                break

            new_in_batch     = 0
            too_old_in_batch = 0

            for paper in batch:
                aid = paper["arxiv_id"]
                if aid in seen_ids or aid in history_ids:
                    continue
                if cutoff_dt and paper.get("published_dt"):
                    if paper["published_dt"] < cutoff_dt:
                        too_old_in_batch += 1
                        continue
                collected.append(paper)
                new_in_batch += 1
                if len(collected) >= target:
                    break

            logger.debug(
                f"    [分页] offset={offset} | 批={len(batch)} | "
                f"新={new_in_batch} | 旧={too_old_in_batch} | "
                f"已收={len(collected)}/{target}"
            )

            if cutoff_dt and too_old_in_batch == len(batch) and new_in_batch == 0:
                logger.debug("    [分页] 全部超出时间窗口，停止")
                break

            if new_in_batch == 0 and too_old_in_batch == 0:
                empty_pages += 1
                if empty_pages >= MAX_EMPTY_PAGES:
                    logger.debug(f"    [分页] 连续 {MAX_EMPTY_PAGES} 页无新内容，停止")
                    break
            else:
                empty_pages = 0

            if total_on_arxiv is not None and offset + PAGE_SIZE >= total_on_arxiv:
                logger.debug(f"    [分页] 到达 arXiv 末尾（总={total_on_arxiv}），停止")
                break

            offset += PAGE_SIZE
            time.sleep(0.5)

        logger.info(
            f"    [分页] [{query}] 翻 {offset // PAGE_SIZE + 1} 页，"
            f"收 {len(collected)}/{target} 篇"
        )
        return collected

    # ── 工具方法 ──────────────────────────────────────────────

    def _merge(self, papers: list[dict], seen_ids: dict[str, dict]) -> int:
        """将 papers 合并到 seen_ids，返回实际新增数量。"""
        added = 0
        for p in papers:
            if p["arxiv_id"] not in seen_ids:
                seen_ids[p["arxiv_id"]] = p
                added += 1
        return added

    def _api_call(
        self,
        search_expr: str,
        start:       int,
        known_total: int | None,
    ) -> tuple[list[dict], int | None]:
        params = {
            "search_query": search_expr,
            "start":        start,
            "max_results":  PAGE_SIZE,
            "sortBy":       "submittedDate",
            "sortOrder":    "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        logger.debug(f"    GET {url}")
        req = urllib.request.Request(
            url, headers={"User-Agent": "AutoPaperBriefing/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()
        return self._parse_xml(xml_data)

    def _parse_xml(self, xml_data: bytes) -> tuple[list[dict], int | None]:
        root      = ET.fromstring(xml_data)
        total_tag = root.find("opensearch:totalResults", NS)
        total     = int(total_tag.text) if total_tag is not None else None
        papers    = []
        for entry in root.findall("atom:entry", NS):
            p = self._parse_entry(entry)
            if p:
                papers.append(p)
        return papers, total

    def _parse_entry(self, entry) -> dict | None:
        try:
            raw_id   = entry.find("atom:id", NS).text.strip()
            arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]
            title    = entry.find("atom:title",   NS).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", NS).text.strip().replace("\n", " ")
            authors  = [
                a.find("atom:name", NS).text.strip()
                for a in entry.findall("atom:author", NS)
                if a.find("atom:name", NS) is not None
            ]
            published_str = entry.find("atom:published", NS).text.strip()
            published_dt  = datetime.fromisoformat(
                published_str.replace("Z", "+00:00"))

            pdf_url = abs_url = None
            for link in entry.findall("atom:link", NS):
                href = link.get("href", "").replace("http://", "https://")
                if link.get("title") == "pdf":
                    pdf_url = href
                elif link.get("rel") == "alternate":
                    abs_url = href

            return {
                "arxiv_id":     arxiv_id,
                "title":        title,
                "authors":      authors,
                "abstract":     abstract,
                "published":    published_str,
                "published_dt": published_dt,
                "pdf_url":      pdf_url or f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "abs_url":      abs_url or f"https://arxiv.org/abs/{arxiv_id}",
                "categories":   [t.get("term","")
                                 for t in entry.findall("atom:category", NS)],
            }
        except Exception as e:
            logger.warning(f"    解析 entry 失败: {e}")
            return None

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
