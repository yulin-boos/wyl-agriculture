# 后端（精简运行版）

本目录包含网页后端运行所需的 FastAPI 接口、识别模型、标签、知识库、依赖和接口回归测试；不包含训练数据、训练脚本和实验结果。

## 首次安装（Windows PowerShell）

```powershell
cd C:\Users\yulin\yulin_obj\yulin_Code\Project\wyl\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，配置 MySQL 的 `DATABASE_URL`；账户功能还需配置至少 32 字节的随机 `AUTH_SECRET_KEY`。网页仍支持临时填写建议 API 密钥。不要把真实密钥提交到版本库。

## MySQL 初始化与旧数据迁移

数据库结构依据 `禾诊_SQL数据库架构图.pptx`：`hezhen_db` 中有 `users`、`crops`、`diseases`、`knowledge_base`、`diagnosis_history`、`diagnosis_feedback` 六张表及八条外键。图中未给出类型、长度和全部字段；实现补充了现有诊断接口所需的快照、来源和时间字段。历史记录保留 UUID，其他表使用自增整数主键。

1. 在 MySQL 8.0.16 或更新版本中，通过 Navicat、Workbench 或 MySQL 客户端执行 `sql/禾诊_MySQL初始化.sql`（桌面同名文件内容相同）。包含 14 种作物、38 个模型分类及当前 JSONL 中的知识资料，不预置用户或密码。
2. 配置已存在且有 `hezhen_db` 读写权限的数据库账户。示例：`DATABASE_URL=mysql+pymysql://hezhen_app:YOUR_PASSWORD@127.0.0.1:3306/hezhen_db?charset=utf8mb4`。替换账号和密码，密码中的特殊字符需 URL 编码。脚本不创建 MySQL 账户。
3. 双击 `run.bat` 启动。直接使用 PowerShell 启动或运行管理脚本时，先把 `.env` 中的配置设置为环境变量；脚本不会自动读取 `.env`。

后端启动只检查架构，不自动建表或改表；不再默认创建 `.local/web.db`。旧 `diagnosis_records` 表和 SQLite 文件保留，但新接口只读取 `diagnosis_history`。如需保留旧历史，在初始化目标库后执行以下命令之一（`DATABASE_URL` 必须指向目标库）：

```powershell
# 旧记录和新表位于同一个数据库
python scripts/migrate_legacy_history.py
# 或从旧 SQLite 文件复制
python scripts/migrate_legacy_history.py --sqlite .local/web.db
```

迁移保留历史 UUID，跳过已迁移记录，不删除源记录；标签找不到或缺少客户端标识时回滚此次复制。已有同名但结构不同的六张表不会自动升级，请先备份并人工迁移。初始化脚本不会覆盖已存在的自然键对应数据，也不会删除业务数据。

仅本地开发测试可显式设置 `DATABASE_URL=sqlite:///.local/test.db`（先创建 `.local` 目录），然后运行 `python scripts/init_database.py` 建表并导入种子数据。生产使用配套 MySQL 脚本。MySQL 版本下限与外键、CHECK 的处理参考 [MySQL CHECK 约束说明](https://docs.oracle.com/cd/E17952_01/mysql-8.0-en/create-table-check-constraints.html)。

## 启动

双击 `run.bat`，或运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查地址：<http://127.0.0.1:8000/api/health>

诊断结果写入 `diagnosis_history`，作物与病害通过外键关联；`diagnosis_json`、`advice_json` 和报告文本保留当时的诊断快照。

## 用户账户与诊断反馈

| 接口 | 用途 |
| --- | --- |
| `POST /api/auth/register` | JSON：`username`、`password`、可选 `email`；只能注册普通用户 |
| `POST /api/auth/login` | JSON：`username`、`password`；返回有效期 24 小时的访问令牌 |
| `GET /api/auth/me` | 返回当前用户，须携带 `Authorization: Bearer <access_token>` |
| `GET /api/diseases?crop=Tomato` | 获取病害 ID、标签、中文名，供反馈选择修正病害 |
| `POST /api/diagnoses/{id}/feedback` | JSON：`is_correct`、可选 `corrected_disease_id`、`content`；每次诊断仅一份反馈，重复返回 409 |
| `GET /api/diagnoses/{id}/feedback` | 读取自己的反馈 |
| `DELETE /api/diagnoses/{id}` | 删除自己的诊断，并由外键级联删除其反馈 |

诊断、历史与反馈支持两种归属：已登录用户携带 Bearer 令牌，`client_id` 可省略；匿名用户继续提供原有 UUID `client_id`。匿名反馈和删除请求在查询参数中携带 `client_id`。任何请求不能指定其他 `user_id`，服务端从令牌读取；用户记录不会仅凭同一个客户端 ID 开放访问。匿名模式仍以客户端 UUID 作为访问凭据，兼容现有前端，不自动把匿名旧记录归入新账户。

密码使用随机盐和 PBKDF2-SHA256 哈希存储；不返回哈希。账户停用后已有令牌立即失效。修正病害必须属于原诊断作物、不同于原病害，且 `is_correct=false`。数据库 CHECK 确保诊断和反馈至少有一个归属标识。普通用户与管理员共用 `users` 表，通过 `role` 区分。

创建管理员：在配置好数据库的环境运行 `python scripts/create_admin.py`，按提示输入用户名和密码；不会预置默认密码或覆盖已有账户。管理员随后调用登录接口取得令牌。

## 管理员按模板添加知识库

管理员请求携带 `Authorization: Bearer <管理员登录令牌>`，普通用户返回 403，缺少认证返回 401。也保留可选的环境变量 `ADMIN_API_TOKEN` 作为兼容凭证；留空时只允许数据库管理员登录令牌。远程部署通过 HTTPS 调用，不要把管理员凭证放在公开前端代码中。

可在 `http://127.0.0.1:8000/docs` 点击 **Authorize** 输入凭证，再按下面顺序操作：

1. `GET /api/admin/knowledge/labels` 获取模型支持的标签及作物、病害中文名（包括尚未被知识库覆盖的标签）。
2. `GET /api/admin/knowledge/template?label=Tomato___Bacterial_spot` 获取 JSON 模板，已自动填入标签和作物、病害名称。
3. 填好模板后，将整个 JSON 作为请求体提交到 `POST /api/admin/knowledge`。成功返回 201 和已保存条目。

模板字段：

| 字段 | 填写规则 |
| --- | --- |
| `id` | 唯一来源 ID，1–100 位英文字母、数字、下划线或连字符，首位为字母或数字；重复返回 409 |
| `label`、`crop` | 使用模板预填值；标签必须属于模型，作物必须与标签一致 |
| `crop_zh`、`disease_zh` | 使用模板预填的数据库分类名称；不通过录入知识修改分类名称 |
| `title`、`source_org` | 资料标题、来源机构，必填，每项不超过 200 字 |
| `source_url` | 实际资料的 HTTP/HTTPS 链接，不超过 2048 字符 |
| `source_updated` | 来源更新时间说明，选填，不超过 100 字 |
| `tags` | 1–30 个非空关键词，每项不超过 200 字，自动去重 |
| `content` | 20–20000 字的资料正文，可按症状、传播条件、防治措施、预防、复核建议组织 |

模板中的空字段必须补齐，格式错误返回 422。来源内容需由管理员核实，接口只验证格式，不自动验证资料真伪或抓取网址。模板 `id` 对应 `knowledge_base.source_code`；数据库主键 `knowledge_base.id` 自动生成，`disease_id` 根据标签查找。新增内容先校验索引，再提交数据库事务；失败回滚。各 worker 在后续读取时检测数据库内容变化并重建本地检索索引，作物列表只展示启用且有知识覆盖的作物，按 `sort_order` 排序。

`knowledge/disease_guidance.jsonl` 现在仅用于初始化/导入，不再是运行时知识数据源。新增知识不会写回 JSONL；部署后直接修改 JSONL 不会影响在线数据库。数据库中的名称、标签与来源信息用于检索和引用。

本功能提供后端接口，可通过 API 文档页面操作；尚未增加业务前端管理页面。增加知识条目不能扩展识别模型本身的标签范围。

## 农产品图片校验（2026-09-10）

`POST /api/diagnoses` 在病害推理前执行独立的本地 CLIP 内容校验。允许农作物、病叶、果蔬、谷物等种植业图片；人物、车辆、屏幕截图、日用品等不相关图片，以及无法确认的图片，停止诊断。不调用建议 API、不保存诊断记录，临时上传文件会清理。

接口参数和成功返回格式保持不变。拒绝返回 HTTP 422：

```json
{"detail":"图片不是农作物或农产品，或无法确认其内容，已停止诊断。请上传清晰的作物、叶片或果蔬照片。","code":"non_agricultural_image"}
```

其他错误码：`uncertain_agricultural_image`（内容不确定，422）、`invalid_image`（图片不可读，422）、`image_gate_unavailable`（依赖或模型不可用，503）。`detail` 保持字符串，兼容现有客户端。校验故障时不会绕过检查。

### 部署

1. 在后端 Python 环境安装更新的 `requirements.txt`。
2. 本机已包含 `models/image_gate` 权重，但 GitHub 仓库不跟踪该大文件目录，部署时可从本机复制到服务器。若没有该目录，在联网环境运行 `python scripts/prepare_image_gate.py`（约 600 MB 权重）。准备后可离线运行，用户上传图片不会发送给该模型的提供方。
3. 重启后端服务。PowerShell/Linux 直接启动时需自行导出 `.env` 中的环境变量；现有 `run.bat` 会读取 `.env`。
4. 用 `python scripts/check_image_gate.py path/to/crop.jpg path/to/non_crop.jpg` 做纯图片校验，不访问数据库或建议 API。

权重来自 `openai/clip-vit-base-patch32`，固定版本 `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`，准备脚本将其保存为 safetensors。运行时只读取本地文件，不在请求期间下载。实现参考：https://huggingface.co/docs/transformers/v4.57.2/model_doc/clip 。

这是通用视觉模型的开放类别筛选，不能保证所有无关图片都被拒绝。相似度阈值 0.22、类别差值 0.02 是初始工程参数，需用真实业务正负样本继续评估；它们不是概率。此处的农产品范围为种植业，畜禽和加工食品不在范围内。通过此检查也不代表所选作物匹配、病害诊断正确，后续仍使用原有作物及病害判断。

### 回归测试

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

测试使用启用外键的临时 SQLite 数据库及模拟推理，不连接云数据库、不调用付费 API。覆盖图片校验、管理员权限、知识入库和回滚、并发重复提交、登录、记录归属隔离、反馈唯一性、修正病害校验和级联删除。建库脚本由相同的 ORM 元数据生成并核对六表八外键；这些检查不代替真实 MySQL 实例的导入联调。
