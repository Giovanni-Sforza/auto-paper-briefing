"""
report_generator.py — HTML 简报生成模块 v5

新增：
  - 👎 踩按钮（与👍并列）
  - 赞/踩均可再次点击取消（toggle）
  - 点击赞/踩后出现行内评论框（轻量，可填可空，回车/失焦提交）
  - 评论通过 POST /react 携带 comment 字段上报
  - 历史页（reactions_history.html）显示赞/踩分类 + 评论
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
        filepath = os.path.join(self.output_dir, f"Daily_Paper_{today}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._render_daily(papers, today))
        return filepath

    # ── 反应历史（常驻纯前端）────────────────────────────────

    def generate_reactions_history(self) -> str:
        filepath = os.path.join(self.output_dir, "reactions_history.html")
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self._render_reactions_history_frontend())
            logger.info(f"  [Report] 反应历史页已生成（常驻）: {filepath}")
        return filepath

    # 向下兼容旧名称
    def generate_likes_history(self) -> str:
        return self.generate_reactions_history()

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
    <a href="reactions_history.html" class="nav-link">⭐ 反应历史</a>
    <a href="http://127.0.0.1:{port}/" class="nav-link" target="_blank">🌱 种子管理</a>
  </div>
</div>

<div class="container">
  {cards}
  <div class="footer">
    Auto-Paper-Briefing · {date_display} · 客观信息提取，不含主观评价
  </div>
  <div class="footer license-footer">
    Released under the <a href="https://opensource.org/licenses/MIT" target="_blank">MIT License</a> ·
    <a href="https://github.com/Giovanni-Sforza/auto-paper-briefing" target="_blank">GitHub</a> ·
    论文摘要版权归原作者所有，AI 总结仅供参考
  </div>
</div>

<script>
const TRACKER    = "http://127.0.0.1:{port}";
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
        title_attr = title.replace('"','&quot;').replace("'","&#39;")[:120]
        abs_e      = escape(abs_url)
        pdf_e      = escape(pdf_url)
        arxiv_e    = escape(arxiv_id)
        author_str = escape(", ".join(authors[:5]) + ("等" if len(authors) > 5 else ""))
        tags_html  = "".join(f'<span class="tag">{escape(c)}</span>' for c in categories)
        date_html  = f'<span class="date-tag">📅 {escape(published)}</span>' if published else ""

        # 摘要
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

        # AI 总结
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

        snippet_raw  = ""
        if not has_error and summary:
            snippet_raw = str(next(iter(summary.values()), ""))[:100]
        snippet_attr  = snippet_raw.replace('"','&quot;').replace("'","&#39;")
        authors_attr  = json.dumps(authors[:5]).replace('"','&quot;')

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
    <div class="reaction-group" id="rg-{uid}">
      <button class="btn btn-like" id="like-{uid}"
        data-arxiv-id="{arxiv_e}" data-title="{title_attr}"
        data-authors="{authors_attr}" data-abs-url="{abs_e}"
        data-snippet="{snippet_attr}"
        onclick="handleReact(event,this,'like')">👍 赞
      </button>
      <button class="btn btn-dislike" id="dislike-{uid}"
        data-arxiv-id="{arxiv_e}" data-title="{title_attr}"
        data-authors="{authors_attr}" data-abs-url="{abs_e}"
        data-snippet="{snippet_attr}"
        onclick="handleReact(event,this,'dislike')">👎 踩
      </button>
    </div>
    <span class="arxiv-id">arXiv:{arxiv_e}</span>
  </div>

  <!-- 行内评论框（赞/踩后出现）-->
  <div class="comment-bar" id="cb-{uid}" style="display:none">
    <span class="comment-label" id="cl-{uid}"></span>
    <input class="comment-input" id="ci-{uid}" type="text"
      placeholder="添加评论，帮助 AI 更准确地理解你的偏好（可留空）"
      data-arxiv-id="{arxiv_e}" data-uid="{uid}"
      onkeydown="commentKeydown(event,this)"
      onblur="submitComment(this)">
    <button class="comment-ok" onclick="submitComment(document.getElementById('ci-{uid}'))">确定</button>
    <button class="comment-skip" onclick="hideComment('{uid}')">跳过</button>
  </div>
</div>"""

    # ─────────────────────────────────────────────────────────
    # 反应历史（纯前端）
    # ─────────────────────────────────────────────────────────

    def _render_reactions_history_frontend(self) -> str:
        port = self.tracker_port
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>反应历史 · Auto-Paper-Briefing</title>
<style>{REACTIONS_CSS}</style>
</head>
<body>
<div class="header">
  <h1>⭐ 反应历史</h1>
  <div class="subtitle" id="subtitle">加载中…</div>
  <div class="nav">
    <a href="javascript:history.back()">← 返回简报</a>
    <a href="http://127.0.0.1:{port}/" target="_blank">🌱 种子管理</a>
  </div>
</div>

<div class="container">
  <div class="toolbar">
    <input type="text" id="searchBox" placeholder="🔍 搜索标题或作者…" oninput="renderList()">
    <div class="filter-group">
      <button class="filter-btn active" data-filter="all"   onclick="setFilter('all')">全部</button>
      <button class="filter-btn"        data-filter="like"  onclick="setFilter('like')">👍 赞</button>
      <button class="filter-btn"        data-filter="dislike" onclick="setFilter('dislike')">👎 踩</button>
    </div>
    <div class="sort-group">
      <button class="sort-btn active" id="sortNew" onclick="setSort('new')">最新</button>
      <button class="sort-btn"        id="sortOld" onclick="setSort('old')">最早</button>
    </div>
  </div>

  <div class="stats-bar" id="statsBar"></div>
  <div class="timeline" id="listEl"><div class="loading">⏳ 加载中…</div></div>
  <div class="footer">反应历史实时从本地服务读取 · Auto-Paper-Briefing</div>
</div>

<script>
const API = "http://127.0.0.1:{port}";
let allReactions = [];
let sortOrder = "new";
let filterType = "all";

async function load() {{
  try {{
    allReactions = await (await fetch(API + "/api/reactions")).json();
    updateStats();
    renderList();
  }} catch(e) {{
    document.getElementById("listEl").innerHTML = '<div class="empty">⚠️ 无法连接服务，请先运行 python main.py</div>';
    document.getElementById("subtitle").textContent = "服务未运行";
  }}
}}

function updateStats() {{
  const likes    = allReactions.filter(r => r.reaction === "like").length;
  const dislikes = allReactions.filter(r => r.reaction === "dislike").length;
  const cancelled= allReactions.filter(r => r.reaction === null).length;
  document.getElementById("subtitle").textContent =
    `共 ${{allReactions.length}} 条记录 · 👍 ${{likes}} · 👎 ${{dislikes}} · 已取消 ${{cancelled}}`;
  document.getElementById("statsBar").textContent = "";
}}

function setFilter(f) {{
  filterType = f;
  document.querySelectorAll(".filter-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.filter === f));
  renderList();
}}

function setSort(order) {{
  sortOrder = order;
  document.getElementById("sortNew").classList.toggle("active", order==="new");
  document.getElementById("sortOld").classList.toggle("active", order==="old");
  renderList();
}}

function renderList() {{
  const q = document.getElementById("searchBox").value.toLowerCase();
  let list = allReactions.filter(r => {{
    const matchText = (r.title||"").toLowerCase().includes(q) ||
                      (r.authors||[]).join(" ").toLowerCase().includes(q);
    const matchFilter = filterType === "all" ||
                        (filterType === "like" && r.reaction === "like") ||
                        (filterType === "dislike" && r.reaction === "dislike");
    return matchText && matchFilter;
  }});
  if (sortOrder === "old") list = [...list].reverse();

  const el = document.getElementById("listEl");
  if (!list.length) {{
    el.innerHTML = allReactions.length
      ? '<div class="empty">🔍 没有匹配的结果</div>'
      : '<div class="empty">💭 还没有任何反应记录，去简报页点赞/踩吧</div>';
    return;
  }}

  el.innerHTML = list.map((r, i) => {{
    const reactionInfo = r.reaction === "like"
      ? {{emoji:"👍", cls:"like", label:"赞"}}
      : r.reaction === "dislike"
      ? {{emoji:"👎", cls:"dislike", label:"踩"}}
      : {{emoji:"↩️", cls:"cancelled", label:"已取消"}};
    const date    = formatDate(r.reacted_at);
    const auth    = (r.authors||[]).slice(0,3).join(", ") + ((r.authors||[]).length>3?" 等":"");
    const comment = r.comment
      ? `<div class="comment-display ${{reactionInfo.cls}}">${{esc(r.comment)}}</div>` : "";
    const snip    = !r.comment && r.summary_snippet
      ? `<div class="snippet">${{esc(r.summary_snippet)}}</div>` : "";
    return `
<div class="reaction-item">
  <div class="item-num">${{i+1}}</div>
  <div class="item-body">
    <div class="item-title">
      <span class="reaction-badge ${{reactionInfo.cls}}">${{reactionInfo.emoji}} ${{reactionInfo.label}}</span>
      <a href="${{esc(r.abs_url)}}" target="_blank">${{esc(r.title)}}</a>
    </div>
    <div class="item-meta">
      <span>👤 ${{esc(auth)||'（作者未知）'}}</span>
      <span class="reaction-date">${{date}}</span>
      <span class="arxiv-id">arXiv:${{esc(r.arxiv_id)}}</span>
    </div>
    ${{comment}}${{snip}}
  </div>
</div>`;
  }}).join("");
}}

function formatDate(iso) {{
  if (!iso) return "";
  try {{
    const d = new Date(iso);
    return d.getFullYear()+"年"+String(d.getMonth()+1).padStart(2,"0")+"月"+
           String(d.getDate()).padStart(2,"0")+"日 "+
           String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0");
  }} catch {{ return iso.slice(0,16); }}
}}

function esc(s) {{
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

load();
setInterval(load, 30000);
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

DAILY_CSS = """
:root{
  --bg:#f4f5fb;--card:#fff;--accent:#4f6ef7;--accent-dark:#3a56d4;
  --accent-light:#eef1ff;--text:#1a1d2e;--text2:#4e5370;--muted:#9498b0;
  --border:#e5e8f2;--tag-bg:#eff1ff;--tag-c:#4f6ef7;
  --like-bg:#f0fdf4;--like-c:#16a34a;--like-border:#bbf7d0;--like-active:#16a34a;
  --dislike-bg:#fff5f5;--dislike-c:#dc2626;--dislike-border:#fca5a5;--dislike-active:#dc2626;
  --comment-bg:#fffbeb;--comment-border:#fde68a;
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
.header{background:linear-gradient(135deg,#3a56d4,#6d28d9);color:#fff;padding:44px 24px 36px;text-align:center}
.header h1{font-size:1.9rem;font-weight:800;letter-spacing:-.5px}
.header .subtitle{margin-top:6px;font-size:.95rem;opacity:.8}
.header .stats{display:inline-flex;gap:16px;flex-wrap:wrap;justify-content:center;align-items:center;
  margin-top:18px;background:rgba(255,255,255,.14);border-radius:100px;padding:8px 22px;font-size:.86rem}
.header .stats span{opacity:.88}.header .stats strong{opacity:1}
.nav-link{color:#fff;text-decoration:none;background:rgba(255,255,255,.2);border-radius:100px;
  padding:3px 13px;font-size:.82rem;font-weight:600;white-space:nowrap}
.nav-link:hover{background:rgba(255,255,255,.32)}
.container{max-width:920px;margin:28px auto 0;padding:0 18px}
.paper-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:24px 26px 0;margin-bottom:18px;box-shadow:var(--shadow-sm);
  transition:box-shadow .2s,border-color .2s;overflow:hidden}
.paper-card:hover{box-shadow:var(--shadow-md);border-color:#c5ceff}
.paper-card.clicked-card{border-left:3px solid var(--accent)}
.paper-card.liked-card{border-left:3px solid var(--like-active)}
.paper-card.disliked-card{border-left:3px solid var(--dislike-active)}
.card-top{display:flex;align-items:flex-start;gap:13px;margin-bottom:12px}
.paper-index{flex-shrink:0;width:30px;height:30px;background:var(--accent-light);color:var(--accent);
  border-radius:var(--rs);display:flex;align-items:center;justify-content:center;font-size:.82rem;font-weight:700}
.paper-title{font-size:1.06rem;font-weight:700;color:var(--text);line-height:1.45;flex:1}
.read-badge{flex-shrink:0;font-size:.7rem;padding:2px 8px;background:var(--accent-light);color:var(--accent);
  border-radius:100px;font-weight:600;align-self:flex-start;margin-top:4px;display:none}
.paper-card.clicked-card .read-badge{display:inline-block}
.meta-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px;padding-left:43px}
.authors{font-size:.86rem;color:var(--text2);flex:1;min-width:180px}
.tags{display:flex;gap:5px;flex-wrap:wrap}
.tag{font-size:.73rem;background:var(--tag-bg);color:var(--tag-c);padding:2px 8px;border-radius:100px;font-weight:600}
.date-tag{font-size:.75rem;color:var(--muted);background:var(--bg);padding:2px 8px;border-radius:100px;border:1px solid var(--border)}
.section-toggle{width:100%;background:none;border:none;cursor:pointer;text-align:left;
  padding:10px 0 10px 43px;display:flex;align-items:center;gap:7px;
  font-size:.82rem;font-weight:600;color:var(--muted);border-top:1px solid var(--border);transition:color .15s}
.section-toggle:hover{color:var(--accent)}
.arrow{font-size:.65rem;transition:transform .2s;display:inline-block}
.section-toggle.open .arrow{transform:rotate(90deg)}
.toggle-count{margin-left:auto;padding-right:4px;font-weight:400;font-size:.75rem;color:var(--muted)}
.collapsible{overflow:hidden;max-height:0;transition:max-height .35s ease}
.collapsible.open{max-height:4000px}
.abstract-body{padding:12px 14px 16px 43px;font-size:.9rem;color:var(--text2);
  background:var(--abs-bg);border-top:1px solid var(--border);line-height:1.75}
.abstract-label{font-size:.73rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}
.summary-body{padding:14px 14px 16px 43px}
.summary-item{margin-bottom:13px}
.dim-label{font-size:.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}
.dim-content{font-size:.9rem;color:var(--text2);background:var(--bg);border-radius:var(--rs);
  padding:9px 13px;border-left:3px solid var(--accent-light);line-height:1.7}
.error-card{background:var(--err-bg);border-color:var(--err-border)}
.error-msg{font-size:.86rem;color:#dc2626;padding:12px 14px 14px 43px}
.card-footer{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
  padding:14px 0 14px 43px;border-top:1px solid var(--border)}
.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 15px;border-radius:var(--rs);
  font-size:.83rem;font-weight:600;text-decoration:none;cursor:pointer;border:none;
  transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.97)}.btn:hover{opacity:.85}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary.tracked{background:var(--accent-dark)}
.btn-secondary{background:var(--tag-bg);color:var(--accent);border:1px solid #d0d8ff}
.reaction-group{display:inline-flex;gap:4px;border:1px solid var(--border);border-radius:var(--rs);overflow:hidden}
.reaction-group .btn{border-radius:0;border:none;margin:0}
.btn-like{background:var(--like-bg);color:var(--like-c);border:none}
.btn-like.active{background:var(--like-active);color:#fff}
.btn-dislike{background:var(--dislike-bg);color:var(--dislike-c);border:none}
.btn-dislike.active{background:var(--dislike-active);color:#fff}
.arxiv-id{font-size:.75rem;color:var(--muted);margin-left:auto;padding-right:2px}
/* 评论栏 */
.comment-bar{display:flex;align-items:center;gap:8px;padding:10px 14px 12px 43px;
  background:var(--comment-bg);border-top:1px solid var(--comment-border);flex-wrap:wrap}
.comment-label{font-size:.8rem;color:#92400e;font-weight:600;white-space:nowrap}
.comment-input{flex:1;min-width:160px;padding:6px 10px;border:1px solid var(--comment-border);
  border-radius:var(--rs);font-size:.85rem;outline:none;background:#fff}
.comment-input:focus{border-color:#f59e0b}
.comment-ok{padding:5px 12px;background:#f59e0b;color:#fff;border:none;border-radius:var(--rs);
  font-size:.82rem;font-weight:600;cursor:pointer}
.comment-ok:hover{opacity:.88}
.comment-skip{padding:5px 10px;background:none;border:1px solid var(--border);color:var(--muted);
  border-radius:var(--rs);font-size:.82rem;cursor:pointer}
.comment-skip:hover{color:var(--text)}
.empty-state{text-align:center;padding:70px 20px;color:var(--muted)}
.footer{text-align:center;margin-top:44px;font-size:.78rem;color:var(--muted)}
.license-footer{margin-top:8px;font-size:.74rem}
.license-footer a{color:var(--accent);text-decoration:none}
.license-footer a:hover{text-decoration:underline}
"""

REACTIONS_CSS = """
:root{
  --bg:#f4f5fb;--card:#fff;--text:#1a1d2e;--text2:#4e5370;--muted:#9498b0;
  --border:#e5e8f2;--like-c:#16a34a;--like-bg:#f0fdf4;--like-border:#bbf7d0;
  --dislike-c:#dc2626;--dislike-bg:#fff5f5;--dislike-border:#fca5a5;
  --cancelled-c:#9498b0;--cancelled-bg:#f4f5fb;
  --r:12px;--shadow:0 2px 10px rgba(0,0,0,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;padding-bottom:60px}
.header{background:linear-gradient(135deg,#1d4ed8,#7c3aed);color:#fff;padding:40px 24px 28px;text-align:center}
.header h1{font-size:1.8rem;font-weight:800}
.header .subtitle{margin-top:6px;font-size:.9rem;opacity:.85}
.header .nav{margin-top:14px;display:flex;gap:14px;justify-content:center}
.header .nav a{color:rgba(255,255,255,.85);text-decoration:none;font-size:.84rem;
  background:rgba(255,255,255,.18);border-radius:100px;padding:3px 14px}
.header .nav a:hover{background:rgba(255,255,255,.3)}
.container{max-width:860px;margin:24px auto;padding:0 18px}
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.toolbar input{flex:1;min-width:180px;padding:8px 14px;border:1px solid var(--border);
  border-radius:var(--r);font-size:.88rem;outline:none}
.toolbar input:focus{border-color:#6366f1}
.filter-group,.sort-group{display:flex;gap:4px}
.filter-btn,.sort-btn{padding:6px 13px;border:1px solid var(--border);border-radius:100px;
  background:var(--bg);font-size:.8rem;cursor:pointer;transition:all .15s;font-weight:500}
.filter-btn.active,.sort-btn.active{background:#6366f1;color:#fff;border-color:#6366f1}
.timeline{position:relative;padding-left:20px}
.timeline::before{content:'';position:absolute;left:4px;top:0;bottom:0;
  width:2px;background:linear-gradient(to bottom,#4f6ef7,#dc2626)}
.reaction-item{display:flex;gap:14px;margin-bottom:14px;position:relative}
.item-num{flex-shrink:0;width:26px;height:26px;background:#eef1ff;color:#4f6ef7;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:.74rem;font-weight:700;margin-top:14px}
.item-body{flex:1;background:var(--card);border:1px solid var(--border);
  border-radius:var(--r);padding:14px 16px;box-shadow:var(--shadow)}
.item-title{display:flex;align-items:flex-start;gap:8px;margin-bottom:6px}
.reaction-badge{flex-shrink:0;font-size:.72rem;font-weight:700;padding:2px 9px;
  border-radius:100px;white-space:nowrap;margin-top:2px}
.reaction-badge.like{background:var(--like-bg);color:var(--like-c);border:1px solid var(--like-border)}
.reaction-badge.dislike{background:var(--dislike-bg);color:var(--dislike-c);border:1px solid var(--dislike-border)}
.reaction-badge.cancelled{background:var(--cancelled-bg);color:var(--cancelled-c);border:1px solid var(--border)}
.item-title a{font-size:.97rem;font-weight:700;color:var(--text);text-decoration:none;line-height:1.4}
.item-title a:hover{color:#4f6ef7}
.item-meta{display:flex;flex-wrap:wrap;gap:10px;font-size:.78rem;color:var(--text2)}
.reaction-date{font-weight:600;color:#6366f1}
.arxiv-id{color:var(--muted)}
.comment-display{margin-top:8px;font-size:.87rem;padding:7px 11px;border-radius:6px;font-style:italic}
.comment-display.like{background:var(--like-bg);color:var(--like-c);border-left:3px solid var(--like-border)}
.comment-display.dislike{background:var(--dislike-bg);color:var(--dislike-c);border-left:3px solid var(--dislike-border)}
.snippet{margin-top:8px;font-size:.86rem;color:var(--text2);background:var(--bg);
  border-radius:6px;padding:7px 11px;border-left:3px solid var(--border)}
.loading,.empty{text-align:center;padding:50px 20px;color:var(--muted)}
.footer{text-align:center;margin-top:36px;font-size:.78rem;color:var(--muted)}
"""

# ─────────────────────────────────────────────────────────────
# 共享 JS
# ─────────────────────────────────────────────────────────────

SHARED_JS = """
// ── 折叠 ────────────────────────────────────────────────────
function toggleSection(btn) {
  btn.classList.toggle("open");
  const el = document.getElementById(btn.dataset.target);
  if (el) el.classList.toggle("open");
}

// ── Tracker 心跳 ────────────────────────────────────────────
async function checkTracker() {
  const bar = document.getElementById("trackerBar");
  try {
    await fetch(TRACKER + "/track", { method:"OPTIONS", signal:AbortSignal.timeout(1500) });
    bar.textContent = "✅ 追踪已启用 — 点击、赞/踩与评论将用于关键词优化";
    bar.className = "tracker-bar online";
  } catch {
    bar.textContent = "⚠️ 追踪服务未运行（需先执行 python main.py）— 只读模式";
    bar.className = "tracker-bar";
  }
}
checkTracker();

// ── 点击上报 + 跳转 ─────────────────────────────────────────
async function trackAndOpen(event, btn) {
  event.preventDefault();
  const card = btn.closest(".paper-card");
  card.classList.add("clicked-card");
  btn.classList.add("tracked");
  try {
    await fetch(TRACKER + "/track", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ arxiv_id:btn.dataset.arxivId, title:btn.dataset.title,
                             action:btn.dataset.action, report_date:REPORT_DATE }),
      signal: AbortSignal.timeout(2000),
    });
  } catch(e) {}
  window.open(btn.dataset.url, "_blank");
}

// ── 赞/踩（支持取消）───────────────────────────────────────
// currentReaction[arxivId] = "like" | "dislike" | null
const currentReaction = {};

async function handleReact(event, btn, action) {
  event.preventDefault();
  const arxivId = btn.dataset.arxivId;
  const card    = btn.closest(".paper-card");
  const uid     = btn.id.replace(/^(like|dislike)-/, "");

  const prev = currentReaction[arxivId] || null;

  // 判断是否为取消操作（再次点击已激活的按钮）
  const isCancel = (prev === action);
  const finalAction = isCancel ? "cancel" : action;

  // 乐观更新 UI
  _updateReactionUI(uid, card, isCancel ? null : action);

  // 发送请求
  let authors = [];
  try { authors = JSON.parse(btn.dataset.authors || "[]"); } catch(e) {}

  try {
    const res = await fetch(TRACKER + "/react", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        arxiv_id:        arxivId,
        action:          finalAction,
        title:           btn.dataset.title,
        authors:         authors,
        abs_url:         btn.dataset.absUrl,
        report_date:     REPORT_DATE,
        summary_snippet: btn.dataset.snippet || "",
        comment:         "",    // 评论通过 comment-bar 单独提交
      }),
      signal: AbortSignal.timeout(3000),
    });
    const data = await res.json();
    // 以服务端返回为准
    const serverReaction = data.reaction;
    currentReaction[arxivId] = serverReaction;
    _updateReactionUI(uid, card, serverReaction);

    // 显示评论栏（取消时隐藏）
    if (serverReaction !== null) {
      _showCommentBar(uid, serverReaction);
    } else {
      _hideCommentBar(uid);
    }
  } catch(e) {
    // 回滚
    _updateReactionUI(uid, card, prev);
  }
}

function _updateReactionUI(uid, card, reaction) {
  const likeBtn    = document.getElementById("like-" + uid);
  const dislikeBtn = document.getElementById("dislike-" + uid);
  if (!likeBtn || !dislikeBtn) return;

  likeBtn.classList.toggle("active",    reaction === "like");
  dislikeBtn.classList.toggle("active", reaction === "dislike");
  card.classList.toggle("liked-card",    reaction === "like");
  card.classList.toggle("disliked-card", reaction === "dislike");

  // 按钮文字
  likeBtn.textContent    = reaction === "like"    ? "👍 已赞" : "👍 赞";
  dislikeBtn.textContent = reaction === "dislike" ? "👎 已踩" : "👎 踩";
}

// ── 评论栏 ──────────────────────────────────────────────────

function _showCommentBar(uid, reaction) {
  const bar   = document.getElementById("cb-" + uid);
  const label = document.getElementById("cl-" + uid);
  if (!bar) return;
  label.textContent = reaction === "like" ? "💬 为什么喜欢？" : "💬 为什么不感兴趣？";
  bar.style.display = "flex";
  setTimeout(() => document.getElementById("ci-" + uid)?.focus(), 50);
}

function _hideCommentBar(uid) {
  const bar = document.getElementById("cb-" + uid);
  if (bar) bar.style.display = "none";
}

function hideComment(uid) {
  _hideCommentBar(uid);
}

function commentKeydown(event, input) {
  if (event.key === "Enter") {
    event.preventDefault();
    submitComment(input);
  }
  if (event.key === "Escape") {
    hideComment(input.dataset.uid);
  }
}

// blur 时延迟 150ms 再提交，避免点"确定"时 blur 和 click 冲突
let _blurTimer = null;
function submitComment(input) {
  clearTimeout(_blurTimer);
  _blurTimer = setTimeout(() => _doSubmitComment(input), 150);
}

async function _doSubmitComment(input) {
  const comment = input.value.trim();
  const uid     = input.dataset.uid;
  const arxivId = input.dataset.arxivId;

  _hideCommentBar(uid);

  if (!comment) return;   // 空评论跳过请求

  const reaction = currentReaction[arxivId] || "like";
  try {
    await fetch(TRACKER + "/react", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        arxiv_id: arxivId,
        action:   reaction,
        comment:  comment,
        report_date: REPORT_DATE,
      }),
      signal: AbortSignal.timeout(3000),
    });
  } catch(e) {}
}
"""
