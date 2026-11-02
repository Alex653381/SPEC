import { useCallback, useEffect, useRef, useState } from "react";
import {
  getDataStatus,
  getUpdateJob,
  expandAsset,
  preflightUpdate,
  registerAsset,
  runUpdate,
} from "./api/client";
import { TYPE_LABELS } from "./workspace/labels";
import type { AssetType, DataStatus, RegisterResult, UpdateJob, UpdatePlan } from "./types";

const ASSET_TYPES: AssetType[] = ["stock", "index", "etf", "open_fund"];

export default function DataManagementPanel() {
  const [statuses, setStatuses] = useState<DataStatus[]>([]);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [assetType, setAssetType] = useState<AssetType>("stock");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [plan, setPlan] = useState<UpdatePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [job, setJob] = useState<UpdateJob | null>(null);
  const [running, setRunning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [newAssetType, setNewAssetType] = useState<AssetType>("stock");
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [registerResult, setRegisterResult] = useState<RegisterResult | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerConfirm, setRegisterConfirm] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [expandConfirm, setExpandConfirm] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [expandResult, setExpandResult] = useState<RegisterResult | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const pollRef = useRef<number | null>(null);

  const refreshStatus = useCallback(() => {
    getDataStatus()
      .then((data) => {
        setStatuses(data.items);
        setStatusError(null);
      })
      .catch((error: unknown) => setStatusError(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    return () => {
      if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    };
  }, []);

  function runPreflight() {
    setPlanError(null);
    setPlan(null);
    preflightUpdate({
      asset_type: assetType,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    })
      .then(setPlan)
      .catch((error: unknown) => setPlanError(error instanceof Error ? error.message : String(error)));
  }

  function requestRun() {
    if (!startDate || !endDate) {
      setPlanError("真实更新必须填写开始和结束日期");
      return;
    }
    setConfirmOpen(true);
  }

  function requestRegister() {
    if (!newCode || !newStart || !newEnd) {
      setRegisterError("代码、开始日期和结束日期均为必填");
      return;
    }
    setRegisterConfirm(true);
  }

  function confirmedRegister() {
    setRegisterConfirm(false);
    setRegistering(true);
    setRegisterError(null);
    setRegisterResult(null);
    registerAsset({
      asset_type: newAssetType,
      code: newCode,
      name: newName || undefined,
      start_date: newStart,
      end_date: newEnd,
      confirm: true,
    })
      .then((result) => {
        setRegisterResult(result);
        refreshStatus();
      })
      .catch((error: unknown) =>
        setRegisterError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setRegistering(false));
  }

  function requestExpand() {
    if (!newCode || !newStart || !newEnd) {
      setRegisterError("代码、开始日期和结束日期均为必填");
      return;
    }
    setExpandConfirm(true);
  }

  function confirmedExpand() {
    setExpandConfirm(false);
    setExpanding(true);
    setRegisterError(null);
    setExpandResult(null);
    expandAsset({
      asset_type: newAssetType,
      code: newCode,
      start_date: newStart,
      end_date: newEnd,
      confirm: true,
    })
      .then((result) => {
        setExpandResult(result);
        refreshStatus();
      })
      .catch((error: unknown) =>
        setRegisterError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setExpanding(false));
  }

  function confirmedRun() {
    setConfirmOpen(false);
    setRunning(true);
    setJob(null);
    runUpdate({ asset_type: assetType, start_date: startDate, end_date: endDate })
      .then((created) => {
        setJob(created);
        pollJob(created.id);
      })
      .catch((error: unknown) => {
        setPlanError(error instanceof Error ? error.message : String(error));
        setRunning(false);
      });
  }

  function pollJob(jobId: string) {
    getUpdateJob(jobId)
      .then((current) => {
        setJob(current);
        if (current.status === "running") {
          pollRef.current = window.setTimeout(() => pollJob(jobId), 1000);
        } else {
          setRunning(false);
          refreshStatus();
        }
      })
      .catch((error: unknown) => {
        setPlanError(error instanceof Error ? error.message : String(error));
        setRunning(false);
      });
  }

  return (
    <section className="panel data-management">
      <div className="panel-header">
        <div>
          <div className="asset-name">数据管理</div>
          <div className="asset-meta">仅本地管理真实数据更新</div>
        </div>
        <div className="panel-actions">
          <button
            className="asset-button"
            onClick={() => setCollapsed((current) => !current)}
            aria-expanded={!collapsed}
          >
            {collapsed ? "展开" : "收起"}
          </button>
          <button className="asset-button" onClick={refreshStatus} disabled={running}>
            刷新状态
          </button>
        </div>
      </div>

      {!collapsed ? (
        <>
          {statusError ? <div className="status">{statusError}</div> : null}

          <div className="data-status-grid">
            {statuses.map((item) => (
              <div className="data-status-card" key={item.asset_id}>
                <div className="asset-name">
                  {item.asset_id} · {TYPE_LABELS[item.asset_type]}
                </div>
                <div className="asset-meta">{item.provider}</div>
                <div className="asset-meta">
                  {item.record_count} 条 · {item.first_date ?? "-"} 至 {item.last_date ?? "-"}
                </div>
                {item.duplicate_dates.length ? (
                  <div className="muted">重复日期：{item.duplicate_dates.join(", ")}</div>
                ) : null}
                <div className="muted">评估：{item.assessment}</div>
                <div className="muted">
                  质量：{item.quality_status ?? "unknown"} · 问题 {item.quality_issue_count ?? 0}
                </div>
              </div>
            ))}
          </div>

          <div className="analysis-controls">
            <label>
              资产类型
              <select value={assetType} onChange={(event) => setAssetType(event.target.value as AssetType)}>
                {ASSET_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {TYPE_LABELS[type]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              开始日期
              <input value={startDate} onChange={(event) => setStartDate(event.target.value)} placeholder="YYYY-MM-DD" />
            </label>
            <label>
              结束日期
              <input value={endDate} onChange={(event) => setEndDate(event.target.value)} placeholder="YYYY-MM-DD" />
            </label>
            <button className="asset-button" onClick={runPreflight} disabled={running}>
              预检
            </button>
            <button className="asset-button" onClick={requestRun} disabled={running}>
              {running ? "更新中…" : "更新真实数据"}
            </button>
          </div>

          {planError ? <div className="status">{planError}</div> : null}
          {plan ? (
            <div className="summary">
              <span>资产 {plan.asset_code}</span>
              <span>数据库 {plan.database}</span>
              <span>最新日期 {plan.latest_date ?? "-"}</span>
              <span>计划区间 {plan.window ? `${plan.window.start} 至 ${plan.window.end}` : "需显式指定"}</span>
            </div>
          ) : null}

          {job ? (
            <div className="summary">
              <span>任务 {job.id}</span>
              <span>状态 {job.status}</span>
              {job.result?.status ? <span>结果 {job.result.status}</span> : null}
              {job.result?.error_category ? <span>错误类别 {job.result.error_category}</span> : null}
              {job.result?.error_summary ? <span>错误 {job.result.error_summary}</span> : null}
            </div>
          ) : null}

          <div className="panel-header">
            <div className="asset-name">新增真实资产</div>
          </div>
          <div className="analysis-controls">
            <label>
              类型
              <select value={newAssetType} onChange={(event) => setNewAssetType(event.target.value as AssetType)}>
                <option value="stock">股票</option>
                <option value="etf">ETF</option>
                <option value="index">指数</option>
                <option value="fund">基金</option>
              </select>
            </label>
            <label>
              代码
              <input value={newCode} onChange={(event) => setNewCode(event.target.value)} placeholder="股票 sz600519 · ETF 510300 · 指数 000688 · 基金 110022" />
            </label>
            <label>
              名称（可选）
              <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="可选" />
            </label>
            <label>
              开始日期
              <input value={newStart} onChange={(event) => setNewStart(event.target.value)} placeholder="YYYY-MM-DD" />
            </label>
            <label>
              结束日期
              <input value={newEnd} onChange={(event) => setNewEnd(event.target.value)} placeholder="YYYY-MM-DD" />
            </label>
            <button className="asset-button" onClick={requestRegister} disabled={registering || running}>
              {registering ? "注册中…" : "新增真实资产"}
            </button>
            <button className="asset-button" onClick={requestExpand} disabled={expanding || running}>
              {expanding ? "扩展中…" : "扩展历史"}
            </button>
          </div>

          {registerError ? <div className="status">{registerError}</div> : null}
          {registerResult ? (
            <div className="summary">
              <span>状态 {registerResult.status}</span>
              <span>资产 {registerResult.asset_id ?? "-"}</span>
              <span>来源 {registerResult.provider ?? "-"}</span>
              <span>插入 {registerResult.inserted ?? 0}</span>
              <span>跳过 {registerResult.skipped ?? 0}</span>
            </div>
          ) : null}
          {expandResult ? (
            <div className="summary">
              <span>状态 {expandResult.status}</span>
              <span>资产 {expandResult.asset_id ?? "-"}</span>
              <span>插入 {expandResult.inserted ?? 0}</span>
              <span>跳过 {expandResult.skipped ?? 0}</span>
            </div>
          ) : null}

          {confirmOpen ? (
            <div className="confirm-overlay">
              <div className="confirm-box">
                <div className="asset-name">确认真实更新</div>
                <div className="asset-meta">
                  资产 {assetType}，区间 {startDate} 至 {endDate}。将发起真实网络请求，并可能写入对应试点数据库。
                </div>
                <div className="analysis-controls">
                  <button className="asset-button" onClick={confirmedRun} disabled={running}>
                    确认执行
                  </button>
                  <button className="remove-button" onClick={() => setConfirmOpen(false)} disabled={running}>
                    取消
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {registerConfirm ? (
            <div className="confirm-overlay">
              <div className="confirm-box">
                <div className="asset-name">确认新增真实资产</div>
                <div className="asset-meta">
                  类型 {newAssetType}，代码 {newCode}，区间 {newStart} 至 {newEnd}。将发起真实网络请求，并写入对应试点数据库。
                </div>
                <div className="analysis-controls">
                  <button className="asset-button" onClick={confirmedRegister} disabled={registering}>
                    确认注册
                  </button>
                  <button className="remove-button" onClick={() => setRegisterConfirm(false)} disabled={registering}>
                    取消
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {expandConfirm ? (
            <div className="confirm-overlay">
              <div className="confirm-box">
                <div className="asset-name">确认扩展历史</div>
                <div className="asset-meta">
                  类型 {newAssetType}，代码 {newCode}，区间 {newStart} 至 {newEnd}。将发起真实网络请求，并增量写入对应试点数据库。
                </div>
                <div className="analysis-controls">
                  <button className="asset-button" onClick={confirmedExpand} disabled={expanding}>
                    确认扩展
                  </button>
                  <button className="remove-button" onClick={() => setExpandConfirm(false)} disabled={expanding}>
                    取消
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
