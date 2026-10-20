# TravelMate

基于 FastAPI 与 React 的旅行客服和多智能体应用。支持政策问答、行程规划、预订管理和人工客服，所有正式业务写入均需用户确认。

## 项目功能

- **旅行客服**：自然语言咨询、多轮对话、历史恢复、订单与已保存行程查询。侧栏“会话管理”支持搜索、重命名及删除；删除会话保留订单等业务记录，进行中任务或待确认操作需先停止。
- **知识库问答**：LlamaIndex 解析 Markdown／文本 PDF，结合 Qdrant 向量检索、BM25、RRF、父块合并与重排，展示适用政策及原文依据。
- **行程规划**：LangGraph 并行编排航班和酒店专家，校验日期、库存、预算与证据，生成可选方案。
- **预订服务**：报价、预订、变更和取消；支持重复预订拦截、归属校验、版本复核和幂等执行。
- **复杂调整**：Deep Agents 使用任务清单、只读专业子助手和内部工作区研究替代方案，用户确认后保存正式报告。
- **人工客服与知识管理**：服务申请、领取、补充、回复及关闭；知识导入、发布、撤回和恢复。
- **会话与恢复**：MySQL 持久化业务记录及 LangGraph checkpoint，Redis 缓存会话投影，独立 worker 执行任务，前端通过 SSE 获取进度。

技术栈：Python 3.12、FastAPI、SQLAlchemy、LangChain、LangGraph、Deep Agents、LlamaIndex、MySQL 9.6、Qdrant、Redis、React、TypeScript、Vite。

模型配置：`qwen3.7-flash`、`qwen3.7-text-embedding`（1024 维）、`qwen3.7-text-rerank`。需要可调用这些模型的 DashScope 账号，知识入库和对话会产生实际 API 用量。

机票、酒店和库存使用本地 MySQL 演示目录，未接入真实供应商、支付或出票服务。知识样例为合成资料；当前记忆限定于会话，不包含跨会话长期画像。扫描 PDF、OCR 和真实景点预约不在当前范围内。

## 本地 Docker 部署

### 1. 准备配置

安装 Docker（含 Compose V2）及 Python 3（仅用于生成本地配置）。以下命令用于首次部署；已有 `.env` 时，请先备份并对照 `.env.example` 补齐配置，保留原连接信息。在项目根目录执行：

```bash
cp -n .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
content = path.read_text()
for placeholder in (
    'replace-with-a-random-mysql-root-password',
    'replace-with-a-random-redis-password',
    'replace-with-a-random-secret-at-least-32-characters',
):
    content = content.replace(placeholder, secrets.token_hex(32))
path.write_text(content)
path.chmod(0o600)
PY
```

输入 DashScope API Key 后回车，输入不会回显。密钥只由主机环境传入容器，不写入 `.env`、镜像或前端：

```bash
read -r -s TRAVELMATE_DASHSCOPE_API_KEY
export TRAVELMATE_DASHSCOPE_API_KEY
```

默认 API Host 为 `https://dashscope.aliyuncs.com`。其他地域或专属业务空间可在 `.env` 修改 `TRAVELMATE_DASHSCOPE_API_HOST`，只填写 HTTPS 域名。

数据默认持久化在项目的 `.docker-data/` 下。需要统一放入本机 DockerData 时，将 `.env` 中的 `TRAVELMATE_DATA_DIR` 改为 `${HOME}/DockerData/TravelMate`；MySQL、Qdrant、Redis 和研究产物分别使用独立子目录。请勿指向其他项目已有的数据目录。

### 2. 构建与初始化

```bash
docker compose build
docker compose up -d mysql qdrant redis
docker compose run --rm api python -m scripts.doctor
docker compose run --rm api python -m app.knowledge
docker compose up -d api worker frontend
```

MySQL 数据目录首次为空时，容器自动执行 `travelmate.sql`，创建表、演示账号以及 20 个城市的演示目录：380 条有向航线，未来 60 天每天两班、合计 45,600 条航班；200 家合成酒店、400 个房型和 90 天住宿库存（另保留基础样例）。该 SQL 仅用于空库初始化，不会在普通重启时重新执行，也不包含清库操作。知识库初始化通过真实模型解析、嵌入并写入 Qdrant；默认包含 20 个城市指南；初始化只补齐缺失文档，已有发布或撤回状态不会被初始化覆盖，后续更新在管理员页面管理。

首次构建需要下载镜像和依赖。启动前确保下列端口未被其他服务占用；如果正在运行此前的本地 API、前端或同端口数据库，请先停止对应服务，避免重复启动。

| 服务 | 本机地址 |
| --- | --- |
| 产品前端 | http://127.0.0.1:15173 |
| 后端 API／接口文档 | http://127.0.0.1:18080/docs |
| MySQL | 127.0.0.1:13316 |
| Qdrant／Dashboard | http://127.0.0.1:16333/dashboard |
| Redis | 127.0.0.1:6379 |

worker 不开放端口；它从 MySQL 领取任务。API 和 worker 必须同时运行。Redis 密码由 `.env` 生成，Qdrant 在本地部署中未启用认证，所有公开端口均绑定 `127.0.0.1`。

已有数据库需要补充演示目录时，可以安全追加；相同 ID 不覆盖已有价格、版本或剩余库存。`--days` 支持 1—365，默认 60：

```bash
docker compose run --rm api python -m app.seed --days 60
docker compose run --rm api python -m app.knowledge
```

城市资料集中在 `data/cities.json`；`python -m app.seed --export-sql` 可同步 `travelmate.sql` 的默认演示目录段。业务资源均为合成数据，不是城市之间真实存在的航班时刻、酒店报价或预约状态。

### 3. 登录体验

| 账号 | 密码 | 权限 |
| --- | --- | --- |
| alice、bob | tutorial123 | 旅行工作台、助手、行程、订单与服务中心 |
| admin | tutorial123 | 额外提供客服工作台和知识管理 |

这些账号和数据库普通用户密码仅供本地演示，不能直接用于公网部署。资源查询的可选日期会显示在工作台；规划和预订时请使用已有库存覆盖的日期。

### 4. 日常管理

```bash
docker compose ps
docker compose logs -f api worker
docker compose down
docker compose up -d
```

`down` 保留绑定目录中的数据。更新已有数据库时，先停止应用并升级会话表（幂等增加字段，保留记录），再启动：

```bash
docker compose stop api worker frontend
docker compose build api worker frontend
docker compose run --rm --no-deps api python -m scripts.migrate
docker compose up -d
```

本地 Conda 开发环境可在启动后端前执行 `python -m scripts.migrate`。重新打开终端时需再次导出 API Key。不要删除数据目录来升级应用，也不要向已有业务库重复执行初始化 SQL。

遇到模型或数据库连接失败时，先运行 `scripts.doctor` 并检查日志、端口和代理配置。本机存在 HTTP 代理时，可为本地地址配置 `NO_PROXY=localhost,127.0.0.1,::1`；容器内部服务使用 Compose 网络中的服务名连接。

## 许可与资源

代码采用 [MIT License](LICENSE)。上海封面图片来自 [Unsplash](https://images.unsplash.com/photo-1548919973-5cef591cdbc9)，仅作城市风景展示，不代表酒店实拍；该图片适用其来源许可，不包含在代码 MIT 授权中。
