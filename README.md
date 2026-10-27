# SignalWatch 舆情雷达 MVP

一个可直接运行的公开舆情监测与危机预警工作台。当前版本接入了 5 个真实公开来源，完成采集、规范化、去重、关键词命中、风险分级、事件聚合、证据展示和人工处置闭环。

## 当前能做什么

- 聚合微博热搜、抖音热榜、今日头条热榜、B站热门和中新网即时新闻
- 设置品牌、人物、事件和政策关键词
- 自动扫描并持久化到本地 SQLite
- 对监测关键词进行命中判断
- 基于规则提取风险类型和风险等级
- 将相似标题跨来源聚合为事件
- 查看事件证据链、原始链接、来源、榜单名次和热度
- 标记“研判中”“已处置”“误报”
- 展示来源健康状态、最近扫描时间和错误
- 对需要登录或授权供应商的来源保存本机凭据
- 通过统一授权接口协议接入微博搜索、抖音搜索、微信、小红书、快手
- 记录完整 Agent 运行轨迹：计划、来源、规则研判、模型调用、告警和失败信息
- 对新告警去重，并通过通用 Webhook、企业微信、飞书或 SMTP 邮件发送
- 导出包含证据链、风险依据和覆盖说明的 Markdown 事件报告
- 使用 23 条合成回归集评测规则效果，并支持配置真实模型后对比评测
- 提供 Docker、Docker Compose、GitHub Actions 和演示脚本

## 快速启动

无需安装第三方依赖，要求 Python 3.9 或以上：

```bash
cd /Users/tanjiayu/Documents/Codex/2026-10-27/xia
python3 app.py
```

然后打开：

```text
http://127.0.0.1:8765
```

停止服务：在运行终端按 `Ctrl+C`。

### 当前机器直接启动（推荐）

```bash
cd /Users/tanjiayu/Documents/Codex/2026-10-27/xia
PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 app.py
```

不配置模型时会自动使用规则引擎，采集、告警和页面均可正常工作。

只执行一次采集后退出：

```bash
python3 app.py --scan-once
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

运行回归评测：

```bash
python3 scripts/evaluate.py
```

使用 Docker：

```bash
docker compose up --build
```

默认只绑定 `127.0.0.1`。若要改变绑定地址，请先阅读安全说明并设置 `MONITOR_BIND_ADDRESS`。

> 如果本机 Python 尝试向不可写的系统缓存目录写 `.pyc`，可以使用：
>
> ```bash
> PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 app.py
> ```

## 数据源状态

| 来源 | 类型 | 当前状态 | 边界 |
|---|---|---|---|
| 微博热搜 | 公开热榜 | 已验证可用 | 公开热搜榜，不是微博站内全量帖子搜索 |
| 抖音热榜 | 公开热榜 | 已验证可用 | 公开热榜接口，不包含站内评论和全量视频搜索 |
| 今日头条热榜 | 公开热榜 | 已验证可用 | 公开热榜 |
| B站热门 | 公开榜单 | 已验证可用 | 综合热门视频榜 |
| 中新网即时新闻 | 权威新闻 RSS | 已验证可用 | 中新网即时新闻 |
| 微博关键词搜索 | 全文检索 | 需授权/验证 | 不能通过公开热榜替代站内全文搜索 |
| 抖音关键词搜索 | 全文检索 | 需授权供应商 | 站内搜索存在签名和风控，不建议通过绕过方式接入 |
| 微信公众号 | 图文内容 | 需授权供应商 | 需授权数据接口或合规采集服务 |
| 小红书 | 社交内容 | 需授权供应商 | 需官方或授权数据接口 |
| 快手 | 社交内容 | 需授权供应商 | 需官方或授权数据接口 |

平台接口和授权规则可能变化。**“公开可访问”不等于“可以任意采集、长期存储或向客户转售”。** 上线前需要逐项核对平台条款、著作权、个人信息、数据安全和适用资质。

## 授权接口协议

Web 页面可以逐项保存 Session Cookie、API Token 或 API Key。凭据保存在：

```text
data/credentials.json
```

文件权限设置为当前用户可读写。API 永不回传凭据明文。

授权来源只有在同时配置可调用接口地址后才会进入扫描。系统使用以下 GET 协议：

```http
GET {endpoint}?keyword={关键词}&limit=50
```

鉴权头：

- `session_cookie`：`Cookie: <用户提供的 Cookie>`
- `api_token`：`Authorization: Bearer <Token>`
- `api_key`：`X-API-Key: <Key>`

接口需要返回以下任一结构：

```json
{
  "items": [
    {
      "id": "provider-item-id",
      "title": "内容标题",
      "url": "https://example.com/item/1",
      "summary": "摘要",
      "author": "发布账号",
      "published_at": "2026-10-27T10:00:00+08:00",
      "rank": 1,
      "hot_value": 12345
    }
  ]
}
```

或：

```json
{
  "data": {
    "items": [
      {
        "id": "provider-item-id",
        "title": "内容标题",
        "url": "https://example.com/item/1"
      }
    ]
  }
}
```

这是供应商适配协议，不代表任何平台官方接口。拿到真实官方接口或授权供应商文档后，可以在 `monitor_agent/sources.py` 中增加专用适配器。

## 接入 DeepSeek 或其他模型

系统支持任意兼容 OpenAI Chat Completions 协议的模型服务。模型层只分析“命中监测词”的候选内容，默认每次最多 20 条，输出结构化 JSON；规则引擎继续作为兜底，不会因为模型超时而丢失采集结果。

### 方式一：云端或自建推理 API（推荐）

```bash
export MONITOR_AI_BASE_URL='https://你的模型服务地址/v1'
export MONITOR_AI_API_KEY='你的密钥'
export MONITOR_AI_MODEL='你的模型名'
export MONITOR_AI_WIRE_API='chat_completions'  # 或 responses
python3 app.py
```

DeepSeek 官方 API、其他云模型、vLLM 自建服务，只要提供 OpenAI 兼容接口，都可以使用。具体模型名和计费以对应服务商的当前文档为准。

### 方式二：本地小模型

当前机器是 **Apple M1、8GB 统一内存**。可以运行 1.5B 到 4B 级量化模型，7B 级即使 4-bit 也会非常紧张。完整 DeepSeek V3/R1 级模型不适合这台机器。

可安装 Ollama、LM Studio 或其他本地推理服务，然后填写其 OpenAI 兼容地址。例如 Ollama 常见本地地址：

```bash
export MONITOR_AI_BASE_URL='http://127.0.0.1:11434/v1'
export MONITOR_AI_MODEL='你在本地实际安装的模型名'
python3 app.py
```

不要照抄不存在的模型名；先使用推理服务自己的模型列表命令确认已下载模型。小模型更适合做相关性分类、摘要和风险初筛，不适合独立做事实核查、法律判断或危机决策。

### 为什么不让舆情系统直接调用 Codex CLI

本机 Codex CLI 支持 `codex exec --json --output-schema`，技术上可以由程序调用，但更适合开发任务，不适合作为线上模型 API：

- 它带有代码执行、工具权限和本地会话语义，不是纯推理接口
- 运行成本、延迟和并发行为不适合舆情采集批处理
- 授权和会话状态与业务 API 生命周期不同
- 失败时会受本地工具、权限和工作目录影响

因此当前实现选择通用模型接口，不把 Codex CLI 作为生产依赖。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MONITOR_HOST` | `127.0.0.1` | Web 服务监听地址 |
| `MONITOR_PORT` | `8765` | Web 服务端口 |
| `MONITOR_SCAN_INTERVAL` | `300` | 自动扫描间隔，最少 60 秒 |
| `MONITOR_HTTP_TIMEOUT` | `15` | 单次网络请求超时 |
| `MONITOR_ITEMS_PER_SOURCE` | `60` | 每个来源单次最多保留条目 |
| `MONITOR_DATA_DIR` | `./data` | 数据目录 |
| `MONITOR_DB_PATH` | `./data/monitor.db` | SQLite 数据库路径 |
| `MONITOR_CREDENTIAL_PATH` | `./data/credentials.json` | 授权凭据文件路径 |
| `MONITOR_AI_BASE_URL` | 空 | OpenAI 兼容模型服务基础地址 |
| `MONITOR_AI_API_KEY` | 空 | 模型 API Key，本地模型可留空 |
| `MONITOR_AI_MODEL` | 空 | 模型名称 |
| `MONITOR_AI_WIRE_API` | `chat_completions` | `chat_completions` 或 `responses` |
| `MONITOR_AI_TIMEOUT` | `45` | 模型请求超时秒数 |
| `MONITOR_AI_MAX_ITEMS` | `20` | 每次扫描最多送入模型的候选条数 |
| `MONITOR_ALERT_WEBHOOK_URL` | 空 | 告警 Webhook 地址 |
| `MONITOR_ALERT_WEBHOOK_TYPE` | `generic` | `generic`、`wecom` 或 `feishu` |
| `MONITOR_ALERT_MIN_RISK` | `medium` | 最低发送风险等级 |
| `MONITOR_ALERT_TIMEOUT` | `10` | 告警 Webhook 超时秒数 |
| `MONITOR_SMTP_HOST` | 空 | SMTP 服务器 |
| `MONITOR_SMTP_PORT` | `465` | SMTP 端口 |
| `MONITOR_SMTP_USER` | 空 | SMTP 用户名 |
| `MONITOR_SMTP_PASSWORD` | 空 | SMTP 密码 |
| `MONITOR_SMTP_FROM` | 空 | 发件人 |
| `MONITOR_ALERT_EMAIL_TO` | 空 | 收件人，多个地址用逗号分隔 |
| `MONITOR_SMTP_SSL` | `true` | SMTP 是否使用 SSL |

示例：

```bash
MONITOR_PORT=9000 MONITOR_SCAN_INTERVAL=600 python3 app.py
```

## 主要 API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/state` | 事件、原始信号、来源和统计 |
| `GET` | `/api/health` | 服务健康检查 |
| `POST` | `/api/scan` | 立即扫描全部可用来源 |
| `POST` | `/api/watch-terms` | 保存监测词并重新分析缓存 |
| `POST` | `/api/authorize` | 保存来源授权 |
| `POST` | `/api/authorize/revoke` | 撤销来源授权 |
| `POST` | `/api/reviews` | 标记事件证据的处理状态 |
| `GET` | `/api/runs/<run_id>` | 获取单次 Agent 运行轨迹 |
| `GET` | `/api/reports/event?event_id=...` | 下载 Markdown 事件报告 |

## 目录结构

```text
app.py                       Web 服务和调度器
monitor_agent/
  analyzer.py                关键词、风险和事件聚合
  config.py                  环境配置
  credentials.py             本机授权凭据存储
  database.py                SQLite 数据层
  service.py                 采集流程和状态组装
  sources.py                 公开来源与授权来源连接器
  notifications.py           Webhook 与邮件告警
  evaluation.py              回归评测与指标计算
static/
  index.html                 工作台页面
  styles.css                 响应式界面
  app.js                     前端交互
tests/                       无网络自动化测试
eval/                        合成回归评测集
scripts/evaluate.py          评测入口
docs/                        架构、演示、评测和简历说明
outputs/                     生成的评测与项目说明
data/                        SQLite 和本机授权文件
```

## 设计边界

- 当前风险判断为规则引擎，不是事实认定或法律结论。
- 当前事件聚合使用标题相似度和共同监测词，适合 MVP，不适合作为最终的事件识别模型。
- 当前统计包含公开热榜，不等于“全网舆情”。
- 当前已经提供可配置的模型研判层，但默认未配置模型时使用规则引擎。
- 模型输出采用校准后的保守合并策略：模型不能降低规则风险，也不能直接从低风险跨级升级为高风险；规则中风险由人工决定是否升级。
- 当前授权能力只负责安全保存和统一接口接入。若使用 Cookie 直接连接平台私有接口，需要用户自行确认平台授权条款，并且专用接口仍需实测。
- 不允许绕过验证码、登录、访问控制或平台风控。
- 不允许自动发布公关声明、联系媒体、投诉、删帖或代表客户执行外部动作。

## 项目文档

- [架构说明](docs/ARCHITECTURE.md)
- [评测说明](docs/EVALUATION.md)
- [演示脚本](docs/DEMO.md)
- [简历项目描述](docs/RESUME.md)
- [评测报告](outputs/evaluation-report.md)

## 推荐后续版本

1. 接入一个已获授权的数据供应商，补全微博、抖音、微信、小红书和快手的全文检索。
2. 使用真实历史事件和人工双标数据替换合成评测集，报告真实召回率、误报率和检测延迟。
3. 增加租户、RBAC、PostgreSQL、Redis 任务队列和结构化 Trace。
4. 增加值班排班、告警确认和升级链路。
5. 将本地凭据存储替换为 OAuth 或专用密钥管理服务。
