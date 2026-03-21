"""
keyword_evolver.py — 关键词进化模块 v3

四轨信号融合（正向 + 负向）
─────────────────────────────────────────────────────
  正向信号（告诉 AI 我喜欢什么）：
    点击 click      — 被动，weight=1
    点赞 like       — 主动喜爱，weight=2，附带评论时额外加权
    种子 seed       — 手动添加，weight=1/3/6（按等级）

  负向信号（告诉 AI 我不喜欢什么）：
    踩  dislike     — 主动排斥，出现在 prompt 的"排斥方向"区，
                      评论时进一步说明为何不喜欢

精炼轨道（exploit）：正向信号 → AI 提炼核心兴趣关键词
探索轨道（explore）：基于精炼词 → AI 生成相邻领域词（防茧房）
负向约束（reject）：踩的方向 → AI 在两个 prompt 中均受到"避开"约束
"""

import json
import os
import re
import math
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta

import yaml

logger = logging.getLogger(__name__)


class KeywordEvolver:

    def __init__(self, config: dict, config_path: str):
        self.config      = config
        self.config_path = config_path
        paths            = config.get("paths", {})
        self.clicks_file    = paths.get("clicks_file",    "./clicks.json")
        self.reactions_file = paths.get("reactions_file", "./reactions.json")
        self.seeds_file     = paths.get("seeds_file",     "./seeds.json")

        evo = config.get("keyword_evolution", {})
        self.explore_ratio = evo.get("explore_ratio", 0.50)
        self.total_queries = evo.get("total_queries", 8)
        self.lookback_days = evo.get("lookback_days", 30)
        self.min_signals   = evo.get("min_signals_to_evolve", 3)

        self.api_key  = config["ai"]["api_key"]
        self.base_url = config["ai"]["base_url"].rstrip("/")
        self.model    = config["ai"]["model"]

    # ── 公开接口 ──────────────────────────────────────────────

    def should_evolve(self) -> bool:
        signals = self._collect_all_signals()
        total   = (signals["clicks"]["effective_count"]
                   + signals["likes"]["effective_count"]
                   + signals["seeds"]["effective_count"])
        if total < self.min_signals:
            logger.info(f"  [Evolver] 有效正向信号 {total} 条，不足 {self.min_signals}，跳过")
            return False
        return True

    def evolve(self) -> list[str]:
        logger.info("  [Evolver] ── 开始四信号融合分析 ──")
        signals = self._collect_all_signals()
        self._log_signal_summary(signals)

        # 固定关键词
        current   = self.config["arxiv"].get("queries", [])
        pinned    = [q for q in current if isinstance(q, dict) and q.get("pin")]
        pin_texts = [q["query"] for q in pinned]

        available = max(self.total_queries - len(pin_texts), 2)
        exploit_n = max(1, math.floor(available * (1 - self.explore_ratio)))
        explore_n = available - exploit_n
        logger.info(f"  [Evolver] 槽位: 精炼 {exploit_n} + 探索 {explore_n}（固定 {len(pin_texts)}）")

        # 构建正向 + 负向 prompt 文本
        pos_text    = self._build_positive_text(signals)
        neg_text    = self._build_negative_text(signals)
        has_negatives = bool(signals["dislikes"]["items"])

        exploit_kws = self._generate_exploit(pos_text, neg_text, exploit_n, has_negatives)
        logger.info(f"  [Evolver] 精炼: {exploit_kws}")

        explore_kws = self._generate_explore(exploit_kws, neg_text, explore_n, has_negatives)
        logger.info(f"  [Evolver] 探索: {explore_kws}")

        final = pin_texts + exploit_kws + explore_kws
        self._update_config(final, pin_texts, exploit_kws, explore_kws)

        logger.info(f"  [Evolver] ✓ 进化完成，共 {len(final)} 个关键词:")
        for q in final:
            flag = "📌" if q in pin_texts else ("🔍" if q in exploit_kws else "🌐")
            logger.info(f"    {flag} {q}")

        return final

    # ── 信号收集 ──────────────────────────────────────────────

    def _collect_all_signals(self) -> dict:
        cutoff    = datetime.now() - timedelta(days=self.lookback_days)
        clicks    = self._load_list(self.clicks_file)
        recent_clicks = [c for c in clicks if self._is_recent(c.get("clicked_at",""), cutoff)]

        reactions = self._load_dict(self.reactions_file)
        likes     = [r for r in reactions.values() if r.get("reaction") == "like"]
        dislikes  = [r for r in reactions.values() if r.get("reaction") == "dislike"]

        seeds_raw = self._load_dict(self.seeds_file)
        seeds     = list(seeds_raw.values())

        return {
            "clicks":   {"items": recent_clicks, "effective_count": len(recent_clicks)},
            "likes":    {"items": likes,          "effective_count": len(likes)},
            "dislikes": {"items": dislikes,       "effective_count": len(dislikes)},
            "seeds":    {"items": seeds,          "effective_count": len(seeds)},
        }

    # ── Prompt 文本构建 ───────────────────────────────────────

    def _build_positive_text(self, signals: dict) -> str:
        """构建正向信号文本（种子 > 点赞含评论 > 点赞 > 点击）"""
        lines = []

        # 种子（按权重重复出现）
        for s in sorted(signals["seeds"]["items"], key=lambda x: -x.get("weight", 1)):
            lvl    = s.get("level", 1)
            emoji  = {1:"📌",2:"⭐",3:"🔥"}.get(lvl,"📌")
            note   = f"（备注：{s['note']}）" if s.get("note") else ""
            for _ in range(lvl):
                lines.append(f"{emoji} [种子Lv{lvl}] {s.get('title','')}{note}")

        # 点赞（附评论的出现 3 次，无评论出现 2 次）
        for r in signals["likes"]["items"][:30]:
            date    = r.get("reacted_at","")[:10]
            comment = r.get("comment","").strip()
            times   = 3 if comment else 2
            comment_note = f"  用户评论：「{comment}」" if comment else ""
            for _ in range(times):
                lines.append(f"👍 [点赞] {r.get('title','')}{comment_note}（{date}）")

        # 普通点击（出现 1 次）
        for c in signals["clicks"]["items"][:40]:
            action = "摘要" if c.get("action") == "abs" else "PDF"
            date   = c.get("clicked_at","")[:10]
            lines.append(f"🖱️ [点击{action}] {c.get('title','')}（{date}）")

        return "\n".join(lines) if lines else "（暂无正向信号）"

    def _build_negative_text(self, signals: dict) -> str:
        """构建负向信号文本（踩的文章，附用户评论）"""
        if not signals["dislikes"]["items"]:
            return ""
        lines = []
        for r in signals["dislikes"]["items"][:20]:
            comment = r.get("comment","").strip()
            comment_note = f"  用户说：「{comment}」" if comment else ""
            lines.append(f"👎 [踩] {r.get('title','')}{comment_note}")
        return "\n".join(lines)

    # ── AI 生成 ───────────────────────────────────────────────

    def _generate_exploit(self, pos_text: str, neg_text: str,
                          count: int, has_neg: bool) -> list[str]:
        neg_section = f"""
【用户明确不喜欢的方向（请务必避开这些主题/技术路线）】
{neg_text}
""" if has_neg else ""

        prompt = f"""你是一位学术研究助手，从用户的阅读信号中提炼核心研究兴趣。

信号权重说明（从高到低）：
  🔥 [种子Lv3] 核心必读  — 最高权重
  ⭐ [种子Lv2] 重要推荐  — 高权重
  📌 [种子Lv1] 普通种子  — 中等权重
  👍 [点赞]+用户评论      — 强正向信号（评论揭示更精确的兴趣点）
  👍 [点赞]               — 正向信号
  🖱️ [点击]               — 弱正向信号

【用户的正向阅读信号（共 {len(pos_text.splitlines())} 条）】
{pos_text}
{neg_section}
【任务】
综合正向信号，提炼出用户最感兴趣的 {count} 个 arXiv 搜索关键词。
高权重信号影响更大；若有"用户评论"，优先参考评论揭示的具体方向。
{"生成的关键词不得与用户不喜欢的方向重合。" if has_neg else ""}

【输出格式】仅输出 JSON 数组，不含其他文字：["kw1", "kw2"]"""
        return self._call_ai(prompt, count)

    def _generate_explore(self, exploit_kws: list[str], neg_text: str,
                          count: int, has_neg: bool) -> list[str]:
        if not exploit_kws:
            return []
        neg_section = f"""
【用户明确不喜欢的方向（生成的探索词必须避开）】
{neg_text}
""" if has_neg else ""

        prompt = f"""你是一位学术研究助手，帮助用户拓展视野、防止信息茧房。

用户当前核心兴趣：
{json.dumps(exploit_kws, ensure_ascii=False)}
{neg_section}
【任务】
基于核心兴趣，生成 {count} 个「相邻但尚未探索」的 arXiv 搜索关键词。

【要求】
1. 英文，可直接用于 arXiv 搜索
2. 与核心方向有学术关联，但不能重复或高度相似
3. 覆盖：交叉学科 / 底层理论 / 不同技术路线
{"4. 不得与用户明确不喜欢的方向重合" if has_neg else ""}

【输出格式】仅输出 JSON 数组：["kw1", "kw2"]"""
        return self._call_ai(prompt, count)

    def _call_ai(self, prompt: str, expected: int) -> list[str]:
        url     = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "temperature": 0.4, "max_tokens": 400,
                   "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            content = result["choices"][0]["message"]["content"].strip()
            content = re.sub(r"```[a-z]*\n?|```", "", content).strip()
            s, e = content.find("["), content.rfind("]") + 1
            if s >= 0 and e > s:
                kws = json.loads(content[s:e])
                return [k.strip() for k in kws if isinstance(k, str) and k.strip()][:expected]
        except urllib.error.HTTPError as ex:
            logger.error(f"  [Evolver] API HTTP {ex.code}: {ex.read().decode()[:150]}")
        except Exception as ex:
            logger.error(f"  [Evolver] AI 调用失败: {ex}")
        return []

    # ── config.yaml 更新 ──────────────────────────────────────

    def _update_config(self, final, pinned, exploit, explore):
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = f.read()

        lines = ["  queries:"]
        for q in pinned:
            lines += [f'    - query: "{q}"', f'      pin: true']
        for q in exploit:
            lines.append(f'    - "{q}"   # 精炼（正向信号）')
        for q in explore:
            lines.append(f'    - "{q}"   # 探索（相邻领域）')

        new_block  = "\n".join(lines)
        pattern    = r"(  queries:\s*\n)((?:[ \t]+-[^\n]*\n?)*)"
        new_raw, n = re.subn(pattern, new_block + "\n", raw)

        if n == 0:
            cfg = yaml.safe_load(raw)
            cfg["arxiv"]["queries"] = final
            new_raw = yaml.dump(cfg, allow_unicode=True,
                                default_flow_style=False, sort_keys=False)

        with open(self.config_path + ".bak", "w", encoding="utf-8") as f:
            f.write(raw)
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(new_raw)
        logger.info("  [Evolver] config.yaml 已更新（备份: .bak）")

    # ── 工具 ──────────────────────────────────────────────────

    def _load_list(self, path: str) -> list:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return d if isinstance(d, list) else []
            except Exception:
                pass
        return []

    def _load_dict(self, path: str) -> dict:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return d if isinstance(d, dict) else {}
            except Exception:
                pass
        return {}

    def _is_recent(self, iso_str: str, cutoff: datetime) -> bool:
        try:
            return datetime.fromisoformat(iso_str) >= cutoff
        except Exception:
            return True

    def _log_signal_summary(self, signals: dict):
        c = signals["clicks"]["effective_count"]
        l = signals["likes"]["effective_count"]
        d = signals["dislikes"]["effective_count"]
        s = signals["seeds"]["effective_count"]
        logger.info(f"  [Evolver] 信号汇总: 点击 {c} | 点赞 {l} | 踩 {d} | 种子 {s}")
