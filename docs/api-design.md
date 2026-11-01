# 只读 API 设计

本阶段只提供读取已入库缓存的接口，任何接口都不会触发抓取、回补、更新或配置修改。

## 1. 通用约定

- 默认监听 `127.0.0.1:8000`，由 `backend/app/core/config.py` 控制。
- 日期使用 ISO `YYYY-MM-DD`。
- 错误响应统一为 `{"error": {"code": "...", "message": "..."}}`。
- 错误响应不包含 traceback、SQL、数据库绝对路径或敏感配置。
- `APP_MODE` 只从环境变量读取，客户端不能通过参数切换模式。

## 2. 健康检查

`GET /api/v1/health`

响应：

```json
{
  "status": "ok",
  "app_mode": "private",
  "database": "ok",
  "authentication_implemented": false
}
```

数据库不可访问时返回 HTTP 503，`status` 与 `database` 为 `"error"`。`authentication_implemented` 当前恒为 `false`，如实反映尚未实现认证。

## 3. 资产列表与搜索

`GET /api/v1/assets`

查询参数：

- `asset_type`：可选，`stock`、`index`、`etf`、`open_fund`。
- `q`：可选，按代码或名称模糊搜索。
- `limit`：默认 50，范围 1-200。
- `offset`：默认 0，不能为负。

响应：

```json
{
  "items": [
    {
      "id": "stock-000001",
      "symbol": "000001",
      "name": "...",
      "asset_type": "stock",
      "market": "SZ",
      "currency": "CNY",
      "provider": "...",
      "price_semantics": "close",
      "volume_unit": "shares",
      "adjustment_mode": "qfq",
      "is_active": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## 4. 资产详情

`GET /api/v1/assets/{asset_id}`

返回单个资产元信息。`asset_id` 是系统内部 ID，与代码和资产类型共同区分不同资产；不同类别下的相同代码不会混为同一资产。不存在时返回 404 `ASSET_NOT_FOUND`。

## 5. 历史行情

`GET /api/v1/assets/{asset_id}/history`

查询参数：

- `start_date`：可选，ISO 日期。
- `end_date`：可选，ISO 日期。
- `limit`：默认 1000，范围 1-2000。

日线资产返回 `data_class="daily_bar"`，记录含 `date/open/high/low/close/volume/turnover/adjustment_mode/provider/quality_status`，按日期升序；`turnover` 可为空。

基金返回 `data_class="fund_nav"`，记录含 `date/unit_nav/accumulated_nav/provider/quality_status`，不生成 OHLC 或成交量。

顶层元信息包含 `asset_id`、`asset_type`、`data_class`、`start_date`、`end_date`、`latest_business_date`、`count`、`records`。

日期范围无数据时返回 `count=0` 和空数组；缺失记录保持缺失，不填零。非法日期、反向范围或非法 `limit` 返回 400。资产不存在返回 404。

## 6. 默认看板

`GET /api/v1/dashboard/default`

读取 `config/default-dashboard.json`（示例见 `config/default-dashboard.example.json`）。配置不存在时返回：

```json
{"configured": false, "assets": []}
```

配置存在时返回 `configured: true` 与 `assets`。该接口只读，不提供写入。

## 7. 安全边界

- 只读 API 只能读取缓存，不调用抓取。
- 没有管理 API、刷新 API 或写入 API。
- 私有模式不等于已认证；当前 `authentication_implemented=false`。
- 未配置 CORS 宽松策略；部署时不应把 CORS 当作访问控制。
- 默认只绑定回环地址，不提供公网监听默认值。

## 8. 契约冻结（阶段 1C-1）

以下以当前 `backend/app/api/routes.py`、`schemas.py` 和测试实际行为为准。

- `GET /api/v1/health`：200 时返回 `status/database/app_mode/authentication_implemented`；数据库异常返回 503，`status` 与 `database` 为 `"error"`。不返回数据库绝对路径。
- `GET /api/v1/assets`：参数 `asset_type`、`q`、`limit`（1-200，默认 50）、`offset`（默认 0）。响应 `items/total/limit/offset`。
- `GET /api/v1/assets/{asset_id}`：200 返回资产元信息；404 返回 `{"error":{"code":"ASSET_NOT_FOUND"}}`。
- `GET /api/v1/assets/{asset_id}/history`：参数 `start_date`、`end_date`（严格 `YYYY-MM-DD`）、`limit`（1-2000，默认 1000）。日线资产 `data_class="daily_bar"`，基金 `data_class="fund_nav"`。指数 `turnover` 可为 `null`。缺失日期不补零。日期范围无数据时 `count=0`、`records=[]`。
- `GET /api/v1/dashboard/default`：配置缺失返回 `{"configured":false,"assets":[]}`；配置存在返回 `configured:true`。
- 错误码：`INVALID_ASSET_TYPE`、`INVALID_LIMIT`、`INVALID_OFFSET`、`ASSET_NOT_FOUND`、`INVALID_DATE_RANGE`、`DASHBOARD_CONFIG_ERROR`。

前端默认通过开发服务器代理访问 `/api`，不使用浏览器直连 SQLite，也不访问真实行情源。

## 9. 本地运行

后端（默认只监听回环地址）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

前端开发服务器：

```powershell
cd frontend
npm run dev
```

前端生产构建：

```powershell
cd frontend
npm run build
```

浏览器联调用独立合成数据库：

```powershell
.\.venv\Scripts\python.exe scripts\init_demo_db.py --path data\demo-synthetic.db --reset
$env:DATABASE_PATH='C:\Users\28421\Desktop\code\SPEC\data\demo-synthetic.db'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
