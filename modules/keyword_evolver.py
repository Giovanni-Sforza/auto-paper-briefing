"""
keyword_evolver.py — 关键词进化模块 v2

三轨信号融合，防止信息茧房
─────────────────────────────────────────────────────
  信号类型      来源文件        权重说明
  ─────────── ──────────────  ─────────────────────────
  点击 click   clicks.json    弱信号（weight=1）
  点赞 like    likes.json     强信号（weight=2）
  种子 seed    seeds.json     超强信号（weight=1/2/3档，weight=1/3/6）

  精炼轨道（exploit）：上述加权信号 → 收敛到核心兴趣
  探索轨道（explore）：AI 推断相邻领域 → 发散，防茧房

比例由 config.yaml 的 keyword_evolution.explore_ratio 控制（默认50%）
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
    """三信号融合的关键词进化引擎"""

    def __init__(self, config: dict, config_path: str):
        self.config      = config
        self.config_path = config_path
        paths            = config.get("paths", {})
        self.clicks_file = paths.get("clicks_file", "./clicks.json")
        self.likes_file  = paths.get("likes_file",  "./likes.json")
        self.seeds_file  = paths.get("seeds_file",  "./seeds.json")

        evo = config.get("keyword_evolution", {})
        self.explore_ratio = evo.get("explore_ratio", 0.50)
        self.total_queries = evo.get("total_queries", 8)
        self.lookback_days = evo.get("lookback_days", 30)
        self.min_signals   = evo.get("min_signals_to_evolve", 3)

        self.api_key  = config["ai"]["api_key"]
        self.base_url = config["ai"]["base_url"].rstrip("/")
        self.model    = config["ai"]["model"]

    # ─────────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────────

    def should_evolve(self) -> bool:
        """只要任一信号来源有足够数据就触发进化"""
        signals = self._collect_all_signals()
        total   = sum(s["effective_count"] for s in signals.values())
        if total < self.min_signals:
            logger.info(f"  [Evolver] 有效信号 {total} 条，"
                        f"不足 {self.min_signals} 条，跳过")
            return False
        return True

    def evolve(self) -> list[str]:
        """执行关键词进化，返回新列表并写回 config.yaml"""
        logger.info("  [Evolver] ── 开始三信号融合分析 ──")
        signals = self._collect_all_signals()
        self._log_signal_summary(signals)

        # ── 固定关键词（pin=true，不参与进化）──────────────
        current  = self.config["arxiv"].get("queries", [])
        pinned   = [q for q in current if isinstance(q, dict) and q.get("pin")]
        pin_texts = [q["query"] for q in pinned]

        available   = max(self.total_queries - len(pin_texts), 2)
        exploit_n   = max(1, math.floor(available * (1 - self.explore_ratio)))
        explore_n   = available - exploit_n
        logger.info(f"  [Evolver] 槽位分配: 精炼 {exploit_n} + 探索 {explore_n}（固定 {len(pin_texts)}）")

        # ── 构建融合 prompt ──────────────────────────────────
        combined_prompt = self._build_combined_signal_text(signals)

        # ── 精炼关键词 ───────────────────────────────────────
        exploit_kws = self._generate_exploit(combined_prompt, exploit_n)
        logger.info(f"  [Evolver] 精炼: {exploit_kws}")

        # ── 探索关键词 ───────────────────────────────────────
        explore_kws = self._generate_explore(exploit_kws, explore_n)
        logger.info(f"  [Evolver] 探索: {explore_kws}")

        # ── 合并 & 写回 ──────────────────────────────────────
        final = pin_texts + exploit_kws + explore_kws
        self._update_config(final, pin_texts, exploit_kws, explore_kws)

        logger.info(f"  [Evolver] ✓ 关键词进化完成，共 {len(final)} 个:")
        for q in final:
            flag = "📌" if q in pin_texts else ("🔍" if q in exploit_kws else "🌐")
            logger.info(f"    {flag} {q}")

        return final

    # ─────────────────────────────────────────────────────────
    # 信号收集
    # ─────────────────────────────────────────────────────────

    def _collect_all_signals(self) -> dict:
        """收集三类信号，返回结构化字典"""
        cutoff = datetime.now() - timedelta(days=self.lookback_days)

        # 1. 点击
        clicks     = self._load_json_list(self.clicks_file)
        recent_clicks = [c for c in clicks if self._is_recent(c.get("clicked_at", ""), cutoff)]

        # 2. 点赞（全量，不限时间——点赞代表持久兴趣）
        likes = self._load_json_list(self.likes_file)

        # 3. 种子
        seeds_raw = self._load_json_dict(self.seeds_file)
        seeds     = list(seeds_raw.values()) if seeds_raw else []

        return {
            "clicks": {
                "items": recent_clicks,
                "effective_count": len(recent_clicks),
                "weight_per_item": 1,
            },
            "likes": {
                "items": likes,
                "effective_count": len(likes),
                "weight_per_item": 2,   # 点赞=2倍点击
            },
            "seeds": {
                "items": seeds,
                "effective_count": len(seeds),
                "weight_per_item": None,  # 每篇种子有自己的 weight
            },
        }

    def _build_combined_signal_text(self, signals: dict) -> str:
        """将三类信号合并为供 AI 分析的文本"""
        lines = []

        # 种子（最高优先级，按权重重复出现）
        for s in sorted(signals["seeds"]["items"], key=lambda x: -x.get("weight", 1)):
            lvl     = s.get("level", 1)
            emoji   = {1: "📌", 2: "⭐", 3: "🔥"}.get(lvl, "📌")
            repeats = lvl   # Lv1=1次，Lv2=2次，Lv3=3次
            note    = f"（备注：{s['note']}）" if s.get("note") else ""
            for _ in range(repeats):
                lines.append(f"{emoji} [种子Lv{lvl}] {s.get('title','')}{note}")

        # 点赞（每篇出现2次，强化其权重）
        for r in signals["likes"]["items"][:30]:
            date = r.get("liked_at", "")[:10]
            lines.append(f"👍 [点赞] {r.get('title','')}（{date}）")
            lines.append(f"👍 [点赞] {r.get('title','')}（加权重复）")

        # 普通点击（出现1次）
        for c in signals["clicks"]["items"][:40]:
            action = "摘要" if c.get("action") == "abs" else "PDF"
            date   = c.get("clicked_at", "")[:10]
            lines.append(f"🖱️ [点击{action}] {c.get('title','')}（{date}）")

        return "\n".join(lines) if lines else "（暂无信号数据）"

    # ─────────────────────────────────────────────────────────
    # AI 调用
    # ─────────────────────────────────────────────────────────

    def _generate_exploit(self, signal_text: str, count: int) -> list[str]:
        prompt = f"""你是一位学术研究助手，负责从用户的阅读信号中提炼研究兴趣。

信号说明（权重从高到低）：
  🔥 [种子Lv3] 核心必读 — 最高权重，直接相关
  ⭐ [种子Lv2] 重要推荐 — 高权重
  📌 [种子Lv1] 普通种子 — 中等权重
  👍 [点赞]              — 主动表达喜爱
  🖱️ [点击]              — 被动浏览记录

用户的阅读信号（共 {len(signal_text.splitlines())} 条）：
{signal_text}

【任务】
综合以上信号，提炼出用户最核心的 {count} 个 arXiv 搜索关键词。
高权重信号（种子、点赞）对结果影响更大。

【要求】
1. 英文关键词，可直接用于 arXiv 全文搜索
2. 聚焦具体技术方向（如 "chain-of-thought reasoning"，而非 "machine learning"）
3. 仅输出 JSON 数组，不含其他文字：["kw1", "kw2"]"""
        return self._call_ai(prompt, count)

    def _generate_explore(self, exploit_kws: list[str], count: int) -> list[str]:
        if not exploit_kws:
            return []
        prompt = f"""你是一位学术研究助手，帮助用户拓展视野、防止信息茧房。

用户当前核心兴趣：
{json.dumps(exploit_kws, ensure_ascii=False)}

【任务】
基于以上方向，生成 {count} 个「相邻但尚未探索」的 arXiv 搜索关键词。

【要求】
1. 英文，可直接用于 arXiv 搜索
2. 与现有方向有学术关联，但不能重复或高度相似
3. 覆盖：交叉学科 / 底层理论 / 不同技术路线
4. 仅输出 JSON 数组：["kw1", "kw2"]"""
        return self._call_ai(prompt, count)

    def _call_ai(self, prompt: str, expected: int) -> list[str]:
        url     = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model, "temperature": 0.4, "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }
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
        except urllib.error.HTTPError as e:
            logger.error(f"  [Evolver] API HTTP {e.code}: {e.read().decode()[:150]}")
        except Exception as e:
            logger.error(f"  [Evolver] AI 调用失败: {e}")
        return []

    # ─────────────────────────────────────────────────────────
    # config.yaml 更新
    # ─────────────────────────────────────────────────────────

    def _update_config(self, final: list[str], pinned: list[str],
                       exploit: list[str], explore: list[str]):
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = f.read()

        lines = ["  queries:"]
        for q in pinned:
            lines += [f'    - query: "{q}"', f'      pin: true']
        for q in exploit:
            lines.append(f'    - "{q}"   # 精炼（点击/点赞/种子）')
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
        logger.info(f"  [Evolver] config.yaml 已更新（备份: .bak）")

    # ─────────────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────────────

    def _load_json_list(self, path: str) -> list:
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _load_json_dict(self, path: str) -> dict:
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _is_recent(self, iso_str: str, cutoff: datetime) -> bool:
        try:
            return datetime.fromisoformat(iso_str) >= cutoff
        except Exception:
            return True

    def _log_signal_summary(self, signals: dict):
        c = signals["clicks"]["effective_count"]
        l = signals["likes"]["effective_count"]
        s = signals["seeds"]["effective_count"]
        logger.info(f"  [Evolver] 信号汇总: 点击 {c} | 点赞 {l} | 种子 {s}")
