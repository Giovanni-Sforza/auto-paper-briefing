#!/usr/bin/env python3
"""
run_tests.py — 内置测试套件
无需 pytest，直接运行：python run_tests.py
"""

import sys
import os
import json
import time
import unittest
import unittest.mock as mock
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def make_arxiv_xml(ids: list[str], total: int) -> bytes:
    entries = "".join(f"""
  <entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/{aid}v1</id>
    <title>Paper {aid}</title>
    <author><n>Alice</n></author>
    <summary>Abstract of {aid}.</summary>
    <published>2024-06-01T00:00:00Z</published>
    <link rel="alternate" href="https://arxiv.org/abs/{aid}"/>
    <link title="pdf" href="https://arxiv.org/pdf/{aid}"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>""" for aid in ids)
    return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>{total}</opensearch:totalResults>
  {entries}</feed>""".encode()


# ═══════════════════════════════════════════════════════════════
#  HistoryManager
# ═══════════════════════════════════════════════════════════════

class TestHistoryManager(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.gettempdir(), "test_history_apb.json")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_add_and_exists(self):
        from modules.history_manager import HistoryManager
        h = HistoryManager(self.path)
        self.assertFalse(h.exists("2401.00001"))
        h.add({"arxiv_id": "2401.00001", "title": "T", "authors": []})
        self.assertTrue(h.exists("2401.00001"))

    def test_persist_and_reload(self):
        from modules.history_manager import HistoryManager
        h = HistoryManager(self.path)
        h.add({"arxiv_id": "2401.00002", "title": "T2", "authors": []})
        h.save()
        h2 = HistoryManager(self.path)
        self.assertTrue(h2.exists("2401.00002"))
        self.assertEqual(h2.count(), 1)


# ═══════════════════════════════════════════════════════════════
#  ArxivFetcher
# ═══════════════════════════════════════════════════════════════

class TestArxivFetcher(unittest.TestCase):

    def _make_urlopen(self, all_ids, total=None):
        from urllib.parse import urlparse, parse_qs, unquote_plus
        from modules.arxiv_fetcher import PAGE_SIZE

        def fake(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            qs  = parse_qs(urlparse(url).query)
            s   = int(qs.get("start", ["0"])[0])
            m   = int(qs.get("max_results", [str(PAGE_SIZE)])[0])
            batch = all_ids[s:s+m]
            class R:
                def read(self): return make_arxiv_xml(batch, total or len(all_ids))
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return R()
        return fake

    def test_basic_fetch(self):
        from modules.arxiv_fetcher import ArxivFetcher
        all_ids = [f"p{i:03d}" for i in range(1, 21)]
        fetcher = ArxivFetcher({"queries":["q1"],"categories":[],
                                "max_results_per_query":5,"days_lookback":0})
        with mock.patch("urllib.request.urlopen", side_effect=self._make_urlopen(all_ids)):
            results = fetcher.fetch()
        self.assertEqual(len(results), 5)

    def test_dedup_with_history(self):
        from modules.arxiv_fetcher import ArxivFetcher
        all_ids = [f"p{i:03d}" for i in range(1, 61)]
        history = {f"p{i:03d}" for i in range(1, 41)}   # 前40已处理
        fetcher = ArxivFetcher({"queries":["q1"],"categories":[],
                                "max_results_per_query":10,"days_lookback":0})
        with mock.patch("urllib.request.urlopen", side_effect=self._make_urlopen(all_ids)):
            results = fetcher.fetch(history_ids=history)
        self.assertEqual(len(results), 10)
        for p in results:
            self.assertNotIn(p["arxiv_id"], history)

    def test_graceful_when_too_few(self):
        from modules.arxiv_fetcher import ArxivFetcher
        slim = ["s001", "s002"]
        fetcher = ArxivFetcher({"queries":["q1"],"categories":[],
                                "max_results_per_query":50,"days_lookback":0})
        with mock.patch("urllib.request.urlopen", side_effect=self._make_urlopen(slim)):
            results = fetcher.fetch()
        self.assertEqual(len(results), 2)

    def test_pin_query_parsing(self):
        from modules.arxiv_fetcher import ArxivFetcher
        fetcher = ArxivFetcher({"queries":[
            {"query":"pinned topic","pin":True},
            "normal query",
        ], "categories":[], "max_results_per_query":5, "days_lookback":0})
        self.assertEqual(fetcher.queries, ["pinned topic", "normal query"])

    def test_expansion_triggered_on_deficit(self):
        from modules.arxiv_fetcher import ArxivFetcher, PAGE_SIZE
        from urllib.parse import urlparse, parse_qs, unquote_plus
        slim   = ["s001", "s002"]
        expand = {"q short": ["e001","e002","e003"]}
        call_log = []

        def urlopen_mock(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "fake_ai" in url:
                call_log.append("ai")
                resp = json.dumps({"choices":[{"message":{"content":
                    json.dumps({"q tight": ["q short"]})}}]}).encode()
                class AIR:
                    def read(self): return resp
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                return AIR()
            qs  = parse_qs(urlparse(url).query)
            sq  = unquote_plus(qs.get("search_query",[""])[0])
            s   = int(qs.get("start",["0"])[0])
            m   = int(qs.get("max_results",[str(PAGE_SIZE)])[0])
            call_log.append(f"arxiv:{sq[:20]}")
            if "q tight" in sq:
                batch, total = slim[s:s+m], len(slim)
            elif "q short" in sq:
                pool = expand["q short"]
                batch, total = pool[s:s+m], len(pool)
            else:
                batch, total = [], 0
            class R:
                def read(self): return make_arxiv_xml(batch, total)
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return R()

        fetcher = ArxivFetcher(
            {"queries":["q tight"],"categories":[],"max_results_per_query":5,"days_lookback":0},
            {"api_key":"x","base_url":"http://fake_ai/v1","model":"m"}
        )
        with mock.patch("urllib.request.urlopen", side_effect=urlopen_mock):
            results = fetcher.fetch()

        self.assertGreater(len(results), 2)     # 扩展后超过原来的2篇
        self.assertIn("ai", call_log)           # AI 被调用了


# ═══════════════════════════════════════════════════════════════
#  ClickTrackerServer
# ═══════════════════════════════════════════════════════════════

class TestClickTracker(unittest.TestCase):
    PORT      = 19530
    CLICKS    = os.path.join(tempfile.gettempdir(), "test_clicks_apb.json")
    REACTIONS = os.path.join(tempfile.gettempdir(), "test_reactions_apb.json")
    SEEDS     = os.path.join(tempfile.gettempdir(), "test_seeds_apb.json")

    def setUp(self):
        from modules.click_tracker import ClickTrackerServer
        self.server = ClickTrackerServer(
            self.CLICKS, self.REACTIONS, self.SEEDS, port=self.PORT)
        self.server.start()
        time.sleep(0.3)

    def tearDown(self):
        self.server.stop()
        for f in [self.CLICKS, self.REACTIONS, self.SEEDS]:
            if os.path.exists(f): os.remove(f)

    def _post(self, path, payload):
        import urllib.request as ur
        data = json.dumps(payload).encode()
        req  = ur.Request(f"http://127.0.0.1:{self.PORT}{path}", data=data,
                          headers={"Content-Type":"application/json"}, method="POST")
        with ur.urlopen(req) as r:
            ct   = r.headers.get("Content-Type","")
            body = r.read()
            return json.loads(body) if "json" in ct else body.decode()

    def _get(self, path):
        import urllib.request as ur
        with ur.urlopen(f"http://127.0.0.1:{self.PORT}{path}") as r:
            return json.loads(r.read())

    def test_click_recorded(self):
        self._post("/track", {"arxiv_id":"2401.00001","title":"T","action":"abs"})
        data = json.load(open(self.CLICKS))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["arxiv_id"], "2401.00001")

    def test_like_and_cancel(self):
        r1 = self._post("/react", {"arxiv_id":"2401.00001","title":"T","action":"like"})
        self.assertEqual(r1["reaction"], "like")
        self.assertTrue(r1["is_new"])
        r2 = self._post("/react", {"arxiv_id":"2401.00001","title":"T","action":"cancel"})
        self.assertIsNone(r2["reaction"])

    def test_dislike(self):
        r = self._post("/react", {"arxiv_id":"2401.00002","title":"T2","action":"dislike"})
        self.assertEqual(r["reaction"], "dislike")

    def test_like_dedup(self):
        self._post("/react", {"arxiv_id":"2401.00003","title":"T3","action":"like"})
        r2 = self._post("/react", {"arxiv_id":"2401.00003","title":"T3","action":"like"})
        self.assertFalse(r2["is_new"])

    def test_comment_saved(self):
        self._post("/react", {"arxiv_id":"2401.00004","title":"T4",
                               "action":"like","comment":"很好的方法"})
        data = json.load(open(self.REACTIONS))
        self.assertEqual(data["2401.00004"]["comment"], "很好的方法")

    def test_api_reactions(self):
        self._post("/react", {"arxiv_id":"2401.00005","title":"T5","action":"like"})
        lst = self._get("/api/reactions")
        self.assertIsInstance(lst, list)
        self.assertEqual(lst[0]["arxiv_id"], "2401.00005")

    def test_seed_ui_serves_html(self):
        import urllib.request as ur
        with ur.urlopen(f"http://127.0.0.1:{self.PORT}/") as r:
            html = r.read().decode()
        self.assertIn("种子文章管理", html)


# ═══════════════════════════════════════════════════════════════
#  ReportGenerator
# ═══════════════════════════════════════════════════════════════

class TestReportGenerator(unittest.TestCase):
    OUT = os.path.join(tempfile.gettempdir(), "test_rg_apb")

    def setUp(self):
        os.makedirs(self.OUT, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.OUT, ignore_errors=True)

    def _make_gen(self):
        from modules.report_generator import ReportGenerator
        return ReportGenerator({"paths":{"output_dir":self.OUT},
                                "click_tracking":{"port":19523}})

    def test_daily_report_contains_buttons(self):
        gen = self._make_gen()
        papers = [{"arxiv_id":"2401.12345","title":"LLM Test","authors":["Alice"],
                   "abs_url":"https://arxiv.org/abs/2401.12345",
                   "pdf_url":"https://arxiv.org/pdf/2401.12345",
                   "categories":["cs.AI"],"published":"2024-01-15",
                   "abstract":"We propose a method.","summary":{"背景":"推理问题"}}]
        path = gen.generate(papers)
        html = open(path).read()
        self.assertIn("btn-like",    html)
        self.assertIn("btn-dislike", html)
        self.assertIn("handleReact", html)
        self.assertIn("comment-bar", html)
        self.assertIn("We propose a method", html)          # 摘要内联
        self.assertIn("reactions_history.html", html)       # 历史页链接
        self.assertIn("MIT License", html)                  # License 声明

    def test_reactions_history_is_frontend(self):
        gen = self._make_gen()
        path = gen.generate_reactions_history()
        html = open(path).read()
        self.assertIn("api/reactions", html)    # 从 API 拉取
        self.assertIn("setInterval",   html)    # 自动刷新
        self.assertIn("filter-btn",    html)    # 赞/踩筛选

    def test_history_page_not_overwritten(self):
        gen   = self._make_gen()
        path  = gen.generate_reactions_history()
        mtime = os.path.getmtime(path)
        time.sleep(0.05)
        gen.generate_reactions_history()
        self.assertEqual(mtime, os.path.getmtime(path))


# ═══════════════════════════════════════════════════════════════
#  Setup Wizard
# ═══════════════════════════════════════════════════════════════

class TestSetupWizard(unittest.TestCase):
    CONFIG = os.path.join(tempfile.gettempdir(), "test_setup_config_apb.yaml")
    SEEDS  = os.path.join(tempfile.gettempdir(), "test_setup_seeds_apb.json")

    def tearDown(self):
        for f in [self.CONFIG, self.SEEDS]:
            if os.path.exists(f): os.remove(f)

    def test_arxiv_id_parsing(self):
        from setup import parse_arxiv_id
        self.assertEqual(parse_arxiv_id("2401.12345"), "2401.12345")
        self.assertEqual(parse_arxiv_id("https://arxiv.org/abs/2401.12345v2"), "2401.12345")
        self.assertIsNone(parse_arxiv_id("not-valid"))

    def test_write_config(self):
        import yaml
        from setup import SetupHandler
        SetupHandler.config_path = self.CONFIG
        h = SetupHandler.__new__(SetupHandler)
        h._write_config({
            "ai": {"api_key":"sk-test","base_url":"https://api.openai.com/v1","model":"gpt-4o-mini"},
            "arxiv": {"queries":["llm reasoning"],"categories":["cs.AI"]},
            "performance": {"max_results":10,"days_lookback":7},
        })
        self.assertTrue(os.path.exists(self.CONFIG))
        with open(self.CONFIG) as f:
            cfg = yaml.safe_load(f)
        self.assertEqual(cfg["ai"]["api_key"], "sk-test")
        self.assertIn("llm reasoning", str(cfg["arxiv"]["queries"]))
        self.assertEqual(cfg["arxiv"]["max_results_per_query"], 10)

    def test_write_seeds(self):
        from setup import SetupHandler
        SetupHandler.config_path = self.CONFIG
        # 临时改种子输出路径
        orig = "seeds.json"
        # 创建一个不冲突的测试
        h = SetupHandler.__new__(SetupHandler)
        h._write_seeds({"seeds":[
            {"arxiv_id":"2401.99999","title":"Seed Paper",
             "authors":["Bob"],"level":3,"note":"核心"}
        ]})
        with open("seeds.json") as f:
            seeds = json.load(f)
        self.assertEqual(seeds["2401.99999"]["level"], 3)
        self.assertEqual(seeds["2401.99999"]["weight"], 6.0)
        os.remove("seeds.json")


# ═══════════════════════════════════════════════════════════════
#  MigrateLikes
# ═══════════════════════════════════════════════════════════════

class TestMigrateLikes(unittest.TestCase):
    LIKES     = os.path.join(tempfile.gettempdir(), "test_migrate_likes_apb.json")
    REACTIONS = os.path.join(tempfile.gettempdir(), "test_migrate_reactions_apb.json")

    def tearDown(self):
        for f in [self.LIKES, self.REACTIONS, self.LIKES+".bak"]:
            if os.path.exists(f): os.remove(f)

    def test_migration(self):
        from migrate_likes import migrate
        likes = [
            {"arxiv_id":"2401.00001","title":"Paper A","authors":["Alice"],
             "abs_url":"https://arxiv.org/abs/2401.00001",
             "liked_at":"2024-01-10T09:00:00","summary_snippet":"LLM"},
            {"arxiv_id":"","title":"invalid"},   # 无 ID，应跳过
        ]
        with open(self.LIKES,"w") as f:
            json.dump(likes, f)
        migrate(self.LIKES, self.REACTIONS)
        with open(self.REACTIONS) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data["2401.00001"]["reaction"], "like")
        self.assertEqual(data["2401.00001"]["comment"],  "")
        self.assertTrue(os.path.exists(self.LIKES+".bak"))

    def test_idempotent(self):
        from migrate_likes import migrate
        likes = [{"arxiv_id":"2401.00002","title":"P","authors":[],
                  "abs_url":"","liked_at":"2024-01-10T09:00:00"}]
        with open(self.LIKES,"w") as f:
            json.dump(likes, f)
        migrate(self.LIKES, self.REACTIONS)
        migrate(self.LIKES, self.REACTIONS)  # 第二次
        with open(self.REACTIONS) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)       # 不重复写入


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestHistoryManager))
    suite.addTests(loader.loadTestsFromTestCase(TestArxivFetcher))
    suite.addTests(loader.loadTestsFromTestCase(TestClickTracker))
    suite.addTests(loader.loadTestsFromTestCase(TestReportGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestSetupWizard))
    suite.addTests(loader.loadTestsFromTestCase(TestMigrateLikes))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
