# SPEC 多资产行情研究

个人及少数同学自用的多资产行情研究看板，支持股票、指数、场内 ETF 和场外基金。当前版本 `v1.2`，默认私有模式，不对公网开放。

## 功能

- 四类真实数据试点：股票、基金、基准指数、ETF。
- 合成数据与真实数据隔离存储。
- 多资产 K 线面板、成交量、基金净值折线。
- 归一化表现比较、基准比较和轻量组合分析。
- 只读数据状态、数据质量检查。
- 本地数据管理面板：预检、显式确认后的增量更新、按代码新增真实资产、扩展历史。
- 单资产图与多资产对比图支持放大查看。
- 单资产图支持 1–250 日可配置均线，三档独立开关。
- 数据管理面板支持展开与折叠。

## 技术栈

- 后端：FastAPI、SQLite
- 前端：React、TypeScript、Vite、Apache ECharts

## 环境要求

- Python 3.11+
- Node.js 18+

## 快速启动

首次 clone 后，从零准备本地环境：

```powershell
git clone <你的私人仓库地址>
cd SPEC
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe scripts\init_demo_db.py --path data\demo-synthetic.db --reset
cd frontend
npm install
cd ..
```

随后启动服务：

Windows 下双击或在项目根目录运行：

```bat
start-dev.bat
```

手动启动：

```powershell
# 后端
$env:DATABASE_PATH='data/demo-synthetic.db'
$env:APP_MODE='private'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

前端默认地址：`http://127.0.0.1:5173`

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t .
.\.venv\Scripts\python.exe -m compileall -q backend scripts
cd frontend
node --experimental-strip-types --test src/charts/adapt.test.ts src/charts/movingAverage.test.ts src/charts/normalize.test.ts src/charts/sync.test.ts src/workspace/panelState.test.ts src/workspace/summary.test.ts src/analysis/portfolio.test.ts
npm run build
```

## 数据说明

仓库不包含真实行情数据库文件。`data/*.db` 已加入 `.gitignore`。真实行情数据涉及第三方数据源条款，请勿将 `data/live-*.db` 或 `data/demo-synthetic.db` 提交到公共仓库或再分发。

合成数据库可由脚本初始化：

```powershell
.\.venv\Scripts\python.exe scripts\init_demo_db.py --path data/demo-synthetic.db --reset
```

## 目录

```text
backend/    FastAPI 应用、数据库、服务、worker、测试
frontend/   React + TypeScript + Vite 前端
scripts/    数据初始化、导入、更新和质量检查脚本
docs/       设计、审计和路线图文档
config/     配置文件
```

## 许可与边界

本项目代码仅供个人学习研究使用。真实行情数据的获取和使用需遵守各数据源的服务条款，当前不授权公开再分发。项目不提供交易、下单、买卖建议或收益承诺。
