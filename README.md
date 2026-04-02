# 美妆智能顾问 (Beauty Agent)

一个多 Agent 驱动的护肤美妆智能助手，采用 ReAct 模式、混合检索和分层记忆架构，能够理解用户肤质需求，提供个性化产品推荐、成分分析、护肤品搭配建议和购买服务。

## 功能特性

### 🤖 多 Agent 架构
- **Orchestrator**：任务分发与协调中心
- **推荐 Agent**：基于用户肤质和需求推荐产品
- **分析 Agent**：产品详情与成分安全分析
- **搭配 Agent**：护肤品配伍检测与使用流程规划
- **电商 Agent**：自有品牌购买与订单查询

### 🔍 混合检索
- **向量搜索**：ChromaDB 语义检索（支持中文）
- **关键词搜索**：BM25 排序算法
- **结果融合**：Reciprocal Rank Fusion (RRF)

### 🧠 4 层记忆系统
| 层级 | 存储方式 | 用途 |
|------|---------|------|
| 短期 | deque 滑动窗口 | 最近 40 条对话 |
| 中期 | 会话摘要 | 压缩关键信息 |
| 任务 | 问卷状态机 | 多轮问答进度 |
| 长期 | SQLite 持久化 | 用户档案与历史 |

### 📋 智能问卷
首次使用自动收集：肤质类型 → 皮肤问题 → 预算范围 → 品牌偏好

## 快速开始

### 1. 环境要求

- Python 3.11+
- ANTHROPIC_API_KEY（ Claude API Key）

### 2. 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-username/beauty-agent.git
cd beauty-agent

# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 ANTHROPIC_API_KEY
```

### 4. 运行

```bash
python main.py
```

浏览器访问 http://localhost:7860

## 效果演示

首次对话会触发问卷流程：

```
👤: 你好
🤖: 欢迎！为了给您更好的推荐，请告诉我您的肤质类型是？
👤: 敏感肌
🤖: 感谢！那您最想改善的皮肤问题是？
...
```

## 项目结构

```
beauty-agent/
├── agents/          # 5 个 Agent（orchestrator + 4 子 Agent）
├── tools/           # 4 个工具（搜索、分析、规划、订单）
├── retrieval/       # 混合检索（vector + BM25 + RRF）
├── memory/          # 4 层记忆系统
├── storage/         # SQLite 数据库
├── questionnaire/   # 问卷状态机
├── data/            # Mock 数据（产品、成分、订单）
├── config.py        # 配置管理
└── main.py          # Gradio 入口
```

## 技术栈

| 类别 | 技术 |
|------|------|
| LLM | Claude Opus 4.6（Anthropic API） |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2（本地） |
| UI | Gradio 4.44+ |
| 向量数据库 | ChromaDB |
| 关键词搜索 | rank-bm25 + jieba |
| 持久化 | SQLite（WAL 模式） |

## 验证测试

```bash
# 推荐测试
"推荐一款敏感肌面霜"

# 分析测试
"烟酰胺的作用是什么"

# 搭配测试
"烟酰胺和视黄醇能一起用吗"

# 电商测试
"帮我买 [产品名]"
"我的订单到哪了"
```

## 注意事项

- 所有产品数据均为 mock 数据，仅供演示
- 首次运行会自动初始化数据库并构建向量索引
- 支持多用户（通过 user_id 区分会话）
- 会话记忆在进程内，重启后清空（长期记忆保留在 SQLite）

## License

MIT License