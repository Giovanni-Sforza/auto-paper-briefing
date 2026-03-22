#!/usr/bin/env python3
"""
setup.py — Auto-Paper-Briefing 初始化配置向导

首次使用时运行此脚本，在浏览器中完成所有配置，
自动生成 config.yaml 并可选地添加初始种子文章。

用法：
  python setup.py              # 使用默认端口 19520
  python setup.py --port 8080  # 指定端口
  python setup.py --config my_config.yaml  # 生成到指定路径
"""

import argparse
import json
import os
import re
import sys
import threading
import webbrowser
import time
import urllib.request
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SETUP_PORT   = 19520
CONFIG_PATH  = "config.yaml"
DONE_EVENT   = threading.Event()


# ── arXiv 元数据获取（用于验证种子链接）──────────────────────

def fetch_arxiv_meta(arxiv_id: str) -> dict:
    NS = {"atom": "http://www.w3.org/2005/Atom"}
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "AutoPaperBriefing-Setup/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        entry = root.find("atom:entry", NS)
        if entry is None:
            return {"error": "未找到该 arXiv 文章"}
        title = entry.find("atom:title", NS)
        authors = entry.findall("atom:author", NS)
        return {
            "arxiv_id": arxiv_id,
            "title":    title.text.strip().replace("\n"," ") if title is not None else "",
            "authors":  [a.find("atom:name", NS).text.strip()
                         for a in authors if a.find("atom:name", NS) is not None],
            "abs_url":  f"https://arxiv.org/abs/{arxiv_id}",
        }
    except Exception as e:
        return {"error": str(e)}


def parse_arxiv_id(raw: str) -> str | None:
    raw = raw.strip()
    m = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})', raw, re.I)
    if m:
        return m.group(1).split("v")[0]
    m = re.match(r'^([0-9]{4}\.[0-9]{4,5})', raw)
    if m:
        return m.group(1)
    return None


# ── HTTP Handler ──────────────────────────────────────────────

class SetupHandler(BaseHTTPRequestHandler):
    config_path: str = CONFIG_PATH

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        else:
            self._respond(404, "Not Found")

    def do_POST(self):
        body = self._read_body()
        if self.path == "/api/validate-key":
            self._validate_key(body)
        elif self.path == "/api/fetch-arxiv":
            self._fetch_arxiv(body)
        elif self.path == "/api/save":
            self._save_config(body)
        else:
            self._respond(404, "Not Found")

    def do_OPTIONS(self):
        self._respond(200, "OK")

    # ── API 处理 ─────────────────────────────────────────────

    def _validate_key(self, data: dict):
        """测试 AI API Key 是否可用"""
        api_key  = data.get("api_key", "").strip()
        base_url = data.get("base_url", "").strip().rstrip("/")
        model    = data.get("model", "gpt-4o-mini").strip()

        if not api_key or not base_url:
            self._respond_json(400, {"ok": False, "error": "API Key 和 Base URL 不能为空"})
            return

        payload = {
            "model": model, "max_tokens": 5, "temperature": 0,
            "messages": [{"role": "user", "content": "hi"}],
        }
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
            if "choices" in result:
                self._respond_json(200, {"ok": True, "model": model})
            else:
                self._respond_json(200, {"ok": False, "error": str(result)[:120]})
        except urllib.request.HTTPError as e:
            err = e.read().decode("utf-8", errors="ignore")[:150]
            self._respond_json(200, {"ok": False, "error": f"HTTP {e.code}: {err}"})
        except Exception as e:
            self._respond_json(200, {"ok": False, "error": str(e)[:120]})

    def _fetch_arxiv(self, data: dict):
        """验证并获取 arXiv 文章元数据"""
        raw = data.get("url_or_id", "").strip()
        arxiv_id = parse_arxiv_id(raw)
        if not arxiv_id:
            self._respond_json(400, {"error": f"无法解析 arXiv ID: {raw!r}"})
            return
        meta = fetch_arxiv_meta(arxiv_id)
        self._respond_json(200, meta)

    def _save_config(self, data: dict):
        """生成并保存 config.yaml 和 seeds.json"""
        try:
            self._write_config(data)
            self._write_seeds(data)
            self._respond_json(200, {"ok": True,
                                      "config_path": self.__class__.config_path})
            # 延迟关闭服务，让响应先发出去
            threading.Timer(1.0, DONE_EVENT.set).start()
        except Exception as e:
            self._respond_json(500, {"ok": False, "error": str(e)})

    def _write_config(self, data: dict):
        ai      = data.get("ai", {})
        arxiv   = data.get("arxiv", {})
        perf    = data.get("performance", {})

        queries = arxiv.get("queries", [])
        queries_yaml = "\n".join(f'    - "{q}"' for q in queries if q.strip())
        if not queries_yaml:
            queries_yaml = '    - "large language model reasoning"'

        categories = arxiv.get("categories", ["cs.AI","cs.LG","cs.CL"])
        categories_yaml = "\n".join(f'    - "{c}"' for c in categories)

        dimensions_yaml = """\
    - "研究背景与动机：该研究试图解决什么问题？现有方法的局限性是什么？"
    - "核心方法与技术：论文提出了什么方法、模型或框架？关键技术点是什么？"
    - "实验设置：使用了哪些数据集？评测指标是什么？对比了哪些基线方法？"
    - "主要实验结论：在各项指标上取得了怎样的量化结果？"
    - "研究局限性：论文中明确指出了哪些局限性或未来工作方向？" """

        max_results  = int(perf.get("max_results", 10))
        days_lookback = int(perf.get("days_lookback", 7))

        yaml_content = f"""# ============================================================
#  Auto-Paper-Briefing 配置文件
#  由初始化向导自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}
# ============================================================

ai:
  base_url: "{ai.get('base_url', 'https://api.openai.com/v1')}"
  api_key:  "{ai.get('api_key', '')}"
  model:    "{ai.get('model', 'gpt-4o-mini')}"
  temperature: 0.1
  max_tokens: 2000

arxiv:
  queries:
{queries_yaml}

  categories:
{categories_yaml}

  max_results_per_query: {max_results}
  days_lookback: {days_lookback}

summary:
  dimensions:
{dimensions_yaml}

click_tracking:
  port: 19523

keyword_evolution:
  explore_ratio: 0.50
  total_queries: 8
  lookback_days: 30
  min_signals_to_evolve: 3

paths:
  temp_pdf_dir:   "./temp_pdfs"
  history_file:   "./history.json"
  output_dir:     "./reports"
  clicks_file:    "./clicks.json"
  reactions_file: "./reactions.json"
  seeds_file:     "./seeds.json"

performance:
  request_interval: 2
  max_retries: 3
  retry_delay: 5
  max_pdf_pages: 8
  max_text_chars: 8000
"""
        with open(self.__class__.config_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)

    def _write_seeds(self, data: dict):
        seeds_list = data.get("seeds", [])
        if not seeds_list:
            return
        now = datetime.now().isoformat()
        seeds_dict = {}
        LEVELS = {1: 1.0, 2: 3.0, 3: 6.0}
        for s in seeds_list:
            aid = s.get("arxiv_id", "").strip()
            if not aid:
                continue
            level = max(1, min(3, int(s.get("level", 1))))
            seeds_dict[aid] = {
                "arxiv_id":   aid,
                "title":      s.get("title", ""),
                "authors":    s.get("authors", []),
                "level":      level,
                "weight":     LEVELS[level],
                "note":       s.get("note", ""),
                "abs_url":    f"https://arxiv.org/abs/{aid}",
                "added_at":   now,
                "updated_at": now,
            }
        if seeds_dict:
            with open("seeds.json", "w", encoding="utf-8") as f:
                json.dump(seeds_dict, f, ensure_ascii=False, indent=2)

    # ── 工具方法 ─────────────────────────────────────────────

    def _read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            b = self.rfile.read(n)
            return json.loads(b.decode("utf-8")) if b else {}
        except Exception:
            return {}

    def _respond(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(msg.encode())

    def _respond_json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        html = SETUP_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, *args):
        pass


# ── 配置向导 HTML ────────────────────────────────────────────

SETUP_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Auto-Paper-Briefing · 初始化配置</title>
<style>
:root{
  --bg:#f4f5fb;--card:#fff;--accent:#4f6ef7;--accent-dark:#3a56d4;
  --accent-light:#eef1ff;--text:#1a1d2e;--text2:#4e5370;--muted:#9498b0;
  --border:#e5e8f2;--ok:#16a34a;--ok-bg:#f0fdf4;--ok-border:#bbf7d0;
  --err:#dc2626;--err-bg:#fff5f5;--err-border:#fca5a5;
  --warn:#d97706;--warn-bg:#fffbeb;--warn-border:#fde68a;
  --r:12px;--rs:8px;--shadow:0 2px 12px rgba(79,110,247,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;padding-bottom:60px}
.header{background:linear-gradient(135deg,#3a56d4,#7c3aed);color:#fff;
  padding:40px 24px 32px;text-align:center}
.header h1{font-size:1.8rem;font-weight:800}
.header p{margin-top:8px;opacity:.82;font-size:.95rem}
.progress-bar{background:rgba(255,255,255,.2);height:4px;margin-top:20px;border-radius:2px;overflow:hidden}
.progress-fill{background:#fff;height:100%;border-radius:2px;transition:width .4s ease}
.container{max-width:720px;margin:32px auto;padding:0 18px}
.step{display:none}.step.active{display:block}

/* 卡片 */
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:28px;margin-bottom:16px;box-shadow:var(--shadow)}
.card h2{font-size:1.05rem;font-weight:700;margin-bottom:6px}
.card .desc{font-size:.88rem;color:var(--text2);margin-bottom:20px;line-height:1.6}

/* 表单 */
.field{margin-bottom:18px}
.field label{display:block;font-size:.85rem;font-weight:600;color:var(--text2);margin-bottom:6px}
.field input[type=text],.field input[type=password],.field select,.field textarea{
  width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--rs);
  font-size:.9rem;outline:none;transition:border .15s;font-family:inherit;background:#fff}
.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--accent)}
.field textarea{min-height:90px;resize:vertical;line-height:1.6}
.field .hint{font-size:.78rem;color:var(--muted);margin-top:5px}
.inline-row{display:flex;gap:10px;align-items:flex-end}
.inline-row .field{flex:1;margin-bottom:0}

/* 按钮 */
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 20px;border-radius:var(--rs);
  font-size:.88rem;font-weight:600;cursor:pointer;border:none;transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.97)}.btn:hover{opacity:.88}
.btn-primary{background:var(--accent);color:#fff}
.btn-secondary{background:var(--accent-light);color:var(--accent)}
.btn-outline{background:none;border:1px solid var(--border);color:var(--text2)}
.btn-ok{background:var(--ok);color:#fff}
.btn-sm{padding:6px 13px;font-size:.82rem}
.btn:disabled{opacity:.45;cursor:not-allowed}

/* 状态提示 */
.status{padding:9px 13px;border-radius:var(--rs);font-size:.85rem;margin-top:10px;display:none}
.status.ok{background:var(--ok-bg);color:var(--ok);border:1px solid var(--ok-border);display:block}
.status.err{background:var(--err-bg);color:var(--err);border:1px solid var(--err-border);display:block}
.status.warn{background:var(--warn-bg);color:var(--warn);border:1px solid var(--warn-border);display:block}
.status.loading{background:var(--accent-light);color:var(--accent);border:1px solid #c7d2fe;display:block}

/* API 提供商快选 */
.provider-grid{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.provider-btn{padding:7px 14px;border:2px solid var(--border);border-radius:var(--rs);
  cursor:pointer;font-size:.82rem;font-weight:600;background:var(--bg);transition:all .15s}
.provider-btn.active{background:var(--accent-light);color:var(--accent);border-color:var(--accent)}

/* 关键词标签 */
.tag-input-area{border:1px solid var(--border);border-radius:var(--rs);
  padding:8px 10px;min-height:52px;display:flex;flex-wrap:wrap;gap:6px;
  cursor:text;background:#fff;transition:border .15s}
.tag-input-area:focus-within{border-color:var(--accent)}
.tag{display:inline-flex;align-items:center;gap:4px;background:var(--accent-light);
  color:var(--accent);padding:3px 10px;border-radius:100px;font-size:.82rem;font-weight:500}
.tag .tag-del{cursor:pointer;opacity:.6;font-size:.75rem;margin-left:2px}
.tag .tag-del:hover{opacity:1}
.tag-inner-input{border:none;outline:none;font-size:.88rem;min-width:80px;
  background:transparent;font-family:inherit;padding:2px 4px}

/* 分类复选 */
.cat-grid{display:flex;flex-wrap:wrap;gap:8px}
.cat-btn{padding:5px 13px;border:1px solid var(--border);border-radius:100px;
  font-size:.8rem;cursor:pointer;transition:all .15s;background:var(--bg)}
.cat-btn.active{background:var(--accent-light);color:var(--accent);border-color:var(--accent)}

/* 种子文章 */
.seed-item{background:var(--bg);border:1px solid var(--border);border-radius:var(--rs);
  padding:12px 14px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start}
.seed-info{flex:1;min-width:0}
.seed-title{font-size:.9rem;font-weight:600;margin-bottom:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seed-meta{font-size:.78rem;color:var(--muted)}
.seed-level{display:flex;gap:6px;margin-top:8px}
.level-btn{padding:3px 10px;border:1px solid var(--border);border-radius:100px;
  font-size:.75rem;cursor:pointer;background:var(--bg)}
.level-btn.active.lv1{background:#f0f9ff;color:#0369a1;border-color:#bae6fd}
.level-btn.active.lv2{background:#fefce8;color:#a16207;border-color:#fde047}
.level-btn.active.lv3{background:#fff7ed;color:#c2410c;border-color:#fb923c}
.seed-del{flex-shrink:0;background:none;border:none;cursor:pointer;
  color:var(--muted);font-size:.85rem;padding:4px}
.seed-del:hover{color:var(--err)}

/* 导航 */
.nav-row{display:flex;justify-content:space-between;align-items:center;margin-top:24px}
.step-indicator{font-size:.82rem;color:var(--muted)}

/* 完成页 */
.done-icon{font-size:3.5rem;margin-bottom:16px}
.done-card{text-align:center;padding:40px 28px}
.done-card h2{font-size:1.4rem;font-weight:800;margin-bottom:10px}
.done-card p{color:var(--text2);font-size:.93rem;margin-bottom:8px}
.cmd-box{background:#1e1e2e;color:#a6e3a1;border-radius:var(--rs);
  padding:14px 18px;font-family:monospace;font-size:.9rem;
  text-align:left;margin:16px 0;line-height:1.8}

/* 高级参数 */
.advanced-toggle{font-size:.82rem;color:var(--accent);cursor:pointer;
  display:flex;align-items:center;gap:4px;user-select:none;margin-bottom:12px}
.advanced-section{display:none}
.advanced-section.open{display:block}
</style>
</head>
<body>

<div class="header">
  <h1>🎓 Auto-Paper-Briefing</h1>
  <p>个人 AI 学术追踪系统 · 初始化配置向导</p>
  <div class="progress-bar">
    <div class="progress-fill" id="progressFill" style="width:20%"></div>
  </div>
</div>

<div class="container">

<!-- ══════════════════════════════════════════════════════════
     Step 1: AI API 配置
════════════════════════════════════════════════════════════ -->
<div class="step active" id="step1">
  <div class="card">
    <h2>🤖 Step 1 · AI API 配置</h2>
    <p class="desc">Auto-Paper-Briefing 使用 AI 为每篇论文生成客观总结，并智能迭代搜索词。
      请填写你的 AI 服务商信息。支持所有 OpenAI 兼容接口。</p>

    <div style="margin-bottom:14px">
      <div style="font-size:.85rem;font-weight:600;color:var(--text2);margin-bottom:8px">快速选择服务商</div>
      <div class="provider-grid">
        <button class="provider-btn" onclick="selectProvider('openai')">OpenAI</button>
        <button class="provider-btn" onclick="selectProvider('deepseek')">DeepSeek</button>
        <button class="provider-btn" onclick="selectProvider('aliyun')">阿里云百炼</button>
        <button class="provider-btn" onclick="selectProvider('ollama')">Ollama（本地）</button>
        <button class="provider-btn" onclick="selectProvider('custom')">自定义</button>
      </div>
    </div>

    <div class="field">
      <label>Base URL</label>
      <input type="text" id="baseUrl" placeholder="https://api.openai.com/v1">
    </div>
    <div class="field">
      <label>API Key</label>
      <input type="password" id="apiKey" placeholder="sk-xxxxxxxxxxxxxxxx（Ollama 可留空填 ollama）">
      <div class="hint">API Key 只保存在本地 config.yaml 中，不会上传到任何服务器。</div>
    </div>
    <div class="field">
      <label>模型名称</label>
      <input type="text" id="modelName" placeholder="gpt-4o-mini">
    </div>

    <div style="display:flex;gap:10px;align-items:center">
      <button class="btn btn-secondary" onclick="validateKey()" id="validateBtn">🔍 测试连通性</button>
    </div>
    <div class="status" id="keyStatus"></div>
  </div>

  <div class="nav-row">
    <span class="step-indicator">第 1 步 / 共 4 步</span>
    <button class="btn btn-primary" onclick="goStep(2)">下一步 →</button>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════
     Step 2: 搜索关键词 + 分类
════════════════════════════════════════════════════════════ -->
<div class="step" id="step2">
  <div class="card">
    <h2>🔍 Step 2 · 初始搜索关键词</h2>
    <p class="desc">填写你感兴趣的研究方向。系统会根据你的阅读反馈自动进化这些关键词。
      建议填写 3~8 个，尽量具体（如 "chain-of-thought reasoning" 而非 "AI"）。</p>

    <div class="field">
      <label>关键词（按回车或逗号添加）</label>
      <div class="tag-input-area" id="queryTagArea" onclick="focusTagInput()">
        <input class="tag-inner-input" id="queryTagInput"
          placeholder="输入关键词，回车添加…"
          onkeydown="handleTagKey(event)"
          onblur="handleTagBlur()">
      </div>
      <div class="hint">示例：large language model reasoning · multimodal foundation model · diffusion models</div>
    </div>

    <div class="field">
      <label>arXiv 分类过滤（可多选）</label>
      <div class="cat-grid" id="catGrid">
        <button class="cat-btn active" data-cat="cs.AI" onclick="toggleCat(this)">cs.AI</button>
        <button class="cat-btn active" data-cat="cs.LG" onclick="toggleCat(this)">cs.LG</button>
        <button class="cat-btn active" data-cat="cs.CL" onclick="toggleCat(this)">cs.CL</button>
        <button class="cat-btn" data-cat="cs.CV" onclick="toggleCat(this)">cs.CV</button>
        <button class="cat-btn" data-cat="cs.RO" onclick="toggleCat(this)">cs.RO</button>
        <button class="cat-btn" data-cat="cs.NE" onclick="toggleCat(this)">cs.NE</button>
        <button class="cat-btn" data-cat="stat.ML" onclick="toggleCat(this)">stat.ML</button>
        <button class="cat-btn" data-cat="eess.SP" onclick="toggleCat(this)">eess.SP</button>
        <button class="cat-btn" data-cat="q-bio.NC" onclick="toggleCat(this)">q-bio.NC</button>
      </div>
      <div class="hint" style="margin-top:8px">不选则不限制分类，会覆盖范围更广但可能引入不相关文章。</div>
    </div>

    <!-- 高级参数 -->
    <div class="advanced-toggle" onclick="toggleAdvanced()">
      <span id="advIcon">▶</span> 高级参数（可选）
    </div>
    <div class="advanced-section" id="advancedSection">
      <div class="inline-row">
        <div class="field">
          <label>每个关键词最多获取篇数</label>
          <input type="text" id="maxResults" value="10">
          <div class="hint">日常使用建议 5~15；起步阶段可设 30~50 快速积累</div>
        </div>
        <div class="field">
          <label>检索时间范围（天）</label>
          <input type="text" id="daysLookback" value="7">
          <div class="hint">起步阶段可设 90~365；日常建议 7~30</div>
        </div>
      </div>
    </div>
  </div>

  <div class="nav-row">
    <button class="btn btn-outline" onclick="goStep(1)">← 上一步</button>
    <span class="step-indicator">第 2 步 / 共 4 步</span>
    <button class="btn btn-primary" onclick="goStep(3)">下一步 →</button>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════
     Step 3: 初始种子文章
════════════════════════════════════════════════════════════ -->
<div class="step" id="step3">
  <div class="card">
    <h2>🌱 Step 3 · 初始种子文章（可选）</h2>
    <p class="desc">添加你已知的高质量文章作为初始信号，帮助系统更快理解你的研究方向。
      这些文章会以高权重影响关键词进化。可以跳过，后续在种子管理页随时添加。</p>

    <div class="inline-row" style="margin-bottom:16px">
      <div class="field">
        <label>arXiv 链接或 ID</label>
        <input type="text" id="seedInput" placeholder="https://arxiv.org/abs/2401.12345 或 2401.12345"
          onkeydown="if(event.key==='Enter')addSeed()">
      </div>
      <div class="field" style="flex:0 0 auto">
        <label>&nbsp;</label>
        <button class="btn btn-secondary" onclick="addSeed()" id="addSeedBtn">+ 添加</button>
      </div>
    </div>

    <div class="status" id="seedStatus"></div>
    <div id="seedList" style="margin-top:12px"></div>
    <div style="font-size:.82rem;color:var(--muted);margin-top:10px">
      权重说明：📌 普通推荐 (×1) · ⭐ 重要 (×3) · 🔥 核心必读 (×6)
    </div>
  </div>

  <div class="nav-row">
    <button class="btn btn-outline" onclick="goStep(2)">← 上一步</button>
    <span class="step-indicator">第 3 步 / 共 4 步</span>
    <button class="btn btn-primary" onclick="goStep(4)">下一步 →</button>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════
     Step 4: 确认并保存
════════════════════════════════════════════════════════════ -->
<div class="step" id="step4">
  <div class="card">
    <h2>✅ Step 4 · 确认配置</h2>
    <p class="desc">请检查以下配置摘要，确认无误后点击「完成配置」生成 config.yaml 文件。</p>
    <div id="summaryBox" style="background:var(--bg);border-radius:var(--rs);
      padding:14px 16px;font-size:.88rem;line-height:1.9;border:1px solid var(--border)">
    </div>
  </div>

  <div class="nav-row">
    <button class="btn btn-outline" onclick="goStep(3)">← 上一步</button>
    <span class="step-indicator">第 4 步 / 共 4 步</span>
    <button class="btn btn-ok" onclick="saveConfig()" id="saveBtn">💾 完成配置</button>
  </div>
  <div class="status" id="saveStatus"></div>
</div>

<!-- ══════════════════════════════════════════════════════════
     完成页
════════════════════════════════════════════════════════════ -->
<div class="step" id="stepDone">
  <div class="card done-card">
    <div class="done-icon">🎉</div>
    <h2>配置完成！</h2>
    <p>config.yaml 已生成，现在可以启动主程序开始追踪论文了。</p>
    <div class="cmd-box">
      <div style="color:#89b4fa;margin-bottom:6px"># macOS / Linux</div>
      python main.py<br><br>
      <div style="color:#89b4fa;margin-bottom:6px"># Windows</div>
      python main.py
    </div>
    <p style="font-size:.82rem;color:var(--muted)">
      程序启动后，在浏览器打开 reports/ 目录下生成的 HTML 文件即可查看简报。<br>
      种子文章管理：<a href="http://127.0.0.1:19523/" target="_blank"
        style="color:var(--accent)">http://127.0.0.1:19523/</a>（main.py 运行后可访问）
    </p>
  </div>
</div>

</div><!-- /container -->

<script>
const API = "http://127.0.0.1:" + location.port;

// ── 进度管理 ────────────────────────────────────────────────
const TOTAL_STEPS = 4;
let currentStep = 1;

function goStep(n) {
  if (n > currentStep && !validateCurrentStep()) return;
  document.getElementById("step" + currentStep).classList.remove("active");
  currentStep = n;
  if (n > TOTAL_STEPS) {
    document.getElementById("stepDone").classList.add("active");
    document.querySelector(".progress-fill").style.width = "100%";
    return;
  }
  document.getElementById("step" + n).classList.add("active");
  document.querySelector(".progress-fill").style.width = (n / TOTAL_STEPS * 100) + "%";
  if (n === 4) buildSummary();
  window.scrollTo({top:0, behavior:"smooth"});
}

function validateCurrentStep() {
  if (currentStep === 1) {
    const key = document.getElementById("apiKey").value.trim();
    const url = document.getElementById("baseUrl").value.trim();
    if (!key || !url) { showStatus("keyStatus","warn","⚠️ 请填写 Base URL 和 API Key"); return false; }
  }
  if (currentStep === 2) {
    if (getQueries().length === 0) {
      alert("请至少填写一个搜索关键词");
      return false;
    }
  }
  return true;
}

// ── Step 1: 服务商快选 ───────────────────────────────────────
const PROVIDERS = {
  openai:   { url:"https://api.openai.com/v1",  model:"gpt-4o-mini",      key:"" },
  deepseek: { url:"https://api.deepseek.com/v1", model:"deepseek-chat",   key:"" },
  aliyun:   { url:"https://dashscope.aliyuncs.com/compatible-mode/v1",
               model:"qwen-plus", key:"" },
  ollama:   { url:"http://localhost:11434/v1",   model:"llama3",          key:"ollama" },
  custom:   { url:"", model:"", key:"" },
};

function selectProvider(id) {
  document.querySelectorAll(".provider-btn").forEach(b =>
    b.classList.toggle("active", b.textContent.toLowerCase().includes(id) ||
    (id==="custom" && b.textContent==="自定义")));
  const p = PROVIDERS[id];
  if (p.url) document.getElementById("baseUrl").value  = p.url;
  if (p.model) document.getElementById("modelName").value = p.model;
  if (p.key)  document.getElementById("apiKey").value  = p.key;
}

async function validateKey() {
  const key  = document.getElementById("apiKey").value.trim();
  const url  = document.getElementById("baseUrl").value.trim();
  const model = document.getElementById("modelName").value.trim() || "gpt-4o-mini";
  if (!key || !url) { showStatus("keyStatus","warn","请先填写 Base URL 和 API Key"); return; }
  showStatus("keyStatus","loading","⏳ 测试中，请稍候…");
  const btn = document.getElementById("validateBtn");
  btn.disabled = true;
  try {
    const res  = await fetch(API + "/api/validate-key", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({api_key:key, base_url:url, model})
    });
    const data = await res.json();
    if (data.ok) showStatus("keyStatus","ok","✅ 连接成功！模型: " + (data.model||model));
    else         showStatus("keyStatus","err","❌ 连接失败: " + (data.error||"未知错误"));
  } catch(e) {
    showStatus("keyStatus","err","❌ 无法连接向导服务: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── Step 2: 关键词标签 ───────────────────────────────────────
const queryTags = [];

function focusTagInput() {
  document.getElementById("queryTagInput").focus();
}

function handleTagKey(e) {
  const input = e.target;
  const val   = input.value.trim();
  if ((e.key === "Enter" || e.key === ",") && val) {
    e.preventDefault();
    addTag(val.replace(/,$/, "").trim());
    input.value = "";
  } else if (e.key === "Backspace" && !input.value && queryTags.length > 0) {
    removeTag(queryTags.length - 1);
  }
}

function handleTagBlur() {
  const input = document.getElementById("queryTagInput");
  const val   = input.value.trim();
  if (val) { addTag(val); input.value = ""; }
}

function addTag(text) {
  if (!text || queryTags.includes(text)) return;
  queryTags.push(text);
  renderTags();
}

function removeTag(i) {
  queryTags.splice(i, 1);
  renderTags();
}

function renderTags() {
  const area  = document.getElementById("queryTagArea");
  const input = document.getElementById("queryTagInput");
  // 删除旧 tag
  area.querySelectorAll(".tag").forEach(t => t.remove());
  queryTags.forEach((t, i) => {
    const el = document.createElement("span");
    el.className = "tag";
    el.innerHTML = `${esc(t)} <span class="tag-del" onclick="removeTag(${i})">×</span>`;
    area.insertBefore(el, input);
  });
}

function getQueries() { return [...queryTags]; }

// 分类
const selectedCats = new Set(["cs.AI","cs.LG","cs.CL"]);
function toggleCat(btn) {
  const cat = btn.dataset.cat;
  if (selectedCats.has(cat)) { selectedCats.delete(cat); btn.classList.remove("active"); }
  else                        { selectedCats.add(cat);    btn.classList.add("active"); }
}

// 高级参数
function toggleAdvanced() {
  const sec  = document.getElementById("advancedSection");
  const icon = document.getElementById("advIcon");
  const open = sec.classList.toggle("open");
  icon.textContent = open ? "▼" : "▶";
}

// ── Step 3: 种子文章 ────────────────────────────────────────
const seeds = [];

async function addSeed() {
  const input = document.getElementById("seedInput");
  const raw   = input.value.trim();
  if (!raw) return;
  showStatus("seedStatus","loading","⏳ 正在查询 arXiv…");
  document.getElementById("addSeedBtn").disabled = true;
  try {
    const res  = await fetch(API + "/api/fetch-arxiv", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({url_or_id: raw})
    });
    const data = await res.json();
    if (data.error) {
      showStatus("seedStatus","err","❌ " + data.error);
    } else {
      if (seeds.find(s => s.arxiv_id === data.arxiv_id)) {
        showStatus("seedStatus","warn","ℹ️ 该文章已在列表中");
      } else {
        seeds.push({...data, level:1});
        renderSeeds();
        showStatus("seedStatus","ok","✅ 已添加: " + data.title.slice(0,60));
        input.value = "";
      }
    }
  } catch(e) {
    showStatus("seedStatus","err","❌ " + e.message);
  } finally {
    document.getElementById("addSeedBtn").disabled = false;
  }
}

function renderSeeds() {
  const el = document.getElementById("seedList");
  if (!seeds.length) { el.innerHTML = ""; return; }
  el.innerHTML = seeds.map((s,i) => `
<div class="seed-item">
  <div class="seed-info">
    <div class="seed-title">${esc(s.title)}</div>
    <div class="seed-meta">arXiv:${esc(s.arxiv_id)} · ${(s.authors||[]).slice(0,2).join(", ")}</div>
    <div class="seed-level">
      <button class="level-btn lv1 ${s.level===1?'active':''}" onclick="setSeedLevel(${i},1)">📌 普通</button>
      <button class="level-btn lv2 ${s.level===2?'active':''}" onclick="setSeedLevel(${i},2)">⭐ 重要</button>
      <button class="level-btn lv3 ${s.level===3?'active':''}" onclick="setSeedLevel(${i},3)">🔥 核心</button>
    </div>
  </div>
  <button class="seed-del" onclick="removeSeed(${i})">🗑</button>
</div>`).join("");
}

function setSeedLevel(i, lv) { seeds[i].level = lv; renderSeeds(); }
function removeSeed(i) { seeds.splice(i,1); renderSeeds(); }

// ── Step 4: 摘要 + 保存 ────────────────────────────────────
function buildSummary() {
  const cats = [...selectedCats].join(", ") || "不限";
  document.getElementById("summaryBox").innerHTML = `
    <b>🤖 AI 接口</b><br>
    Base URL: ${esc(document.getElementById("baseUrl").value)}<br>
    模型: ${esc(document.getElementById("modelName").value)}<br><br>
    <b>🔍 搜索关键词</b>（${getQueries().length} 个）<br>
    ${getQueries().map(q=>`· ${esc(q)}`).join("<br>")}<br><br>
    <b>📂 分类过滤</b>: ${esc(cats)}<br>
    <b>📄 每词最多</b>: ${document.getElementById("maxResults").value} 篇 ·
    <b>⏱ 时间范围</b>: 近 ${document.getElementById("daysLookback").value} 天<br><br>
    <b>🌱 种子文章</b>: ${seeds.length} 篇
  `;
}

async function saveConfig() {
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  showStatus("saveStatus","loading","⏳ 正在生成配置文件…");
  try {
    const payload = {
      ai: {
        api_key:  document.getElementById("apiKey").value.trim(),
        base_url: document.getElementById("baseUrl").value.trim(),
        model:    document.getElementById("modelName").value.trim() || "gpt-4o-mini",
      },
      arxiv: {
        queries:    getQueries(),
        categories: [...selectedCats],
      },
      performance: {
        max_results:  parseInt(document.getElementById("maxResults").value) || 10,
        days_lookback: parseInt(document.getElementById("daysLookback").value) || 7,
      },
      seeds: seeds,
    };
    const res  = await fetch(API + "/api/save", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) { goStep(5); }
    else showStatus("saveStatus","err","❌ 保存失败: " + (data.error||""));
  } catch(e) {
    showStatus("saveStatus","err","❌ " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── 工具 ────────────────────────────────────────────────────
function showStatus(id, type, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = "status " + type;
  el.textContent = msg;
}

function esc(s) {
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
</script>
</body></html>"""


# ── 主程序 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-Paper-Briefing 初始化配置向导")
    parser.add_argument("--port",   type=int, default=SETUP_PORT, help=f"向导服务端口（默认 {SETUP_PORT}）")
    parser.add_argument("--config", default=CONFIG_PATH,          help="生成的配置文件路径")
    args = parser.parse_args()

    # 检查是否已有配置
    if os.path.exists(args.config):
        print(f"⚠️  {args.config} 已存在。")
        ans = input("   继续运行向导将覆盖现有配置，是否继续？[y/N] ").strip().lower()
        if ans != "y":
            print("已取消。如需重新配置，请先删除 config.yaml。")
            sys.exit(0)

    SetupHandler.config_path = args.config

    server = HTTPServer(("127.0.0.1", args.port), SetupHandler)
    url    = f"http://127.0.0.1:{args.port}/"

    print()
    print("=" * 55)
    print("  Auto-Paper-Briefing · 初始化配置向导")
    print("=" * 55)
    print(f"  向导已启动 → {url}")
    print("  正在自动打开浏览器…")
    print("  配置完成后此窗口将自动关闭。")
    print("=" * 55)
    print()

    # 延迟打开浏览器（给服务器一点启动时间）
    def _open():
        time.sleep(0.5)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()

    # 在后台线程运行服务器，主线程等待完成信号
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    DONE_EVENT.wait()   # 阻塞直到 /api/save 触发
    server.shutdown()

    print()
    print("✅  配置文件已生成：", args.config)
    if os.path.exists("seeds.json"):
        import json as _j
        n = len(_j.load(open("seeds.json")))
        print(f"🌱  种子文章：{n} 篇（seeds.json）")
    print()
    print("现在可以运行主程序：")
    print("  python main.py")
    print()


if __name__ == "__main__":
    main()
