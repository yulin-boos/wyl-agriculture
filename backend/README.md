# 后端（精简运行版）

本目录只保留网页后端运行所需的 FastAPI 接口、识别模型、标签、知识库和依赖；训练数据、训练脚本、实验结果与测试文件均未包含。

## 首次安装（Windows PowerShell）

```powershell
cd C:\Users\yulin\yulin_obj\yulin_Code\Project\wyl\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

如需后端固定使用 API 密钥或连接 MySQL，请编辑 `.env`；网页也支持临时填写兼容接口的密钥。不要把真实密钥提交到版本库。

## 启动

双击 `run.bat`，或运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查地址：<http://127.0.0.1:8000/api/health>

默认数据库是本目录下 `.local/web.db`。设置 `DATABASE_URL` 后可改用 MySQL。
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

测试使用模拟服务和内存数据库配置，不连接云数据库、不调用付费 API。覆盖允许、拒绝、不确定、损坏图片、模型故障、HTTP 错误、临时文件清理，以及拒绝后不调用病害模型/建议接口、不写入记录。
