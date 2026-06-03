# agent-ci-verify

<!-- cspell:ignore deepseek AKIA rglob venv pytest Moltbook -->

> AI Agent 产出的 CI/CD 验证管道。  
> **别信你的 Agent —— 验证它。**

[![CI](https://github.com/Lewis-404/agent-ci-verify/actions/workflows/ci.yml/badge.svg)](https://github.com/Lewis-404/agent-ci-verify/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/agent-ci-verify.svg)](https://pypi.org/project/agent-ci-verify/)
[![Python](https://img.shields.io/pypi/pyversions/agent-ci-verify.svg)](https://pypi.org/project/agent-ci-verify/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](./README.md)

---

## 为什么需要它？

AI Agent 正在进入生产环境，但**没人能回答“这个产出我能信吗”**。

市面上的工具全是“评估库”——import 进来自己写测试，本质上是自审自查，不是独立验证。

**agent-ci-verify 是 Agent 世界的 CI/CD 管道**——Agent 跑完任务，产出自动进入验证层，过审才放行。

## 快速开始

```bash
pip install agent-ci-verify
agent-ci ./agent-output/
```

```
agent-ci-verify v1.1.0
Output dir: ./agent-output/
Checkers: schema, fact, diff, integrity

                               📋 Schema Checker
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✅   │ json_valid           │                                                ┃
┃ ✅   │ yaml_valid           │                                                ┃
┃ ✅   │ security_scan        │ No secrets detected                            ┃
┗━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

                               🔍 Fact Checker
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✅   │ fact:file_count      │ 1 files for '*.json'                           ┃
┃ ✅   │ fact:content_contains│ 'success' found in result.json                 ┃
┗━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

╭────────────────────────────────── Verdict ────────────────────────────────╮
│   ✅  PASS                                                                 │
╰───────────────────────────────────────────────────────────────────────────╯
```

## 四层验证

| 层级 | 做什么 | 举例 |
|------|--------|------|
| **Schema（格式）** | 格式校验、结构合规、安全扫描 | JSON 合法吗？泄露了 API Key？必选文件在吗？ |
| **Fact（事实）** | 文件存在性、API 对账、LLM 裁判 | Agent 说生成了 result.json——真的吗？API 返回了 200？ |
| **Diff（对比）** | 回归检测、语义漂移 | 产出比基线变了多少？相似度跌破阈值了吗？ |
| **Integrity（完整性）** | Agent ↔ Skill 引用链完整性 | Agent YAML 引用的 skill 存在吗？.layers.yaml 有孤儿条目吗？ |

## 配置

在 Agent 项目根目录放一个 `.agent-ci.yaml`：

```yaml
pipeline:
  enabled_checkers: [schema, fact, diff, integrity]
  fail_fast: false

schema:
  security:
    enabled: true                # 扫描密钥泄露
  required_files:
    - "output/result.json"
  json_schemas:
    schemas/output.schema.json: "output/**/*.json"

fact:
  files:
    - pattern: "output/**/*.json"
      expected_count: 1
      min_size_bytes: 10
      content_checks:
        - type: contains
          value: "success"
        - type: not_contains
          value: "error"
  api:
    - endpoint: "https://api.example.com/health"
      expected_status: 200
  llm_judge:                     # 独立 LLM 裁判
    - file: "output/answer.md"
      rubric: "检查回答是否事实正确且完整"
      model: "deepseek-v4-flash"

diff:
  baseline: "./baseline-output/"
  semantic_threshold: 0.7
  max_changed_files: 5
```

## 安全扫描

内置检测模式：

- AWS Access Key (`AKIA...`)
- GitHub Token (`ghp_...`)
- OpenAI API Key (`sk-proj-...`)
- JWT Token
- 私钥 (RSA、EC、DSA、OpenSSH)
- 密码/密钥赋值语句

## CI 集成

```bash
# JSON 输出，方便程序解析
agent-ci --json ./output/ | jq .verdict
# "PASS"

agent-ci --json ./output/ | jq .summary
# {"total_checks": 6, "passed": 5, "warnings": 1, "failed": 0}
```

```yaml
# .github/workflows/agent-check.yml
- name: 验证 Agent 产出
  run: |
    pip install agent-ci-verify
    agent-ci --json ./output/ | tee result.json
```

## 审计报告与历史记录

```bash
# 生成自包含 HTML 审计报告
agent-ci --report ./output/
# ✅ Report saved: ./output/agent-ci-report-20260507-120000.html

# 查看验证历史
agent-ci --history
# 📋 Verification History (42 runs)
#   PASS                 20260507-120000  5✅ 0⚠️  0❌  → ./output/prod/
#   REJECT               20260507-115500  2✅ 1⚠️  2❌  → ./output/staging/
```

报告是自包含的 HTML，默认深色主题，适合审计和合规场景。

## Plugins

你可以在任意 `.py` 文件里编写自定义 checker：

```python
from agent_ci.checkers import BaseChecker
from agent_ci.types import CheckResult, CheckerReport, Severity

class SizeChecker(BaseChecker):
    name = "size"

    async def verify(self, output_dir):
        report = CheckerReport(checker_name=self.name)
        total = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
        limit = self.config.get("size", {}).get("max_bytes", 10_000_000)
        severity = Severity.FAIL if total > limit else Severity.PASS
        report.checks.append(CheckResult(
            checker=self.name, check_name="size_limit",
            severity=severity,
            message=f"Output size: {total:,} bytes (limit: {limit:,})",
        ))
        return report
```

在 `.agent-ci.yaml` 中这样配置：

```yaml
plugins:
  paths:
    - ./checks/

pipeline:
  enabled_checkers: [schema, fact, size]
  parallel: true  # 所有 checker 并发执行

size:
  max_bytes: 5000000
```

## Docker

```bash
# 克隆并构建
git clone https://github.com/Lewis-404/agent-ci-verify.git
cd agent-ci-verify

# 生成 API Key
export AGENT_CI_API_KEY=$(openssl rand -hex 32)

# 使用 docker-compose 启动
docker compose up -d

# 验证服务运行中（健康检查返回各 checker 状态）
curl http://localhost:8899/health
```

或手动构建：

```bash
docker build -t agent-ci-verify .
docker run -p 8899:8899 \
  -e AGENT_CI_API_KEY="$AGENT_CI_API_KEY" \
  -e AGENT_CI_ALLOWED_ROOTS="/data" \
  -v ./data:/data:ro \
  agent-ci-verify
```

## 开发

```bash
git clone https://github.com/Lewis-404/agent-ci-verify.git
cd agent-ci-verify
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

如果当前 shell 没有激活虚拟环境，本地验证命令请通过 `./.venv/bin/...` 执行。

## Service 模式（v1.0.5+）

可以作为常驻 HTTP API 运行，接入 CI/CD 管道。服务器模式使用结构化日志（structlog），如果 structlog 不可用则回退到标准日志。

```bash
# 安装 server 依赖
pip install 'agent-ci-verify[server]'

# 启动 API 服务
agent-ci serve

# 健康检查
curl http://127.0.0.1:8899/health
# {"status":"ok","version":"1.0.5","checkers":{"schema":"healthy","fact":"healthy","diff":"healthy","integrity":"healthy"}}

# 通过 API 验证 Agent 产出（需要 API Key）
curl -X POST http://127.0.0.1:8899/verify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"output_directory": "/path/to/agent/output"}'
```

> **注意：** `POST /verify` 接口需要 API Key 认证。使用 `openssl rand -hex 32` 生成密钥，并在启动服务器前设置 `AGENT_CI_API_KEY` 环境变量。

自定义主机/端口：`agent-ci serve --host 0.0.0.0 --port 8080`.

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| AGENT_CI_API_KEY | *(必填)* | POST /verify 接口的 API 认证密钥 |
| AGENT_CI_RATE_LIMIT | 10 | 每个 IP+Key 每时间窗口的最大请求数 |
| AGENT_CI_RATE_WINDOW | 60 | 速率限制窗口（秒） |

## 设计思路

这个项目的起源是一份深挖报告——我们扫描了 Moltbook 25+ 帖子、HN 40+ 讨论、GitHub 10+ 仓库后发现：**所有人都在做“评估库”（Library），没有人在做“验证基础设施”（Infrastructure）。**

- 竞品全是 `import tool → 写测试 → 跑测试` 的库模式
- 企业不敢把 Agent 放生产，不是因为 Agent 笨，而是因为没法回答“产出能不能信”
- Agent 越多，验证需求越大——这是一个验证基础设施机会

详见[深挖报告](https://github.com/Lewis-404/bot-shared-knowledge/blob/main/best-practices/2026-05-06-agent-verification-deep-dive.md)。

## 许可证

MIT — 详见 [LICENSE](./LICENSE)
