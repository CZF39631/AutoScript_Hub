import { useEffect, useId, useRef, useState } from 'react'
import { Button, Input, Select, Spin, Typography } from 'antd'
import { useConnection } from '../contexts/ConnectionContext'
import { browserOptions, loadLocalBrowsers } from '../api/localBrowsers'

const wrap = { whiteSpace: 'normal', overflowWrap: 'anywhere' }

export default function BrowserPicker({ value, onChange, id, label }) {
  const { agentOnline, localApi } = useConnection()
  const descriptionId = useId()
  const selectRef = useRef(null)
  const controlRef = useRef(null)
  const [listHeight, setListHeight] = useState(240)
  const [manual, setManual] = useState(false)
  const [open, setOpen] = useState(false)
  const [retry, setRetry] = useState(0)
  const [result, setResult] = useState({ state: 'idle', browsers: [] })
  const available = agentOnline && Boolean(localApi)

  const changeOpen = (nextOpen) => {
    if (nextOpen && controlRef.current) {
      const control = controlRef.current
      if (window.innerHeight - control.getBoundingClientRect().bottom < 112) {
        control.scrollIntoView({ block: 'center', behavior: 'instant' })
      }
      setListHeight(Math.max(48, Math.min(240,
        window.innerHeight - control.getBoundingClientRect().bottom - 16)))
    }
    setOpen(nextOpen)
  }

  useEffect(() => {
    if (!open || !available) return undefined
    let active = true
    setResult({ state: 'loading', browsers: [], api: localApi })
    loadLocalBrowsers(localApi).then(browsers => {
      if (active) setResult({ state: 'ready', browsers, api: localApi })
    }).catch(() => {
      if (active) setResult({ state: 'error', browsers: [], api: localApi })
    })
    // Closing, disconnecting, switching clients and unmounting invalidate old responses.
    return () => { active = false }
  }, [open, available, localApi, retry])

  const state = result.api === localApi ? result.state : 'idle'
  const detecting = open && available && state === 'loading'
  const status = !available
    ? '本机 Agent 离线，无法检测；可手动填写路径，原值仍保留。'
    : detecting ? '正在检测本机已安装浏览器…'
      : state === 'error' ? '检测失败，请确认本机 Agent 已启动后重试。'
        : state === 'ready' && result.browsers.length === 0
          ? '未检测到浏览器，可手动填写便携版或其他浏览器路径。' : ''

  return (
    <div style={{ minWidth: 0 }}>
      <div className="browser-picker-row">
      <div className="browser-picker-control" ref={controlRef}>
      {manual ? (
        <Input
          id={id}
          aria-label={`${label || id || '浏览器'}（手动输入）`}
          allowClear
          aria-describedby={descriptionId}
          value={value ?? ''}
          onChange={event => onChange?.(event.target.value)}
          placeholder="如：C:\Program Files\Google\Chrome\Application\chrome.exe"
        />
      ) : (
        <Select
          ref={selectRef}
          id={id}
          title={value || undefined}
          aria-busy={detecting}
          aria-label={label || id || '选择本机浏览器'}
          aria-describedby={descriptionId}
          style={{ width: '100%', minWidth: 0 }}
          value={value || undefined}
          onChange={path => onChange?.(path ?? '')}
          allowClear
          open={open}
          onOpenChange={changeOpen}
          placement="bottomLeft"
          popupAlign={{ overflow: { adjustX: true, adjustY: false, shiftY: false } }}
          listHeight={listHeight}
          placeholder="选择本机浏览器"
          loading={detecting}
          virtual={false}
          options={browserOptions(available && state === 'ready' ? result.browsers : [], value)}
          optionRender={({ data }) => (
            <div style={wrap}>
              <div>{data.label}</div>
              <Typography.Text type="secondary" style={wrap}>{data.path}</Typography.Text>
            </div>
          )}
          notFoundContent={status || '打开列表以检测本机浏览器'}
        />
      )}
      </div>
      <Button
        type="link"
        size="small"
        style={{ paddingInline: 0 }}
        onClick={() => { setOpen(false); setManual(!manual) }}
      >
        {manual ? '切换到浏览器列表' : '手动输入路径'}
      </Button>
      </div>
      <div id={descriptionId} style={wrap}>
        <div role="status" aria-live="polite">
          {detecting && <Spin size="small" style={{ marginInlineEnd: 8 }} />}
          {status}
        </div>
        {available && state === 'error' && !manual && (
          <Button size="small" onClick={() => {
            selectRef.current?.focus()
            setOpen(true)
            setRetry(number => number + 1)
          }}>重新检测</Button>
        )}
      </div>
    </div>
  )
}
