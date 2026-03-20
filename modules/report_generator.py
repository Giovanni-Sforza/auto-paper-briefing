"""
report_generator.py — HTML 简报生成模块 v4

每日简报（Daily_Paper_YYYYMMDD.html）：服务端渲染
点赞历史（likes_history.html）：纯前端，实时从 /api/likes 拉取，只生成一次
"""

import json
import os
import logging
from datetime import datetime
from html import escape

logger = logging.getLogger(__name__)
DEFAULT_TRACKER_PORT = 19523


class ReportGenerator:
    def __init__(self, config: dict):
        self.output_dir   = config["paths"]["output_dir"]
        self.tracker_port = config.get("click_tracking", {}).get("port", DEFAULT_TRACKER_PORT)
        os.makedirs(self.output_dir, exist_ok=True)

    # ── 每日简报 ──────────────────────────────────────────────

    def generate(self, papers: list[dict]) -> str:
        today    = datetime.now().strftime("%Y%m%d")
        filename = f"Daily_Paper_{today}.html"
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._render_daily(papers, today))
        return filepath

    # ── 点赞历史（纯前端，只生成一次，常驻）────────────────────

    def generate_likes_history(self) -> str:
        """生成纯前端的点赞历史页，实时从 /api/likes 拉取数据"""
        filepath = os.path.join(self.output_dir, "likes_history.html")
        # 只有文件不存在时才写入（常驻，不需要每次重写）
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self._render_likes_history_frontend())
            logger.info(f"  [Report] 点赞历史页已生成（常驻）: {filepath}")
        return filepath

    # ─────────────────────────────────────────────────────────
    # 每日简报渲染
    # ─────────────────────────────────────────────────────────

    def _render_daily(self, papers: list[dict], date_str: str) -> str:
        date_display = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        cards = "".join(self._card(p, i+1, date_str) for i, p in enumerate(papers))
        if not papers:
            cards = '<div class="empty-state">📭 本次运行未发现新论文</div>'
        port = self.tracker_port

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>学术简报 · {date_display}</title>
  <style>{DAILY_CSS}</style>
</head>
<body>

<div id="trackerBar" class="tracker-bar">⏳ 正在连接追踪服务…</div>

<div class="header">
  <h1>📄 学术论文简报</h1>
  <div class="subtitle">Auto-Paper-Briefing · {date_display} 生成</div>
  <div class="stats">
    <span>本期 <strong>{len(papers)}</strong> 篇</span>
    <span>数据源 <strong>arXiv</strong></span>
    <span>AI 客观总结</span>
    <a href="likes_history.html" class="nav-link">⭐ 点赞历史</a>
    <a href="http://127.0.0.1:{port}/" class="nav-link" target="_blank">🌱 种子管理</a>
  </div>
</div>

<div class="container">
  {cards}
  <div class="footer">
    Auto-Paper-Briefing · {date_display} · 客观信息提取，不含主观评价
  </div>
</div>

<script>
const TRACKER = "http://127.0.0.1:{port}";
const REPORT_DATE = "{date_str}";
{SHARED_JS}
</script>
</body></html>"""

    def _card(self, paper: dict, idx: int, date_str: str) -> str:
        arxiv_id   = paper.get("arxiv_id", "")
        title      = paper.get("title", "未知标题")
        authors    = paper.get("authors", [])
        abs_url    = paper.get("abs_url", "#")
        pdf_url    = paper.get("pdf_url", "#")
        categories = paper.get("categories", [])[:3]
        published  = paper.get("published", "")[:10]
        abstract   = paper.get("abstract", "")
        summary    = paper.get("summary", {})
        has_error  = "error" in summary

        uid        = escape(arxiv_id).replace(".", "-")
        title_e    = escape(title)
        title_attr = title.replace('"', '&quot;').replace("'", "&#39;")[:120]
        abs_e      = escape(abs_url)
        pdf_e      = escape(pdf_url)
        arxiv_e    = escape(arxiv_id)
        author_str = escape(", ".join(authors[:5]) + ("等" if len(authors) > 5 else ""))
        tags_html  = "".join(f'<span class="tag">{escape(c)}</span>' for c in categories)
        date_html  = f'<span class="date-tag">📅 {escape(published)}</span>' if published else ""

        # 摘要折叠
        abstract_html = ""
        if abstract.strip():
            abstract_html = f"""
  <button class="section-toggle" data-target="abstract-{uid}" onclick="toggleSection(this)">
    <span class="arrow">▶</span> 原文摘要 (Abstract)
  </button>
  <div class="collapsible" id="abstract-{uid}">
    <div class="abstract-body">
      <div class="abstract-label">Abstract</div>
      {escape(abstract)}
    </div>
  </div>"""

        # AI 总结（默认展开）
        if has_error:
            summary_inner = f'<div class="error-msg">⚠ 处理失败: {escape(str(summary["error"]))}</div>'
            card_extra    = " error-card"
        else:
            items = []
            for k, v in summary.items():
                label = "AI 总结" if k == "原始总结" else str(k)
                items.append(f"""
        <div class="summary-item">
          <div class="dim-label">{escape(label)}</div>
          <div class="dim-content">{escape(str(v))}</div>
        </div>""")
            summary_inner = "\n".join(items) if items else '<div class="error-msg">暂无总结</div>'
            card_extra    = ""

        # summary_snippet 传给 like 按钮
        snippet_raw  = ""
        if not has_error and summary:
            snippet_raw = str(next(iter(summary.values()), ""))[:100]
        snippet_attr  = snippet_raw.replace('"', '&quot;').replace("'", "&#39;")
        authors_attr  = json.dumps(authors[:5]).replace('"', '&quot;')

        return f"""
<div class="paper-card{card_extra}" id="card-{uid}">
  <div class="card-top">
    <div class="paper-index">{idx}</div>
    <div class="paper-title">{title_e}</div>
    <span class="read-badge">已读</span>
  </div>

  <div class="meta-row">
    <div class="authors">👤 {author_str}</div>
    <div class="tags">{tags_html}{date_html}</div>
  </div>

  {abstract_html}

  <button class="section-toggle open" data-target="summary-{uid}" onclick="toggleSection(this)">
    <span class="arrow">▶</span> AI 客观总结
    <span class="toggle-count">{len(summary) if not has_error else 0} 个维度</span>
  </button>
  <div class="collapsible open" id="summary-{uid}">
    <div class="summary-body">{summary_inner}</div>
  </div>

  <div class="card-footer">
    <button class="btn btn-primary"
      data-arxiv-id="{arxiv_e}" data-title="{title_attr}"
      data-action="abs" data-url="{abs_e}"
      onclick="trackAndOpen(event,this)">🔗 查看摘要页
    </button>
    <button class="btn btn-secondary"
      data-arxiv-id="{arxiv_e}" data-title="{title_attr}"
      data-action="pdf" data-url="{pdf_e}"
      onclick="trackAndOpen(event,this)">📥 下载 PDF
    </button>
    <button class="btn btn-like" id="like-{uid}"
      data-arxiv-id="{arxiv_e}"
      data-title="{title_attr}"
      data-authors="{authors_attr}"
      data-abs-url="{abs_e}"
      data-snippet="{snippet_attr}"
      onclick="toggleLike(event,this)">👍 点赞
    </button>
    <span class="arxiv-id">arXiv:{arxiv_e}</span>
  </div>
</div>"""

    # ─────────────────────────────────────────────────────────
    # 纯前端点赞历史页
    # ─────────────────────────────────────────────────────────

    def _render_likes_history_frontend(self) -> str:
        port = self.tracker_port
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>点赞历史 · Auto-Paper-Briefing</title>
<style>{LIKES_CSS}</style>
</head>
<body>
<div class="header">
  <h1>⭐ 点赞历史</h1>
  <div class="subtitle" id="subtitle">加载中…</div>
  <div class="nav">
    <a href="javascript:history.back()">← 返回简报</a>
    <a href="http://127.0.0.1:{port}/" target="_blank">🌱 种子管理</a>
  </div>
</div>

<div class="container">
  <div class="toolbar">
    <input type="text" id="searchBox" placeholder="🔍 搜索标题或作者…" oninput="renderList()">
    <span class="sort-label">排序：</span>
    <button class="sort-btn active" id="sortNew" onclick="setSort('new')">最新优先</button>
    <button class="sort-btn" id="sortOld" onclick="setSort('old')">最早优先</button>
  </div>

  <div class="timeline" id="listEl">
    <div class="loading">⏳ 加载中…</div>
  </div>

  <div class="footer">
    点赞记录实时从本地服务读取 · Auto-Paper-Briefing
  </div>
</div>

<script>
const API = "http://127.0.0.1:{port}";
let allLikes = [];
let sortOrder = "new";

async function load() {{
  try {{
    const res  = await fetch(API + "/api/likes");
    allLikes   = await res.json();
    document.getElementById("subtitle").textContent =
      `共 ${{allLikes.length}} 篇 · 实时更新`;
    renderList();
  }} catch(e) {{
    document.getElementById("listEl").innerHTML =
      '<div class="empty">⚠️ 无法连接服务，请先运行 python main.py</div>';
    document.getElementById("subtitle").textContent = "服务未运行";
  }}
}}

function setSort(order) {{
  sortOrder = order;
  document.getElementById("sortNew").classList.toggle("active", order==="new");
  document.getElementById("sortOld").classList.toggle("active", order==="old");
  renderList();
}}

function renderList() {{
  const q   = document.getElementById("searchBox").value.toLowerCase();
  let list  = allLikes.filter(r =>
    (r.title||"").toLowerCase().includes(q) ||
    (r.authors||[]).join(" ").toLowerCase().includes(q)
  );
  if (sortOrder === "old") list = [...list].reverse();

  const el = document.getElementById("listEl");
  if (!list.length) {{
    el.innerHTML = allLikes.length
      ? '<div class="empty">🔍 没有匹配的结果</div>'
      : '<div class="empty">💭 还没有点赞记录，去简报页点赞吧</div>';
    return;
  }}

  el.innerHTML = list.map((r, i) => {{
    const date  = formatDate(r.liked_at);
    const auth  = (r.authors||[]).slice(0,3).join(", ") + ((r.authors||[]).length>3?" 等":"");
    const snip  = r.summary_snippet
      ? `<div class="snippet">${{esc(r.summary_snippet)}}</div>` : "";
    return `
<div class="like-item">
  <div class="item-num">${{i+1}}</div>
  <div class="item-body">
    <div class="item-title">
      <a href="${{esc(r.abs_url)}}" target="_blank">${{esc(r.title)}}</a>
    </div>
    <div class="item-meta">
      <span>👤 ${{esc(auth)||'（作者未知）'}}</span>
      <span class="like-date">⭐ ${{date}}</span>
      <span class="arxiv-id">arXiv:${{esc(r.arxiv_id)}}</span>
    </div>
    ${{snip}}
  </div>
</div>`;
  }}).join("");
}}

function formatDate(iso) {{
  if (!iso) return "";
  try {{
    const d = new Date(iso);
    return d.getFullYear() + "年" +
      String(d.getMonth()+1).padStart(2,"0") + "月" +
      String(d.getDate()).padStart(2,"0") + "日 " +
      String(d.getHours()).padStart(2,"0") + ":" +
      String(d.getMinutes()).padStart(2,"0");
  }} catch{{ return iso.slice(0,16); }}
}}

function esc(s) {{
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

load();
// 每 30 秒自动刷新（实时感）
setInterval(load, 30000);
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# CSS 常量
# ─────────────────────────────────────────────────────────────

DAILY_CSS = """
:root{
  --bg:#f4f5fb;--card:#fff;--accent:#4f6ef7;--accent-dark:#3a56d4;
  --accent-light:#eef1ff;--text:#1a1d2e;--text2:#4e5370;--muted:#9498b0;
  --border:#e5e8f2;--tag-bg:#eff1ff;--tag-c:#4f6ef7;
  --like-bg:#fff7ed;--like-c:#ea580c;--like-border:#fed7aa;--like-active:#f97316;
  --abs-bg:#fafbff;--err-bg:#fff5f5;--err-border:#fca5a5;
  --shadow-sm:0 1px 4px rgba(30,40,120,.06);--shadow-md:0 4px 18px rgba(79,110,247,.10);
  --r:14px;--rs:8px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.75;padding-bottom:80px}
.tracker-bar{text-align:center;padding:8px 20px;font-size:.78rem;
  background:#fffbeb;color:#92400e;border-bottom:1px solid #fde68a}
.tracker-bar.online{background:#f0fdf4;color:#166534;border-color:#bbf7d0}
.header{background:linear-gradient(135deg,#3a56d4,#6d28d9);color:#fff;
  padding:44px 24px 36px;text-align:center}
.header h1{font-size:1.9rem;font-weight:800;letter-spacing:-.5px}
.header .subtitle{margin-top:6px;font-size:.95rem;opacity:.8}
.header .stats{display:inline-flex;gap:16px;flex-wrap:wrap;justify-content:center;
  align-items:center;margin-top:18px;background:rgba(255,255,255,.14);
  border-radius:100px;padding:8px 22px;font-size:.86rem}
.header .stats span{opacity:.88} .header .stats strong{opacity:1}
.nav-link{color:#fff;text-decoration:none;background:rgba(255,255,255,.2);
  border-radius:100px;padding:3px 13px;font-size:.82rem;font-weight:600;white-space:nowrap}
.nav-link:hover{background:rgba(255,255,255,.32)}
.container{max-width:920px;margin:28px auto 0;padding:0 18px}
.paper-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:24px 26px 0;margin-bottom:18px;
  box-shadow:var(--shadow-sm);transition:box-shadow .2s,border-color .2s;overflow:hidden}
.paper-card:hover{box-shadow:var(--shadow-md);border-color:#c5ceff}
.paper-card.clicked-card{border-left:3px solid var(--accent)}
.paper-card.liked-card{border-left:3px solid var(--like-active)}
.card-top{display:flex;align-items:flex-start;gap:13px;margin-bottom:12px}
.paper-index{flex-shrink:0;width:30px;height:30px;background:var(--accent-light);
  color:var(--accent);border-radius:var(--rs);display:flex;align-items:center;
  justify-content:center;font-size:.82rem;font-weight:700}
.paper-title{font-size:1.06rem;font-weight:700;color:var(--text);line-height:1.45;flex:1}
.read-badge{flex-shrink:0;font-size:.7rem;padding:2px 8px;background:var(--accent-light);
  color:var(--accent);border-radius:100px;font-weight:600;align-self:flex-start;
  margin-top:4px;display:none}
.paper-card.clicked-card .read-badge{display:inline-block}
.meta-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  margin-bottom:14px;padding-left:43px}
.authors{font-size:.86rem;color:var(--text2);flex:1;min-width:180px}
.tags{display:flex;gap:5px;flex-wrap:wrap}
.tag{font-size:.73rem;background:var(--tag-bg);color:var(--tag-c);
  padding:2px 8px;border-radius:100px;font-weight:600}
.date-tag{font-size:.75rem;color:var(--muted);background:var(--bg);
  padding:2px 8px;border-radius:100px;border:1px solid var(--border)}
.section-toggle{width:100%;background:none;border:none;cursor:pointer;text-align:left;
  padding:10px 0 10px 43px;display:flex;align-items:center;gap:7px;
  font-size:.82rem;font-weight:600;color:var(--muted);
  border-top:1px solid var(--border);transition:color .15s}
.section-toggle:hover{color:var(--accent)}
.arrow{font-size:.65rem;transition:transform .2s;display:inline-block}
.section-toggle.open .arrow{transform:rotate(90deg)}
.toggle-count{margin-left:auto;padding-right:4px;font-weight:400;font-size:.75rem;color:var(--muted)}
.collapsible{overflow:hidden;max-height:0;transition:max-height .35s ease}
.collapsible.open{max-height:4000px}
.abstract-body{padding:12px 14px 16px 43px;font-size:.9rem;color:var(--text2);
  background:var(--abs-bg);border-top:1px solid var(--border);line-height:1.75}
.abstract-label{font-size:.73rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}
.summary-body{padding:14px 14px 16px 43px}
.summary-item{margin-bottom:13px}
.dim-label{font-size:.75rem;font-weight:700;color:var(--accent);
  text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}
.dim-content{font-size:.9rem;color:var(--text2);background:var(--bg);border-radius:var(--rs);
  padding:9px 13px;border-left:3px solid var(--accent-light);line-height:1.7}
.error-card{background:var(--err-bg);border-color:var(--err-border)}
.error-msg{font-size:.86rem;color:#dc2626;padding:12px 14px 14px 43px}
.card-footer{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
  padding:14px 0 16px 43px;border-top:1px solid var(--border)}
.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 15px;
  border-radius:var(--rs);font-size:.83rem;font-weight:600;
  text-decoration:none;cursor:pointer;border:none;
  transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.97)} .btn:hover{opacity:.85}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary.tracked{background:var(--accent-dark)}
.btn-secondary{background:var(--tag-bg);color:var(--accent);border:1px solid #d0d8ff}
.btn-like{background:var(--like-bg);color:var(--like-c);border:1px solid var(--like-border)}
.btn-like.liked{background:var(--like-active);color:#fff;border-color:var(--like-active)}
.arxiv-id{font-size:.75rem;color:var(--muted);margin-left:auto;padding-right:2px}
.empty-state{text-align:center;padding:70px 20px;color:var(--muted)}
.footer{text-align:center;margin-top:44px;font-size:.78rem;color:var(--muted)}
"""

LIKES_CSS = """
:root{
  --bg:#f4f5fb;--card:#fff;--accent:#f97316;--accent-light:#fff7ed;
  --text:#1a1d2e;--text2:#4e5370;--muted:#9498b0;--border:#e5e8f2;
  --r:12px;--shadow:0 2px 10px rgba(0,0,0,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;padding-bottom:60px}
.header{background:linear-gradient(135deg,#ea580c,#9333ea);color:#fff;
  padding:40px 24px 28px;text-align:center}
.header h1{font-size:1.8rem;font-weight:800}
.header .subtitle{margin-top:6px;font-size:.9rem;opacity:.85}
.header .nav{margin-top:14px;display:flex;gap:14px;justify-content:center}
.header .nav a{color:rgba(255,255,255,.85);text-decoration:none;font-size:.84rem;
  background:rgba(255,255,255,.18);border-radius:100px;padding:3px 14px}
.header .nav a:hover{background:rgba(255,255,255,.3)}
.container{max-width:860px;margin:24px auto;padding:0 18px}
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.toolbar input{flex:1;min-width:200px;padding:8px 14px;border:1px solid var(--border);
  border-radius:var(--r);font-size:.88rem;outline:none}
.toolbar input:focus{border-color:var(--accent)}
.sort-label{font-size:.82rem;color:var(--muted)}
.sort-btn{padding:6px 14px;border:1px solid var(--border);border-radius:100px;
  background:var(--bg);font-size:.8rem;cursor:pointer;transition:all .15s}
.sort-btn.active{background:var(--accent-light);color:var(--accent);border-color:#fed7aa}
.timeline{position:relative;padding-left:20px}
.timeline::before{content:'';position:absolute;left:4px;top:0;bottom:0;
  width:2px;background:linear-gradient(to bottom,#f97316,#c084fc)}
.like-item{display:flex;gap:14px;margin-bottom:16px;position:relative}
.like-item::before{content:'⭐';position:absolute;left:-24px;top:12px;font-size:.8rem}
.item-num{flex-shrink:0;width:26px;height:26px;background:var(--accent-light);
  color:var(--accent);border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:.74rem;font-weight:700;margin-top:14px}
.item-body{flex:1;background:var(--card);border:1px solid var(--border);
  border-radius:var(--r);padding:14px 16px;box-shadow:var(--shadow)}
.item-title a{font-size:.97rem;font-weight:700;color:var(--text);
  text-decoration:none;line-height:1.45;display:block}
.item-title a:hover{color:var(--accent)}
.item-meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;font-size:.78rem}
.like-date{color:var(--accent);font-weight:600}
.arxiv-id{color:var(--muted)}
.snippet{margin-top:8px;font-size:.86rem;color:var(--text2);
  background:var(--bg);border-radius:6px;padding:7px 11px;
  border-left:3px solid #fed7aa}
.loading,.empty{text-align:center;padding:50px 20px;color:var(--muted)}
.footer{text-align:center;margin-top:36px;font-size:.78rem;color:var(--muted)}
"""

SHARED_JS = """
function toggleSection(btn) {
  btn.classList.toggle("open");
  const el = document.getElementById(btn.dataset.target);
  if (el) el.classList.toggle("open");
}

async function checkTracker() {
  const bar = document.getElementById("trackerBar");
  try {
    await fetch(TRACKER + "/track", { method:"OPTIONS", signal:AbortSignal.timeout(1500) });
    bar.textContent = "✅ 追踪已启用 — 点击与点赞将用于关键词优化 · 种子管理: " + TRACKER + "/";
    bar.className = "tracker-bar online";
  } catch {
    bar.textContent = "⚠️ 追踪服务未运行（需先执行 python main.py）— 只读模式";
    bar.className = "tracker-bar";
  }
}
checkTracker();

async function trackAndOpen(event, btn) {
  event.preventDefault();
  const card = btn.closest(".paper-card");
  card.classList.add("clicked-card");
  btn.classList.add("tracked");
  try {
    await fetch(TRACKER + "/track", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        arxiv_id: btn.dataset.arxivId, title: btn.dataset.title,
        action: btn.dataset.action, report_date: REPORT_DATE,
      }),
      signal: AbortSignal.timeout(2000),
    });
  } catch(e) {}
  window.open(btn.dataset.url, "_blank");
}

async function toggleLike(event, btn) {
  event.preventDefault();
  if (btn.classList.contains("liked")) return;   // 已赞，不重复

  btn.classList.add("liked");
  btn.textContent = "⭐ 已赞";
  btn.closest(".paper-card").classList.add("liked-card");

  let authors = [];
  try { authors = JSON.parse(btn.dataset.authors || "[]"); } catch(e) {}
  try {
    const res = await fetch(TRACKER + "/like", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        arxiv_id:        btn.dataset.arxivId,
        title:           btn.dataset.title,
        authors:         authors,
        abs_url:         btn.dataset.absUrl,
        report_date:     REPORT_DATE,
        summary_snippet: btn.dataset.snippet || "",
      }),
      signal: AbortSignal.timeout(3000),
    });
  } catch(e) {
    // 网络失败时回滚
    btn.classList.remove("liked");
    btn.textContent = "👍 点赞";
    btn.closest(".paper-card").classList.remove("liked-card");
  }
}
"""
