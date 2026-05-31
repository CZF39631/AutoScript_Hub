# AutoScript Hub

低代码自动化脚本管理平台，用于管理和执行 Python 浏览器自动化脚本。

## 架构

- **服务端**：FastAPI + SQLite + React（Ant Design），部署在中心服务器
- **客户端**：Agent（轮询执行脚本）+ pywebview 桌面 UI，分发到员工电脑运行

## 快速开始

### 服务端安装

```bash
python setup.py --server
```

自动完成：创建 venv、安装依赖、构建前端、初始化数据库、生成配置。

启动服务端：

```bash
start.bat
```

### 客户端安装

```bash
python setup.py --client
```

配置服务器地址、登录凭据、本地目录等。

启动客户端：

```bash
start_client.bat
```

## 技术栈

- Python 3.8.10
- FastAPI + SQLAlchemy + SQLite
- React 19 + Ant Design 6 + Vite
- pywebview（桌面客户端）
- DrissionPage（浏览器自动化）

## 项目结构

```
├── backend/          # FastAPI 后端
│   ├── app/          # 应用代码（路由、模型、服务）
│   └── tests/        # 后端测试
├── frontend/         # React 前端
│   └── src/          # 页面、组件、API
├── client/           # 客户端
│   ├── agent/        # Agent（脚本轮询执行）
│   └── ui/           # pywebview 桌面 UI + 首次运行向导
├── setup.py          # 安装器（--server / --client）
├── start.bat         # 服务端启动脚本
└── config.json       # 服务端配置（运行时生成）
```
