import { useEffect, useState, useCallback, useRef } from 'react'
import { Alert, Descriptions, Tag, Spin, Button, Space, message, Popconfirm } from 'antd'
import { FolderOpenOutlined, StopOutlined, ReloadOutlined, BugOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import api from '../api/client'
import LogViewer from '../components/LogViewer'
import DiagnosticReport from '../components/DiagnosticReport'
import { useConnection } from '../contexts/ConnectionContext'
import { canOpenResultLocally, firstResultPath, loadRunDetail } from '../api/offlineData'
import { formatScriptVersion } from '../utils/scriptVersion'
import { formatServerTime } from '../utils/dateTime'
import { taskError } from '../utils/taskScheduling'
import { formatIssueParams } from '../utils/issueDetail'

import { useI18n } from '../i18n/useI18n'

const statusColors = { pending: 'blue', running: 'orange', success: 'green', failed: 'red', cancelled: 'default', queued: 'blue', claimed: 'processing', preparing: 'processing', cancel_requested: 'orange', unknown: 'warning', skipped: 'default' }
const buttonStyle = { whiteSpace: 'normal', height: 'auto', minHeight: 32, paddingBlock: 4 }
const activeStates = ['pending', 'queued', 'claimed', 'preparing', 'running', 'cancel_requested', 'unknown']

export default function RunDetail() {
  const { t } = useI18n()
  const translation = useRef(t)
  useEffect(() => { translation.current = t }, [t])
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [issueModal, setIssueModal] = useState(false)
  const { online, agentOnline, agentId, localApi } = useConnection()
  const localOnly = /^[LS]/.test(String(id)) || !online
  const runStatus = run?.status

  const load = useCallback(() => {
    setLoading(true)
    loadRunDetail({ id, online, api, localApi })
      .then(setRun)
      .catch(() => message.error(translation.current(localOnly ? 'execution.localRunMissing' : 'execution.loadFailed')))
      .finally(() => setLoading(false))
  }, [id, online, localApi, localOnly])

  // Called by LogViewer when SSE stream ends — refresh run status without flashing the spinner.
  const onLogComplete = useCallback(() => {
    if (!localOnly) api.get(`/api/runs/${id}`).then(r => setRun(r.data)).catch(() => {})
  }, [id, localOnly])

  useEffect(load, [load])

  useEffect(() => {
    if (!activeStates.includes(runStatus)) return undefined
    let active = true
    const interval = setInterval(() => {
      loadRunDetail({ id, online, api, localApi }).then(value => { if (active) setRun(value) }).catch(() => {})
    }, localOnly ? 1000 : 5000)
    return () => { active = false; clearInterval(interval) }
  }, [id, online, localOnly, localApi, runStatus])

  const onCancel = async () => {
    try {
      const endpoint = localOnly ? `/local/runs/${id}/cancel` : run.task_execution_id ? `/api/tasks/executions/${run.task_execution_id}/cancel` : `/api/runs/${id}/cancel`
      await (localOnly ? localApi : api).post(endpoint, {})
      message.success(t('execution.cancelSent'))
      load()
    } catch (e) {
      message.error(taskError(e, t))
    }
  }

  const onOpenResult = async () => {
    try {
      const path = firstResultPath(run.result_files)
      if (!path) throw new Error(t('execution.noResultPath'))
      await localApi.post('/local/results/open', { path })
    } catch (error) {
      const detail = error.response?.data?.error
      message.error(typeof detail === 'string' ? detail : error.message || t('execution.openFailed'))
    }
  }

  if (loading) return <Spin />
  if (!run) return <div>{t('execution.runMissing')}</div>

  const sm = { color: statusColors[run.status] || 'default', text: Object.hasOwn(statusColors, run.status) ? t(`execution.runState.${run.status}`) : run.status }
  const isAlive = activeStates.includes(run.status)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0 }}>{t('execution.detailTitle', { id: run.id })}</h2>
        <Space wrap>
          <Button style={buttonStyle} icon={<ReloadOutlined />} onClick={load}>{t('execution.refresh')}</Button>
          {isAlive && (
            <Popconfirm title={t('execution.cancelConfirm')} description={t('execution.cancelProcessHint')} onConfirm={onCancel}>
              <Button style={buttonStyle} danger icon={<StopOutlined />} disabled={run.status === 'cancel_requested'}>{t('execution.cancelRun')}</Button>
            </Popconfirm>
          )}
          {!localOnly && (run.status === 'failed' || run.status === 'success') && (
            <Button style={buttonStyle} icon={<BugOutlined />} onClick={() => setIssueModal(true)}>{t('execution.reportIssue')}</Button>
          )}
        </Space>
      </div>
      {run.status === 'unknown' && <Alert type="warning" showIcon title={t('execution.unknownRunHint')} style={{ marginBottom: 16 }} />}
      <Descriptions bordered size="small" column={2} className="run-detail__descriptions" style={{ marginBottom: 16 }}>
        <Descriptions.Item label={t('execution.scriptId')}>{run.script_id}</Descriptions.Item>
        <Descriptions.Item label={t('execution.version')}>{formatScriptVersion(run.script_semantic_version, run.script_version)}</Descriptions.Item>
        <Descriptions.Item label={t('execution.status')}><Tag color={sm.color}>{sm.text}</Tag></Descriptions.Item>
        <Descriptions.Item label={t('execution.duration')}>{run.duration_sec != null ? t('execution.seconds', { value: run.duration_sec }) : '-'}</Descriptions.Item>
        <Descriptions.Item label={t('execution.startedAt')}>{formatServerTime(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label={t('execution.finishedAt')}>{formatServerTime(run.finished_at)}</Descriptions.Item>
        {run.error_msg && <Descriptions.Item label={t('execution.errorMessage')} span={2}>{run.error_msg}</Descriptions.Item>}
        {run.result_files && (
          <Descriptions.Item label={t('execution.resultFiles')} span={2}>
            {canOpenResultLocally(run, agentOnline, agentId) ? (
              <Button style={buttonStyle} icon={<FolderOpenOutlined />} onClick={onOpenResult}>{t('execution.openResult')}</Button>
            ) : t('execution.resultFilesOnExecutor')}
          </Descriptions.Item>
        )}
        {run.params && (
          <Descriptions.Item label={t('execution.params')} span={2}>
            <pre className="run-detail__params">{formatIssueParams(run.params).text}</pre>
          </Descriptions.Item>
        )}
      </Descriptions>
      <LogViewer
        runId={run.id}
        status={run.status}
        onComplete={onLogComplete}
        localOnly={localOnly}
        localApi={localApi}
      />

      <DiagnosticReport key={id} open={issueModal} onCancel={() => setIssueModal(false)}
        runId={localOnly ? undefined : id} scriptVersion={formatScriptVersion(run.script_semantic_version, run.script_version)} />
    </div>
  )
}
