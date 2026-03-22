# Auto-Paper-Briefing

> 个人 AI 学术追踪与简报系统 —— 你的私人"学术秘书"

这是本人的第一个vibe coding项目，由Claude 4.6 sonnet构建。核心提示词保存于prompt.md。

项目目的：从 arXiv 自动检索最新论文，用 AI 提取客观摘要，生成可交互的 HTML 简报，并根据你的阅读行为持续进化搜索关键词。

快速开始：releases中有``` Windows / macOS / Linux```平台封装好的安装包。也可以下载源码，自行配置python环境，使用更灵活。首次使用，先运行setup，再运行main。

---

## 目录

- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [一键启动脚本](#一键启动脚本)
- [命令行参数](#命令行参数)
- [项目结构](#项目结构)
- [功能详解](#功能详解)
  - [初始化配置向导](#初始化配置向导)
  - [关键词进化系统](#关键词进化系统)
  - [交互式简报](#交互式简报)
  - [种子文章管理](#种子文章管理)
  - [数据导出](#数据导出)
- [配置说明](#配置说明)
- [定时自动运行](#定时自动运行)
- [数据文件说明](#数据文件说明)
- [注意事项](#注意事项)

---

## 核心特性

| 特性 | 说明 |
|------|------|
| 🎓 可视化配置向导 | 首次运行自动打开浏览器，填表完成所有配置，无需手动编辑 YAML |
| 🔍 智能检索 | arXiv 官方 API + 分页去重，凑满目标数量才停止翻页 |
| 🔄 关键词自动扩展 | 某关键词结果不足时，AI 自动生成近义词补充检索 |
| 🔥 阅后即焚 | PDF 解析完成后立即删除，零磁盘占用 |
| 🤖 客观 AI 总结 | 严格按预设维度提取，禁止主观评价，Temperature=0.1 |
| 📊 交互式简报 | 摘要内联折叠，赞/踩/评论，实时写入兴趣记录 |
| 👍👎 赞踩系统 | 支持取消，可附评论，评论内容直接影响关键词进化方向 |
| 🌱 种子文章 | 三档权重（普通/重要/核心），去重自动升档，Web UI 管理 |
| 🧬 关键词进化 | 四信号融合（点击/点赞/踩/种子），双轨制防信息茧房 |
| 📦 数据导出 | 一键导出所有阅读记录、种子、历史为 JSON 文件 |
| 🖥️ 跨平台 | Windows / macOS / Linux，提供一键启动脚本 |

---

## 快速开始

**环境要求**：Python 3.10 或更高版本

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

### 第二步：运行初始化向导

首次运行时，程序会自动检测到缺少配置文件，并弹出浏览器配置向导：

```bash
python main.py
```

向导分四步：填写 AI API 信息 → 设置搜索关键词与 arXiv 分类 → 添加初始种子文章（可选）→ 确认保存。完成后自动开始抓取论文。

**后续每次启动**时，程序会询问是否重新配置：

```
  是否重新配置 API / 关键词 / 分类？（历史记录和种子文章不受影响）
  [Y] 打开配置向导    [N/Enter] 直接运行（默认）
```

直接回车跳过，按 `Y` 重新配置。历史记录、点赞记录、种子文章不受影响。

### 第三步：查看简报

程序运行完成后，打开 `reports/` 目录下生成的 HTML 文件即可阅读当日简报。程序保持运行（用于追踪点击和点赞），按 `Ctrl+C` 停止。

---

## 一键启动脚本

无需记忆命令，双击即运行：

```bash
# macOS / Linux
# 首次使用需赋予执行权限
chmod +x start.sh
./start.sh

# Windows
# 直接双击 start.bat，或在命令行运行
start.bat
```

脚本会自动检测 Python 环境、安装依赖，首次运行时调起配置向导。

---

## 命令行参数

```bash
python main.py                       # 标准运行（询问是否重配 → 进化关键词 → 抓论文）
python main.py --no-setup-prompt     # 跳过启动询问，直接运行（适合定时任务）
python main.py --setup               # 强制打开配置向导
python main.py --no-evolve           # 跳过关键词进化，直接抓取
python main.py --evolve-only         # 仅执行关键词进化，不抓论文
python main.py --config my.yaml      # 指定配置文件
```

---

## 项目结构

```
auto-paper-briefing/
│
├── main.py                    # 主入口：启动询问、进度条、流程调度
├── setup.py                   # 可视化配置向导（浏览器 Web UI）
├── migrate_likes.py           # 从旧版 likes.json 迁移到 reactions.json
├── run_tests.py               # 内置测试套件（无需 pytest）
│
├── config.yaml                # 所有配置（关键词会被进化系统自动更新）
├── requirements.txt
├── start.sh                   # macOS / Linux 一键启动脚本
├── start.bat                  # Windows 一键启动脚本
├── auto-paper-briefing.spec   # PyInstaller 打包配置
├── BUILD.md                   # 打包为可执行文件的说明
│
├── modules/
│   ├── config_loader.py       # 配置加载，自动从环境变量读取 API Key
│   ├── history_manager.py     # 已处理论文去重记录
│   ├── arxiv_fetcher.py       # arXiv 检索：分页去重 + AI 关键词扩展
│   ├── pdf_processor.py       # PDF 下载、文本提取、阅后即焚
│   ├── ai_summarizer.py       # AI 客观总结（OpenAI 兼容接口）
│   ├── report_generator.py    # 每日简报 + 反应历史页生成
│   ├── click_tracker.py       # 本地 HTTP 服务（追踪/种子管理/导出）
│   ├── keyword_evolver.py     # 四信号融合关键词进化引擎
│   └── seed_manager.py        # 种子文章管理（权重/去重/升档）
│
├── reports/                   # 自动生成的 HTML 文件
│   ├── Daily_Paper_20240101.html
│   └── reactions_history.html # 赞踩历史（常驻，纯前端实时读取）
│
├── history.json               # 已处理论文记录（去重用）
├── reactions.json             # 赞/踩/评论记录
├── clicks.json                # 点击行为记录
└── seeds.json                 # 手动添加的种子文章
```

---

## 功能详解

### 初始化配置向导

运行 `python setup.py` 或首次启动 `main.py` 时自动打开，也可随时通过 `python main.py --setup` 重新进入。

**Step 1 · AI API**：提供 OpenAI / DeepSeek / 阿里云百炼 / Ollama 快速预填，内置连通性测试。

**Step 2 · 搜索关键词与分类**：标签式输入关键词（回车添加），分组快选 arXiv 分类（计算机/统计/物理/数学等），支持自定义分类代码，附分类总览链接。

**Step 3 · 种子文章**（可选）：粘贴 arXiv 链接，实时拉取标题，设置权重等级。

**Step 4 · 确认保存**：生成 `config.yaml` 和 `seeds.json`，历史记录等数据文件完全不受影响。

---

### 关键词进化系统

每次运行时（配置向导模式除外），系统融合四类兴趣信号，由 AI 生成新的关键词列表并写回 `config.yaml`。

**四类信号与权重**

| 信号 | 来源 | 触发方式 | 影响力 |
|------|------|----------|--------|
| 🖱️ 点击 | `clicks.json` | 点击"查看摘要页"或"下载 PDF" | 低（×1） |
| 👍 点赞含评论 | `reactions.json` | 点赞并填写评论 | 高（×3，评论揭示精确兴趣） |
| 👍 点赞 | `reactions.json` | 主动点赞 | 中高（×2） |
| 👎 踩 | `reactions.json` | 主动踩，可附评论 | 负信号，AI 将排斥该方向 |
| 🌱 种子 Lv1 | `seeds.json` | 手动添加，普通 | ×1 |
| ⭐ 种子 Lv2 | `seeds.json` | 手动添加，重要 | ×3 |
| 🔥 种子 Lv3 | `seeds.json` | 手动添加，核心 | ×6 |

**双轨制防信息茧房**

```
正向信号 ──→ 精炼轨道 ──→ 核心兴趣关键词（收敛）
负向信号（踩）↗            ↘ AI 受约束，避开踩的方向
                    探索轨道 ──→ 相邻领域关键词（发散）← 防茧房
```

在 `config.yaml` 中调节探索比例：

```yaml
keyword_evolution:
  explore_ratio: 0.50        # 0.0=完全收敛  0.5=均衡（默认）  0.7=激进探索
  total_queries: 8           # 进化后关键词总数（不含固定关键词）
  min_signals_to_evolve: 3   # 有效信号不足时跳过，避免样本太少产生偏差
```

**固定关键词**（不参与进化）：

```yaml
arxiv:
  queries:
    - query: "my permanent research topic"
      pin: true        # 永远保留，不会被替换
    - "llm reasoning"  # 普通关键词，会被动态替换
```

**关键词自动扩展**：某个关键词在时间窗口内结果不足时，AI 自动生成近义词或删词简化版进行补充检索，直到凑满目标数量或穷尽 arXiv 结果为止。

---

### 交互式简报

每日简报（`reports/Daily_Paper_YYYYMMDD.html`）包含以下交互功能：

**阅读**：每张卡片展示 AI 总结（默认展开）和原文摘要（默认折叠），点击标题栏切换。

**赞踩系统**：
- 👍 赞 / 👎 踩：再次点击取消，支持来回切换
- 点击赞或踩后，卡片底部弹出行内评论框，可填写为什么喜欢/不感兴趣（回车或失焦提交，可跳过）
- 评论内容直接进入进化提示词，帮助 AI 理解你更精确的偏好

**反应历史页**（`reports/reactions_history.html`）：常驻纯前端页面，每 30 秒自动刷新，支持按赞/踩筛选、标题/作者搜索、时间排序，展示评论内容。

**导出数据**：顶部导航栏"📦 导出数据"按钮，一键下载包含所有记录的 JSON 文件。

---

### 种子文章管理

程序运行后，访问 `http://127.0.0.1:19523/` 打开种子管理界面。

**添加**：粘贴 arXiv 链接或 ID（如 `2401.12345`），自动拉取标题，选择权重等级，填写备注，回车提交。

**去重升档**：同一篇文章再次添加时，若新等级更高则自动升档，否则提示已存在。

**权重等级**：

| 等级 | 适用场景 | 进化权重 |
|------|----------|----------|
| 📌 Lv1 普通推荐 | 同学提到、偶然发现的好文章 | ×1 |
| ⭐ Lv2 重要 | 导师建议读、近期必要参考 | ×3 |
| 🔥 Lv3 核心必读 | 与自己研究直接相关、必须精读 | ×6 |

---

### 数据导出

点击简报顶部"📦 导出数据"按钮，下载 `apb-export-YYYYMMDD-HHmmss.json`，包含：

```json
{
  "exported_at": "2024-01-15T14:30:22",
  "reactions":   { "arXiv ID": { "reaction": "like", "comment": "...", ... } },
  "seeds":       { "arXiv ID": { "level": 3, "title": "...", ... } },
  "history":     { "arXiv ID": { "title": "...", "processed_at": "...", ... } },
  "clicks":      [ { "arxiv_id": "...", "action": "abs", ... } ]
}
```

此文件可用于备份、迁移到新机器，或作为数据分析的输入。

---

## 配置说明

### AI API 兼容性

本系统使用标准 OpenAI 兼容 HTTP 接口，修改 `base_url` 即可切换任意服务商：

| 服务商 | base_url |
|--------|----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 本地 Ollama | `http://localhost:11434/v1` |

API Key 推荐通过环境变量传入，避免提交到版本控制：

```bash
# macOS / Linux
export AI_API_KEY="sk-xxxxxxxxxxxxxxxx"

# Windows PowerShell
$env:AI_API_KEY = "sk-xxxxxxxxxxxxxxxx"
```

### 自定义总结维度

```yaml
summary:
  dimensions:
    - "研究背景与动机：该研究试图解决什么问题？"
    - "核心方法与技术：提出了什么方法或框架？"
    - "实验结论：取得了怎样的量化结果？"
    - "研究局限性：论文明确指出了哪些局限？"
    # 可自由增删，AI 会严格按此提取，不作主观评价
```

### 检索参数

```yaml
arxiv:
  max_results_per_query: 10   # 每个关键词目标获取篇数
  days_lookback: 7            # 只获取最近 N 天的论文（0=不限）
```

起步阶段建议 `days_lookback: 90`、`max_results_per_query: 30` 快速积累种子数据；日常使用改回 `7` 和 `10`。

---

## 定时自动运行

### Linux / macOS（cron）

```bash
crontab -e
# 每天早上 8:00 自动运行，跳过启动询问
0 8 * * * cd /path/to/auto-paper-briefing && \
  AI_API_KEY=sk-xxx python main.py --no-setup-prompt >> logs/cron.log 2>&1 &
```

建议搭配 `timeout` 限制最长运行时间：

```bash
0 8 * * * cd /path/to && timeout 7200 python main.py --no-setup-prompt &
```

### Windows（任务计划程序）

新建 `run_scheduled.bat`：

```bat
set AI_API_KEY=sk-xxxxxxxxxxxxxxxx
cd /d C:\path\to\auto-paper-briefing
python main.py --no-setup-prompt
```

在"任务计划程序"中新建任务，设置每日触发，操作指向此 `.bat` 文件。

---

## 分发


| 平台 | 产物文件 |
|------|----------|
| 🪟 Windows | `apb-windows-x86_64.zip` |
| 🍎 macOS Intel | `apb-macos-intel.tar.gz` |
| 🍎 macOS Apple Silicon | `apb-macos-arm64.tar.gz` |
| 🐧 Linux | `apb-linux-x86_64.tar.gz` |

朋友下载对应平台的压缩包，解压后先运行 `apb-setup`（配置向导），再运行 `auto-paper-briefing`（主程序），无需安装任何依赖。

详细说明见 `BUILD.md`。


---

## 数据文件说明

所有数据文件均为 JSON 格式，存放在项目根目录，可直接用文本编辑器查看或备份。

| 文件 | 内容 | 自动生成 |
|------|------|----------|
| `config.yaml` | 所有配置参数，关键词字段会被进化系统更新 | 由向导生成 |
| `history.json` | 已处理论文的 arXiv ID 和标题（用于去重） | ✓ |
| `reactions.json` | 每篇论文的赞/踩状态、评论、时间戳 | ✓ |
| `clicks.json` | 每次点击"查看摘要页"或"下载 PDF"的记录 | ✓ |
| `seeds.json` | 手动添加的种子文章，含权重等级和备注 | 由向导或种子管理 UI 生成 |
| `config.yaml.bak` | 每次关键词进化前的配置备份 | ✓ |

**从旧版迁移**：如果你在之前版本使用了 `likes.json`，运行以下命令迁移到新格式：

```bash
python migrate_likes.py
```

原文件会备份为 `likes.json.bak`，不会被删除。

---

## 注意事项

**arXiv 数据源**：本系统仅使用 arXiv 作为数据源（提供官方开放 API，无反爬问题）。Google Scholar 反爬机制严厉，暂未支持。

**AI 幻觉**：Prompt 要求"客观不评判"，Temperature 设为 0.1，但 AI 仍可能偶尔编造信息。关键实验数据建议对照原文核实。

**PDF 解析**：优先使用 PyMuPDF（效果最佳），未安装时自动降级。推荐安装：

```bash
pip install PyMuPDF
```

**网络环境**：访问 arXiv API 和 AI 接口在部分地区可能需要代理，可切换国内兼容接口（DeepSeek / 阿里云百炼）规避此问题。

**进化备份**：每次关键词进化前，`config.yaml` 会自动备份为 `config.yaml.bak`，若结果不满意可直接替换还原。

---

## License

本项目基于 [MIT License](LICENSE) 开源，欢迎自由使用、修改和分发。

论文摘要版权归原作者所有，AI 总结仅供参考，不构成学术意见。
