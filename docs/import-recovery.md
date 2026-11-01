# 导入故障恢复指引

当前只使用合成数据，单进程运行边界。本文说明失败分类和人工处理方式。

## 1. 冲突与幂等语义

- 同批次完全相同的重复记录：同一批次内只保留首条，其余跳过。
- 同批次同键但内容不同：后出现的记录跳过并计入冲突，不覆盖。
- 与已有记录完全相同：跳过，不重复插入。
- 与已有记录同键但内容不同：跳过并计入冲突，不覆盖。
- 部分记录合法、部分不合法：输入质量检查失败发生在任何写入之前，整批拒绝。
- 同一批次重复执行：幂等，`inserted=0`，已有数据不变。
- 中途写入异常：事务回滚，不产生部分提交。
- 写后检查失败：业务数据已提交，任务标记 `failed`，摘要保留已提交数量和问题。

## 2. 失败分类与处理

- `INPUT_VALIDATION_FAILED`：修复输入批次后创建新任务重试。
- 数据库写入异常：先检查事务是否回滚，再重试；不得手工删除已有数据。
- `POST_CHECK_FAILED`：先查看业务表中已提交记录，再决定人工修复或新增任务；不要无依据删除数据。
- 任务记录更新失败：不视为业务成功，保留错误摘要，业务数据状态需单独核对。

## 3. 查询任务历史

任务记录在 `jobs` 表，字段含 `status`、`error_code`、`error_summary`、`execution_summary`、时间戳。可只读查看：

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; conn=sqlite3.connect('data/demo-synthetic.db'); print(conn.execute('SELECT id,status,error_code,error_summary FROM jobs ORDER BY created_at DESC LIMIT 10').fetchall())"
```

## 4. 避免重试造成重复

- 重试创建新的任务 ID，保留历史记录。
- 导入使用业务唯一键 `(asset_id, trade_date, adjustment_mode)` 或 `(asset_id, nav_date)`，重复数据会被跳过。
- 不要直接改历史任务状态。

## 5. 单进程边界

当前保护依赖 SQLite 行级条件更新和唯一约束，只保证单进程内安全，不提供多进程分布式锁。
