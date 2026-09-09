# 前端（精简源码版）

本目录是独立的 Vue 3 + Vite 前端，只保留页面源码和构建配置，不包含 `node_modules` 与构建缓存。

双击本目录的 `run.bat`；首次启动会自动安装前端依赖。也可以手动运行：

```powershell
cd C:\Users\yulin\yulin_obj\yulin_Code\Project\wyl\frontend
npm install
npm run dev
```

浏览器访问：<http://localhost:5173>

开发代理已指向云端接口 `http://170.106.137.89/api`，健康检查地址为 `http://170.106.137.89/api/health`，本地运行时不需要启动相邻的 `backend`。如果云端地址发生变化，请修改 `vite.config.js` 中的 `target`；该值只写服务器根地址，不要在末尾重复添加 `/api`。
