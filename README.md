# 📄 Auto-Paper-Briefing

个人自动化 AI 学术追踪与简报系统 —— 你的私人"学术秘书"。

这是一个vibe coding项目，是本人第一个vibe coding项目，使用的是Claude 3.6 sonnet。prompt记录与prompt.txt文件中

作用：自动从 arXiv 检索最新论文 → AI 客观提取信息 → 生成 HTML 简报 → 根据阅读行为持续进化关键词。

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🔍 自动检索 | 按关键词 + 分类从 arXiv 官方 API 抓取最新论文 |
| 🚫 自动去重 | 本地 JSON 记录历史，已处理论文自动跳过 |
| 🔥 阅后即焚 | PDF 解析完成后立即删除，零磁盘占用 |
| 🤖 客观总结 | AI 严格按预设维度提取，禁止主观评价，Temperature=0.1 |
| 📊 HTML 简报 | 摘要内联展开，AI 总结可折叠，一键跳转原文/PDF |
| 👍 点赞系统 | 主动点赞记录兴趣，写入 `likes.json`，权重高于普通点击 |
| 🌱 种子文章 | 手动添加导师/同学推荐的论文，设置 3 档权重，去重自动升档 |
| 🧬 关键词进化 | 三信号融合（点击/点赞/种子），AI 自动迭代 `config.yaml` 关键词 |
| 🛡️ 防信息茧房 | 精炼轨道 + 探索轨道双轨制，可调比例，防止关键词过度收敛 |
| ⭐ 点赞历史 | 常驻前端页面，实时从本地服务读取，支持搜索与排序 |
| ⚙️ 一键配置 | 所有参数统一在 `config.yaml` 中管理 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置参数

编辑 `config.yaml`，填写 AI 接口信息和初始关键词：

```yaml
ai:
  base_url: "https://api.openai.com/v1"   # 或 DeepSeek / 阿里云等兼容接口
  model: "gpt-4o-mini"

arxiv:
  queries:
    - "large language model reasoning"
    - "multimodal foundation model"
```

### 3. 设置 API Key

**方式一（推荐）**：环境变量，不会意外提交到 Git

```bash
# macOS / Linux
export AI_API_KEY="sk-xxxxxxxxxxxxxxxx"

#永久生效
echo 'export AI_API_KEY="sk-xxxxxxxxxxxxxxxx"' >> ~/.zshrc
source ~/.zshrc
#验证是否生效
echo $AI_API_KEY

# Windows PowerShell
$env:AI_API_KEY = "sk-xxxxxxxxxxxxxxxx"
```

**方式二**：直接填写 `config.yaml` 的 `ai.api_key` 字段。

### 4. 运行

```bash
python main.py
```

程序运行完毕后**不会退出**，而是保持后台服务运行（用于点击/点赞追踪）。在浏览器中打开生成的简报文件，按 `Ctrl+C` 停止服务。

---

## 📁 项目结构

```
auto-paper-briefing/
├── main.py                    # 主入口
├── config.yaml                # 所有配置（含关键词，会被进化系统自动更新）
├── requirements.txt
│
├── modules/
│   ├── config_loader.py       # 配置加载 + 环境变量读取
│   ├── history_manager.py     # 已处理论文去重记录
│   ├── arxiv_fetcher.py       # arXiv 官方 API 检索
│   ├── pdf_processor.py       # PDF 下载、文本提取、阅后即焚
│   ├── ai_summarizer.py       # AI 客观总结（OpenAI 兼容接口）
│   ├── report_generator.py    # 每日简报 + 点赞历史页生成
│   ├── click_tracker.py       # 本地 HTTP 服务：追踪点击/点赞/种子管理
│   ├── keyword_evolver.py     # 三信号融合关键词进化引擎
│   ├── likes_manager.py       # 点赞历史管理
│   └── seed_manager.py        # 种子文章管理（权重/去重/升档）
│
├── reports/                   # 自动生成
│   ├── Daily_Paper_20240101.html   # 每日简报
│   └── likes_history.html          # 点赞历史（常驻，纯前端）
│
├── history.json               # 自动生成：已处理论文记录
├── clicks.json                # 自动生成：点击行为记录
├── likes.json                 # 自动生成：点赞记录
├── seeds.json                 # 自动生成：手动添加的种子文章
└── prompt.md                  # vibe coding prompt
```

---

## 🧬 关键词进化系统

这是本项目的核心设计。每次运行时，系统会读取三类兴趣信号，融合后由 AI 生成新的关键词列表，并自动写回 `config.yaml`。

### 三类信号与权重

| 信号类型 | 来源文件 | 触发方式 | 相对权重 |
|----------|----------|----------|----------|
| 🖱️ 点击 | `clicks.json` | 点击"查看摘要页"或"下载 PDF" | × 1 |
| 👍 点赞 | `likes.json` | 主动点击简报中的点赞按钮 | × 2 |
| 🌱 种子 Lv1 | `seeds.json` | 手动添加，普通推荐 | × 1 |
| ⭐ 种子 Lv2 | `seeds.json` | 手动添加，重要 | × 3 |
| 🔥 种子 Lv3 | `seeds.json` | 手动添加，核心必读 | × 6 |

### 双轨制防信息茧房

```
三类信号 → AI 精炼轨道 → 核心兴趣关键词（收敛）
                      ↘
              AI 探索轨道 → 相邻领域关键词（发散）← 防茧房
```

在 `config.yaml` 中调节比例：

```yaml
keyword_evolution:
  explore_ratio: 0.50   # 0.0=完全收敛  0.5=均衡（默认）  0.7=激进探索
  total_queries: 8      # 进化后关键词总数
  min_signals_to_evolve: 3  # 信号不足时跳过，避免样本太少产生偏差
```

### 固定关键词（不参与进化）

在 `config.yaml` 中用 `pin: true` 锁定某个关键词，让它永远不被替换：

```yaml
arxiv:
  queries:
    - query: "my core research topic"
      pin: true              # 这条永远保留
    - "llm reasoning"        # 这条会被进化系统动态替换
```

---

## 🌱 种子文章管理

种子文章是权重最高的兴趣信号，适合录入导师推荐、同学分享或自己筛选的高价值论文。

### 打开管理界面

运行 `python main.py` 后，在浏览器打开：

```
http://127.0.0.1:19523/
```

界面支持：粘贴 arXiv 链接或 ID → 选择权重等级 → 填写备注 → 提交。重复添加同一篇文章时，若新等级更高则自动升档，否则提示已存在。

### 权重等级

| 等级 | 适用场景 | 进化权重 |
|------|----------|----------|
| 📌 Lv1 普通推荐 | 同学顺口提到、偶然看到的好文章 | × 1 |
| ⭐ Lv2 重要 | 导师建议读、近期相关工作 | × 3 |
| 🔥 Lv3 核心必读 | 与自己研究直接相关、必须掌握 | × 6 |

---

## ⭐ 点赞历史

`reports/likes_history.html` 是一个常驻的纯前端页面，通过本地服务实时读取 `likes.json`，每 30 秒自动刷新。无需每次运行重新生成。

功能包括：按标题/作者全文搜索、最新/最早排序切换、AI 总结摘要展示。

---

## ⚙️ 配置说明

### AI API 兼容性

本系统使用标准 HTTP 调用，支持所有 OpenAI 兼容接口，修改 `base_url` 即可切换：

| 服务商 | base_url |
|--------|----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 本地 Ollama | `http://localhost:11434/v1` |

### 自定义总结维度

在 `config.yaml` 的 `summary.dimensions` 中修改，AI 会严格按照这些维度提取信息：

```yaml
summary:
  dimensions:
    - "研究背景与动机：该研究试图解决什么问题？"
    - "核心方法与技术：提出了什么方法或框架？"
    - "实验结论：取得了怎样的量化结果？"
    - "研究局限性：论文明确指出了哪些局限？"
    # 可以自由增删维度
```

---

## 🕐 定时自动运行

### Linux / macOS（cron）

```bash
crontab -e
# 每天早上 8:00 运行，运行完后 1 小时自动退出（nohup 后台运行）
0 8 * * * cd /path/to/auto-paper-briefing && AI_API_KEY=sk-xxx python main.py &
```

> 注意：`main.py` 运行完论文处理后会保持进程运行以维持追踪服务。如果只需要定时抓取、不需要长期保持服务，可以在 cron 中用 `timeout 3600 python main.py` 限制运行时长。

### Windows（任务计划程序）

创建 `run.bat`：

```bat
set AI_API_KEY=sk-xxxxxxxxxxxxxxxx
cd /d C:\path\to\auto-paper-briefing
python main.py
```

在"任务计划程序"中新建任务，设置每日触发，操作指向此 `.bat` 文件。

---

## 🖥️ 命令行参数

```bash
python main.py                    # 标准运行（进化关键词 + 抓论文 + 保持追踪服务）
python main.py --no-evolve        # 跳过关键词进化，直接抓取
python main.py --evolve-only      # 仅执行关键词进化，不抓取论文
python main.py --config my.yaml   # 指定配置文件
```

---

## 📡 本地服务 API

`python main.py` 启动后，在 `http://127.0.0.1:19523` 上提供以下接口（HTML 通过 JS 自动调用，一般无需手动访问）：

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 种子文章管理 Web UI |
| `/track` | POST | 记录点击事件 |
| `/like` | POST | 记录点赞事件 |
| `/api/likes` | GET | 返回全部点赞记录（JSON） |
| `/api/seeds` | GET | 返回全部种子列表（JSON） |
| `/api/seeds` | POST | 添加或升档种子文章 |
| `/api/seeds/<id>` | DELETE | 删除种子文章 |

---

## ⚠️ 注意事项

**Google Scholar**：由于反爬机制严厉，本系统仅使用 arXiv 作为数据源（提供官方开放 API，无反爬问题）。

**大模型幻觉**：Prompt 要求"客观不评判"，Temperature 设为 0.1，但 AI 仍可能偶尔脑补。关键数据（如实验数字）建议结合原文核实。

**PDF 解析**：优先使用 PyMuPDF（效果最佳），未安装时自动降级到 pdfminer，再降级到内置基础提取。推荐安装：`pip install PyMuPDF`。

**网络环境**：访问 arXiv API 和 AI 接口在部分地区可能需要代理，请自行配置系统网络或使用国内兼容接口（DeepSeek / 阿里云）。

**关键词进化备份**：每次进化前，`config.yaml` 会自动备份为 `config.yaml.bak`，进化结果不满意时可手动还原。
