"""
click_tracker.py — 统一本地服务 v5

路由总览：
  POST   /track              — 记录点击到 clicks.json
  POST   /react              — 赞/踩/取消/评论 → reactions.json
  GET    /api/reactions      — 返回 reactions.json（供前端实时读取）
  GET    /api/seeds          — 返回 seeds.json
  POST   /api/seeds          — 添加/升档种子文章
  DELETE /api/seeds/<id>     — 删除种子文章
  GET    /                   — 种子管理 Web UI
  OPTIONS *                  — CORS 预检

reactions.json 结构（dict，key=arxiv_id）：
  {
    "2401.12345": {
      "arxiv_id":        "2401.12345",
      "title":           "...",
      "authors":         [...],
      "abs_url":         "...",
      "reaction":        "like" | "dislike" | null,   ← null = 已取消
      "comment":         "用户填写的评论",
      "summary_snippet": "...",
      "reacted_at":      "2024-01-15T10:00:00",
      "updated_at":      "2024-01-15T10:05:00",
      "report_date":     "20240115"
    }
  }
"""

import json
import os
import re
import logging
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)
DEFAULT_PORT = 19523

LEVELS = {
    1: {"name": "普通推荐", "emoji": "📌", "weight": 1.0},
    2: {"name": "重要",     "emoji": "⭐", "weight": 3.0},
    3: {"name": "核心必读", "emoji": "🔥", "weight": 6.0},
}


def _parse_arxiv_id(raw: str) -> str | None:
    raw = raw.strip()
    m = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})', raw, re.I)
    if m:
        return m.group(1).split("v")[0]
    m = re.match(r'^([0-9]{4}\.[0-9]{4,5})', raw)
    if m:
        return m.group(1)
    return None


def _fetch_arxiv_meta(arxiv_id: str) -> dict:
    NS = {"atom": "http://www.w3.org/2005/Atom"}
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoPaperBriefing/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            root = ET.fromstring(resp.read())
        entry = root.find("atom:entry", NS)
        if entry is None:
            return {}
        title   = entry.find("atom:title", NS)
        authors = entry.findall("atom:author", NS)
        return {
            "title":   title.text.strip().replace("\n", " ") if title is not None else "",
            "authors": [a.find("atom:name", NS).text.strip()
                        for a in authors if a.find("atom:name", NS) is not None],
        }
    except Exception as e:
        logger.warning(f"  [Tracker] 元数据获取失败 ({arxiv_id}): {e}")
        return {}


class _Handler(BaseHTTPRequestHandler):
    clicks_file:      str  = ""
    reactions_file:   str  = ""   # 新：统一的赞/踩/评论文件
    seeds_file:       str  = ""
    history_file:     str  = ""   # 用于导出
    react_callbacks:  list = []   # 点赞/踩回调

    # ── 路由分发 ─────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]
        if   path == "/":                self._serve_seed_ui()
        elif path == "/api/reactions":   self._api_get_reactions()
        elif path == "/api/seeds":       self._api_get_seeds()
        elif path == "/api/clicks":      self._api_get_clicks()
        elif path == "/api/export":      self._api_export_all()
        else:                            self._respond(404, "Not Found")

    def do_POST(self):
        body = self._read_body()
        path = self.path.split("?")[0]
        if   path == "/track":      self._handle_click(body)
        elif path == "/react":      self._handle_react(body)
        elif path == "/api/seeds":  self._api_add_seed(body)
        else:                       self._respond(404, "Not Found")

    def do_DELETE(self):
        if self.path.startswith("/api/seeds/"):
            self._api_delete_seed(self.path[len("/api/seeds/"):])
        else:
            self._respond(404, "Not Found")

    def do_OPTIONS(self):
        self._respond(200, "OK")

    # ── /track ───────────────────────────────────────────────

    def _handle_click(self, data: dict):
        try:
            records = self._load_list(self.__class__.clicks_file)
            records.append({
                "arxiv_id":    data.get("arxiv_id", ""),
                "title":       data.get("title", ""),
                "action":      data.get("action", "unknown"),
                "clicked_at":  datetime.now().isoformat(),
                "report_date": data.get("report_date", ""),
            })
            self._save_json(self.__class__.clicks_file, records)
            logger.info(f"  [Tracker] click [{data.get('action')}] {data.get('arxiv_id')} — {data.get('title','')[:40]}")
            self._respond(200, "OK")
        except Exception as e:
            self._respond(500, str(e))

    # ── /react ───────────────────────────────────────────────
    # payload: { arxiv_id, action("like"|"dislike"|"cancel"),
    #            title, authors, abs_url, summary_snippet,
    #            comment, report_date }

    def _handle_react(self, data: dict):
        try:
            arxiv_id = data.get("arxiv_id", "")
            action   = data.get("action", "")    # "like" | "dislike" | "cancel"
            comment  = data.get("comment", "").strip()
            now      = datetime.now().isoformat()

            if action not in ("like", "dislike", "cancel"):
                self._respond_json(400, {"error": f"未知 action: {action}"})
                return

            reactions = self._load_dict(self.__class__.reactions_file)

            if arxiv_id in reactions:
                rec = reactions[arxiv_id]
                old_reaction = rec.get("reaction")

                if action == "cancel":
                    rec["reaction"]   = None
                    rec["updated_at"] = now
                    log_tag = "cancel"
                else:
                    rec["reaction"]   = action
                    rec["updated_at"] = now
                    if comment:
                        rec["comment"] = comment
                    log_tag = action

                reactions[arxiv_id] = rec
                self._save_json(self.__class__.reactions_file, reactions)
                logger.info(f"  [Tracker] react [{log_tag}] {arxiv_id} — {rec['title'][:40]}")
                self._fire_callbacks(rec)
                self._respond_json(200, {"ok": True, "is_new": False,
                                         "reaction": rec["reaction"]})
            else:
                # 首次对这篇文章做出反应
                if action == "cancel":
                    # 取消一个从未存在的记录，直接忽略
                    self._respond_json(200, {"ok": True, "is_new": False, "reaction": None})
                    return

                rec = {
                    "arxiv_id":        arxiv_id,
                    "title":           data.get("title", ""),
                    "authors":         data.get("authors", []),
                    "abs_url":         data.get("abs_url",
                                                f"https://arxiv.org/abs/{arxiv_id}"),
                    "reaction":        action,           # "like" | "dislike"
                    "comment":         comment,
                    "summary_snippet": data.get("summary_snippet", ""),
                    "reacted_at":      now,
                    "updated_at":      now,
                    "report_date":     data.get("report_date", ""),
                }
                reactions[arxiv_id] = rec
                self._save_json(self.__class__.reactions_file, reactions)
                logger.info(f"  [Tracker] react [{action}] {arxiv_id} — {rec['title'][:40]}")
                self._fire_callbacks(rec)
                self._respond_json(200, {"ok": True, "is_new": True,
                                         "reaction": rec["reaction"]})
        except Exception as e:
            logger.warning(f"  [Tracker] react 失败: {e}")
            self._respond(500, str(e))

    def _fire_callbacks(self, record: dict):
        for cb in self.__class__.react_callbacks:
            try:
                cb(record)
            except Exception:
                pass

    # ── GET /api/reactions ───────────────────────────────────

    def _api_get_reactions(self):
        reactions = self._load_dict(self.__class__.reactions_file)
        # 返回列表，按 reacted_at 倒序（最新在前）
        lst = sorted(reactions.values(),
                     key=lambda r: r.get("reacted_at", ""), reverse=True)
        self._respond_json(200, lst)

    # ── GET /api/clicks ──────────────────────────────────────

    def _api_get_clicks(self):
        self._respond_json(200, self._load_list(self.__class__.clicks_file))

    # ── GET /api/export ──────────────────────────────────────

    def _api_export_all(self):
        """聚合所有数据文件，返回完整 JSON 供前端触发下载"""
        from datetime import datetime as _dt
        data = {
            "exported_at": _dt.now().isoformat(),
            "reactions":   self._load_dict(self.__class__.reactions_file),
            "seeds":       self._load_dict(self.__class__.seeds_file),
            "history":     self._load_dict(self.__class__.history_file),
            "clicks":      self._load_list(self.__class__.clicks_file),
        }
        logger.info(
            f"  [Tracker] 导出: "
            f"{len(data['reactions'])} 条反应 / "
            f"{len(data['seeds'])} 篇种子 / "
            f"{len(data['history'])} 条历史 / "
            f"{len(data['clicks'])} 条点击"
        )
        self._respond_json(200, data)

    # ── Seeds CRUD ───────────────────────────────────────────

    def _api_get_seeds(self):
        seeds = self._load_dict(self.__class__.seeds_file)
        lst = sorted(seeds.values(), key=lambda x: -x.get("weight", 1))
        self._respond_json(200, lst)

    def _api_add_seed(self, data: dict):
        url_or_id = data.get("url_or_id", "").strip()
        level     = max(1, min(3, int(data.get("level", 1))))
        note      = data.get("note", "").strip()

        arxiv_id = _parse_arxiv_id(url_or_id)
        if not arxiv_id:
            self._respond_json(400, {"error": f"无法解析 arXiv ID: {url_or_id!r}"})
            return

        seeds = self._load_dict(self.__class__.seeds_file)
        now   = datetime.now().isoformat()

        if arxiv_id in seeds:
            old = seeds[arxiv_id]
            if level > old["level"]:
                old["level"]      = level
                old["weight"]     = LEVELS[level]["weight"]
                old["updated_at"] = now
                if note:
                    old["note"] = note
                self._save_json(self.__class__.seeds_file, seeds)
                self._respond_json(200, {"status": "upgraded", "record": old})
            else:
                self._respond_json(200, {"status": "exists", "record": old})
            return

        meta = _fetch_arxiv_meta(arxiv_id)
        record = {
            "arxiv_id":   arxiv_id,
            "title":      meta.get("title", "（元数据获取失败）"),
            "authors":    meta.get("authors", []),
            "level":      level,
            "weight":     LEVELS[level]["weight"],
            "note":       note,
            "abs_url":    f"https://arxiv.org/abs/{arxiv_id}",
            "added_at":   now,
            "updated_at": now,
        }
        seeds[arxiv_id] = record
        self._save_json(self.__class__.seeds_file, seeds)
        logger.info(f"  [Tracker] seed 添加 [Lv{level}] {arxiv_id} — {record['title'][:45]}")
        self._respond_json(200, {"status": "added", "record": record})

    def _api_delete_seed(self, arxiv_id: str):
        seeds = self._load_dict(self.__class__.seeds_file)
        if arxiv_id.strip() in seeds:
            del seeds[arxiv_id.strip()]
            self._save_json(self.__class__.seeds_file, seeds)
            self._respond_json(200, {"ok": True})
        else:
            self._respond_json(404, {"error": "not found"})

    # ── 种子管理 Web UI ──────────────────────────────────────

    def _serve_seed_ui(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(SEED_UI_HTML.encode("utf-8"))

    # ── 工具方法 ─────────────────────────────────────────────

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            return json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return {}

    def _respond(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(msg.encode())

    def _respond_json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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

    def _save_json(self, path: str, data):
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def log_message(self, *args):
        pass


# ─────────────────────────────────────────────────────────────
# 种子管理 UI（不变，复用之前版本）
# ─────────────────────────────────────────────────────────────

SEED_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>种子文章管理 · Auto-Paper-Briefing</title>
<style>
:root{
  --bg:#f4f5fb;--card:#fff;--accent:#4f6ef7;--accent-light:#eef1ff;
  --text:#1a1d2e;--muted:#9498b0;--border:#e5e8f2;
  --lv1-bg:#f0f9ff;--lv1-c:#0369a1;--lv1-border:#bae6fd;
  --lv2-bg:#fefce8;--lv2-c:#a16207;--lv2-border:#fde047;
  --lv3-bg:#fff7ed;--lv3-c:#c2410c;--lv3-border:#fb923c;
  --radius:12px;--shadow:0 2px 10px rgba(0,0,0,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;padding-bottom:60px}
.header{background:linear-gradient(135deg,#3a56d4,#7c3aed);color:#fff;
  padding:36px 24px 28px;text-align:center}
.header h1{font-size:1.7rem;font-weight:800}
.header .subtitle{margin-top:6px;opacity:.82;font-size:.9rem}
.container{max-width:820px;margin:28px auto;padding:0 18px}
.add-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:24px;margin-bottom:24px;box-shadow:var(--shadow)}
.add-card h2{font-size:1rem;font-weight:700;margin-bottom:16px;color:var(--accent)}
.form-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.form-row input[type=text]{flex:1;min-width:220px;padding:9px 12px;border:1px solid var(--border);
  border-radius:8px;font-size:.9rem;outline:none;transition:border .15s}
.form-row input[type=text]:focus{border-color:var(--accent)}
.level-group{display:flex;gap:8px}
.level-btn{padding:8px 14px;border:2px solid var(--border);border-radius:8px;
  cursor:pointer;font-size:.83rem;font-weight:600;background:var(--bg);transition:all .15s;white-space:nowrap}
.level-btn[data-lv="1"].active{background:var(--lv1-bg);color:var(--lv1-c);border-color:var(--lv1-border)}
.level-btn[data-lv="2"].active{background:var(--lv2-bg);color:var(--lv2-c);border-color:var(--lv2-border)}
.level-btn[data-lv="3"].active{background:var(--lv3-bg);color:var(--lv3-c);border-color:var(--lv3-border)}
.note-row{display:flex;gap:10px}
.note-row input{flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:.87rem;outline:none}
.note-row input:focus{border-color:var(--accent)}
.submit-btn{padding:9px 22px;background:var(--accent);color:#fff;border:none;border-radius:8px;
  font-size:.9rem;font-weight:700;cursor:pointer;transition:opacity .15s,transform .1s}
.submit-btn:hover{opacity:.88}.submit-btn:active{transform:scale(.97)}.submit-btn:disabled{opacity:.5;cursor:not-allowed}
.status-msg{margin-top:10px;font-size:.85rem;min-height:20px;border-radius:6px;padding:6px 10px}
.status-msg.ok{color:#166534;background:#f0fdf4}.status-msg.err{color:#991b1b;background:#fff5f5}
.status-msg.warn{color:#92400e;background:#fffbeb}
.list-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.list-header h2{font-size:1rem;font-weight:700}
.count-badge{font-size:.8rem;background:var(--accent-light);color:var(--accent);padding:2px 10px;border-radius:100px;font-weight:600}
.empty{text-align:center;padding:40px 20px;color:var(--muted)}
.seed-item{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 18px;margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;box-shadow:var(--shadow)}
.level-badge{flex-shrink:0;font-size:.75rem;font-weight:700;padding:3px 10px;border-radius:100px;white-space:nowrap}
.lv1{background:var(--lv1-bg);color:var(--lv1-c);border:1px solid var(--lv1-border)}
.lv2{background:var(--lv2-bg);color:var(--lv2-c);border:1px solid var(--lv2-border)}
.lv3{background:var(--lv3-bg);color:var(--lv3-c);border:1px solid var(--lv3-border)}
.seed-body{flex:1;min-width:0}
.seed-title a{font-size:.95rem;font-weight:700;color:var(--text);text-decoration:none;line-height:1.4;display:block}
.seed-title a:hover{color:var(--accent)}
.seed-meta{font-size:.78rem;color:var(--muted);margin-top:5px;display:flex;gap:12px;flex-wrap:wrap}
.seed-note{font-size:.82rem;color:#6366f1;margin-top:4px;background:#f5f3ff;border-radius:6px;padding:3px 8px;display:inline-block}
.del-btn{flex-shrink:0;background:none;border:1px solid var(--border);color:var(--muted);
  border-radius:7px;padding:4px 10px;font-size:.78rem;cursor:pointer;transition:all .15s}
.del-btn:hover{background:#fff5f5;color:#dc2626;border-color:#fca5a5}
.legend{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.legend-item{font-size:.78rem;padding:4px 12px;border-radius:100px;font-weight:600}
.loading{text-align:center;padding:30px;color:var(--muted);font-size:.9rem}
</style>
</head>
<body>
<div class="header">
  <h1>🌱 种子文章管理</h1>
  <div class="subtitle">手动添加高价值论文，加权影响关键词进化方向</div>
</div>
<div class="container">
  <div class="legend">
    <span class="legend-item lv1">📌 Lv1 普通推荐 &nbsp;weight×1</span>
    <span class="legend-item lv2">⭐ Lv2 重要 &nbsp;weight×3</span>
    <span class="legend-item lv3">🔥 Lv3 核心必读 &nbsp;weight×6</span>
  </div>
  <div class="add-card">
    <h2>➕ 添加种子文章</h2>
    <div class="form-row">
      <input type="text" id="urlInput" placeholder="arXiv 链接或 ID，如 2401.12345">
      <div class="level-group">
        <button class="level-btn active" data-lv="1" onclick="selectLevel(1)">📌 普通</button>
        <button class="level-btn" data-lv="2" onclick="selectLevel(2)">⭐ 重要</button>
        <button class="level-btn" data-lv="3" onclick="selectLevel(3)">🔥 核心</button>
      </div>
    </div>
    <div class="note-row">
      <input type="text" id="noteInput" placeholder="备注（可选，如：导师推荐）">
      <button class="submit-btn" id="submitBtn" onclick="addSeed()">添加</button>
    </div>
    <div class="status-msg" id="statusMsg"></div>
  </div>
  <div class="list-header">
    <h2>📚 已添加的种子文章</h2>
    <span class="count-badge" id="countBadge">加载中…</span>
  </div>
  <div id="seedList"><div class="loading">⏳ 加载中…</div></div>
</div>
<script>
const API = "http://127.0.0.1:" + location.port;
let selectedLevel = 1;
function selectLevel(lv) {
  selectedLevel = lv;
  document.querySelectorAll(".level-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.lv)===lv));
}
function setStatus(msg, type) {
  const el = document.getElementById("statusMsg");
  el.textContent = msg; el.className = "status-msg " + (type||"");
}
async function loadSeeds() {
  try {
    const lst = await (await fetch(API+"/api/seeds")).json();
    renderList(lst);
  } catch(e) {
    document.getElementById("seedList").innerHTML='<div class="empty">⚠️ 无法连接服务，请先运行 python main.py</div>';
    document.getElementById("countBadge").textContent="离线";
  }
}
function renderList(list) {
  document.getElementById("countBadge").textContent = list.length+" 篇";
  const el = document.getElementById("seedList");
  if(!list.length){el.innerHTML='<div class="empty">📭 暂无种子文章</div>';return;}
  const LI={1:{cls:"lv1",label:"📌 普通推荐"},2:{cls:"lv2",label:"⭐ 重要"},3:{cls:"lv3",label:"🔥 核心必读"}};
  el.innerHTML=list.map(s=>{
    const lv=s.level||1,info=LI[lv],note=s.note?`<span class="seed-note">💬 ${esc(s.note)}</span>`:"";
    const date=(s.added_at||"").slice(0,10),auth=(s.authors||[]).slice(0,3).join(", ")+((s.authors?.length>3)?" 等":"");
    return`<div class="seed-item"><span class="level-badge ${info.cls}">${info.label}</span>
<div class="seed-body"><div class="seed-title"><a href="${esc(s.abs_url)}" target="_blank">${esc(s.title)}</a></div>
<div class="seed-meta"><span>👤 ${esc(auth)||'（作者未知）'}</span><span>🆔 arXiv:${esc(s.arxiv_id)}</span><span>📅 ${date}</span><span>权重 ×${s.weight}</span></div>${note}</div>
<button class="del-btn" onclick="deleteSeed('${esc(s.arxiv_id)}')">删除</button></div>`;
  }).join("");
}
async function addSeed() {
  const urlVal=document.getElementById("urlInput").value.trim(),noteVal=document.getElementById("noteInput").value.trim();
  if(!urlVal){setStatus("⚠️ 请输入 arXiv 链接或 ID","warn");return;}
  const btn=document.getElementById("submitBtn");btn.disabled=true;setStatus("⏳ 查询中…","");
  try{
    const data=await(await fetch(API+"/api/seeds",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({url_or_id:urlVal,level:selectedLevel,note:noteVal})})).json();
    if(data.error)setStatus("❌ "+data.error,"err");
    else if(data.status==="added"){setStatus(`✅ 已添加：${data.record.title.slice(0,60)}`,"ok");
      document.getElementById("urlInput").value=document.getElementById("noteInput").value="";loadSeeds();}
    else if(data.status==="upgraded"){setStatus(`⬆️ 已升档至 Lv${data.record.level}：${data.record.title.slice(0,50)}`,"ok");loadSeeds();}
    else setStatus(`ℹ️ 已存在（Lv${data.record.level}），等级不低于当前输入`,"warn");
  }catch(e){setStatus("❌ 服务连接失败："+e.message,"err");}
  finally{btn.disabled=false;}
}
async function deleteSeed(id){
  if(!confirm("确定删除？"))return;
  await fetch(API+"/api/seeds/"+encodeURIComponent(id),{method:"DELETE"});loadSeeds();
}
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("urlInput").addEventListener("keydown",e=>{if(e.key==="Enter")addSeed();});loadSeeds();});
function esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# 服务类
# ─────────────────────────────────────────────────────────────

class ClickTrackerServer:
    def __init__(self, clicks_file: str, reactions_file: str = "",
                 seeds_file: str = "", history_file: str = "",
                 port: int = DEFAULT_PORT):
        self.clicks_file    = clicks_file
        self.reactions_file = reactions_file
        self.seeds_file     = seeds_file
        self.history_file   = history_file
        self.port           = port
        self._server: HTTPServer | None       = None
        self._thread: threading.Thread | None = None

    def start(self):
        _Handler.clicks_file    = self.clicks_file
        _Handler.reactions_file = self.reactions_file
        _Handler.seeds_file     = self.seeds_file
        _Handler.history_file   = self.history_file
        _Handler.react_callbacks = []
        # Windows 上 TIME_WAIT 会阻止端口被立刻重用，
        # allow_reuse_address=True 等价于 SO_REUSEADDR，三平台均有效
        class _ReusableHTTPServer(HTTPServer):
            allow_reuse_address = True

        try:
            self._server = _ReusableHTTPServer(("127.0.0.1", self.port), _Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info(f"  [Tracker] 服务已启动 → http://127.0.0.1:{self.port}")
            logger.info(f"  [Tracker]   种子管理 UI → http://127.0.0.1:{self.port}/")
            logger.info(f"  [Tracker]   reactions  → {self.reactions_file}")
        except OSError as e:
            logger.warning(f"  [Tracker] 启动失败（端口 {self.port} 被占用？）: {e}")

    def register_react_callback(self, fn):
        """注册赞/踩回调（fn 接收 record: dict）"""
        _Handler.react_callbacks.append(fn)

    def stop(self):
        if self._server:
            self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
