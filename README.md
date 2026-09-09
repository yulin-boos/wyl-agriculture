# 农作物病虫害诊疗系统

Vue 3 网页前端与 FastAPI 后端。后端在病害诊断前检查图片是否为农作物、叶片或种植业农产品；无关和不确定图片停止诊断。

## 目录

- `frontend/`：网页前端。
- `backend/`：诊断接口、知识库、图片内容检查、测试。
- `backend/models/best.pt`：约 3 MB 的病害模型，随源码版本管理。
- `backend/models/image_gate/`：约 600 MB 的通用图片检查模型，不提交 Git；首次部署使用下载脚本准备。

密钥、数据库、上传内容、压缩包、虚拟环境和本地备份均不提交。服务器自己的 `.env` 和模型目录不会被普通 `git pull` 覆盖。

## Linux 服务器首次部署

仓库为私有，先为服务器配置 GitHub 只读 deploy key，再执行：

```bash
git clone git@github.com:yulin-boos/wyl-agriculture.git
cd wyl-agriculture/backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写已有云数据库连接、API 密钥等。
.venv/bin/python scripts/prepare_image_gate.py
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file .env
```

首次模型下载需要访问 Hugging Face；也可从已准备好的本机复制整个 `backend/models/image_gate`。后续普通源码更新无需再次下载。生产环境应由现有服务管理器启动上述命令，并经反向代理访问。

已有服务部署在其他目录时，先在新目录完成依赖、模型和配置验证，再调整服务工作目录，不要直接覆盖正在运行的目录或复制数据库到 Git。

## 后续更新

在仓库根目录运行：

```bash
git status --short
git pull --ff-only origin main
cd backend
.venv/bin/python -m pip install -r requirements.txt
# 通过服务器现有的 systemd / Docker / 面板重启后端服务。
curl -f http://127.0.0.1:8000/api/health
```

`--ff-only` 会在分支分叉时停止，不自动覆盖服务器改动。若服务器需要重建前端，在 `frontend` 目录执行 `npm install` 与 `npm run build`，将 `dist` 交给现有静态站点服务；生产反向代理需要将 `/api` 转发给后端。

## 本机提交后续修改

```bash
git status
git add backend frontend README.md .gitignore .gitattributes
git commit -m "Describe the update"
git push origin main
```

提交前检查变更，不要强制添加被忽略的密钥或数据库。模型阈值与范围限制见 [后端说明](backend/README.md)，测试结果见 [图片校验验收记录](backend/IMAGE_GATE_VALIDATION.md)。
