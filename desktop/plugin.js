/**
 * Daily reading: the Desktop page for hermes-daily-reading.
 *
 * Reads the digest the plugin built (summary, audio, items) through this
 * plugin's own backend (dashboard/plugin_api.py, mounted by Hermes at
 * /api/plugins/daily-reading/ only while the plugin is enabled), and offers
 * three actions per item: mark read, save as fragment, turn into article idea
 * (preview first, then an explicit confirmation).
 *
 * Every feed and model text is rendered as a React text child, never as HTML.
 * Links open only when they are http(s), through the host's external opener.
 *
 * Plain ESM loaded uncompiled: UI is jsx() calls, not JSX syntax; only
 * @hermes/plugin-sdk, react and react/jsx-runtime resolve. The views (DigestView,
 * ItemCard, IdeaDialog, FeedsView) are pure functions of their props so they can
 * be tested in Node without a browser; the containers own hooks and requests.
 */

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  GlyphSpinner,
  host,
  Input,
  PALETTE_AREA,
  ROUTES_AREA,
  ScrollArea,
  SIDEBAR_NAV_AREA,
  queryClient,
  useQuery
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useRef, useState } from 'react'

export const ID = 'daily-reading'
const PAGE_PATH = '/daily-reading'

let rest = null
let openExternalFn = async () => false

export function setRuntime ({ restFn, openExternal }) {
  rest = restFn
  if (openExternal) openExternalFn = openExternal
}

// ── helpers ────────────────────────────────────────────────────────────────
export function errText (e) {
  const raw = String(e?.message || e || '')
  const m = /"message"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(raw)
  if (m) {
    try { return JSON.parse(`"${m[1]}"`) } catch { /* fall through */ }
  }
  return raw.slice(0, 300)
}

export function errCode (e) {
  const m = /"code"\s*:\s*"([a-z_]+)"/.exec(String(e?.message || e || ''))
  return m ? m[1] : ''
}

export function safeLink (link) {
  return typeof link === 'string' && /^https?:\/\//i.test(link) ? link : null
}

function text (value) {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function hostOf (url) {
  try { return new URL(url).host } catch { return text(url) }
}

const IDEA_LABEL = { sent: 'Idea sent', failed: 'Idea failed', unknown: 'Idea outcome unknown', running: 'Sending idea…' }

// ── pure views ─────────────────────────────────────────────────────────────
export function ItemCard ({ item, actions, busy = {}, error = '', onToggleRead, onFragment, onIdea, onOpen }) {
  const link = safeLink(item.link)
  const fragment = actions?.fragment || { enabled: false, hint: '' }
  const idea = actions?.idea || { enabled: false, hint: '' }
  const ideaState = item.idea?.state
  return jsxs('article', {
    className: `${ID}-item${item.read ? ` ${ID}-read` : ''}`,
    'data-item': item.id,
    children: [
      jsxs('header', {
        className: `${ID}-item-head`,
        children: [
          jsx('span', { className: `${ID}-num`, children: `${item.number}.` }),
          link
            ? jsx(Button, { variant: 'link', 'data-action': 'open', onClick: () => onOpen?.(link), children: text(item.title) })
            : jsx('span', { 'data-role': 'title', children: text(item.title) }),
          item.read ? jsx(Badge, { 'data-role': 'read-badge', children: 'Read' }) : null,
          ideaState ? jsx(Badge, { 'data-role': 'idea-badge', children: IDEA_LABEL[ideaState] || ideaState }) : null
        ]
      }),
      item.paragraph ? jsx('p', { 'data-role': 'paragraph', children: text(item.paragraph) }) : null,
      !item.paragraph && item.excerpt ? jsx('p', { 'data-role': 'excerpt', className: `${ID}-muted`, children: text(item.excerpt) }) : null,
      jsx('div', {
        className: `${ID}-muted`,
        'data-role': 'sources',
        children: (item.sources || []).map(hostOf).join(' · ') + ((item.themes || []).length ? ` — ${item.themes.join(', ')}` : '')
      }),
      jsxs('div', {
        className: `${ID}-actions`,
        children: [
          jsx(Button, {
            size: 'sm', variant: 'ghost', 'data-action': 'read', disabled: !!busy.read,
            onClick: () => onToggleRead?.(item), children: item.read ? 'Mark unread' : 'Mark read'
          }),
          jsx(Button, {
            size: 'sm', variant: 'ghost', 'data-action': 'fragment',
            disabled: !fragment.enabled || !!busy.fragment || item.fragment_saved,
            title: fragment.enabled ? '' : fragment.hint,
            onClick: () => onFragment?.(item), children: item.fragment_saved ? 'Saved as fragment' : 'Save as fragment'
          }),
          jsx(Button, {
            size: 'sm', variant: 'ghost', 'data-action': 'idea',
            disabled: !idea.enabled || !!busy.idea || ideaState === 'running',
            title: idea.enabled ? '' : idea.hint,
            onClick: () => onIdea?.(item), children: 'Turn into article idea'
          }),
          !fragment.enabled ? jsx('span', { className: `${ID}-hint`, 'data-role': 'fragment-hint', children: text(fragment.hint) }) : null,
          !idea.enabled ? jsx('span', { className: `${ID}-hint`, 'data-role': 'idea-hint', children: text(idea.hint) }) : null
        ]
      }),
      error ? jsx('div', { className: `${ID}-error`, 'data-role': 'error', children: text(error) }) : null
    ]
  })
}

export function IdeaDialog ({ preview, busy = false, result = null, error = '', onConfirm, onCancel }) {
  if (!preview) return null
  const p = preview.payload || {}
  return jsxs('div', {
    className: `${ID}-dialog`, role: 'dialog', 'data-role': 'idea-dialog',
    children: [
      jsx('h3', { children: 'Turn into article idea' }),
      jsx('div', { 'data-role': 'idea-title', children: text(p.title) }),
      jsx('div', { className: `${ID}-muted`, 'data-role': 'idea-url', children: text(p.url) }),
      jsx('div', { className: `${ID}-muted`, 'data-role': 'idea-sources', children: text(p.sources) }),
      jsx('p', { 'data-role': 'idea-summary', children: text(p.summary) || '(no summary paragraph)' }),
      jsx('div', { className: `${ID}-muted`, 'data-role': 'idea-target', children: `Target: ${text(preview.target)} ${text(preview.target_detail)}` }),
      preview.warning ? jsx('div', { className: `${ID}-warning`, 'data-role': 'idea-warning', children: text(preview.warning) }) : null,
      result ? jsx('div', { 'data-role': 'idea-result', children: `${IDEA_LABEL[result.state] || result.state}${result.output ? `: ${text(result.output)}` : ''}` }) : null,
      error ? jsx('div', { className: `${ID}-error`, 'data-role': 'idea-error', children: text(error) }) : null,
      jsxs('div', {
        className: `${ID}-actions`,
        children: [
          result
            ? jsx(Button, { 'data-action': 'idea-close', onClick: () => onCancel?.(), children: 'Close' })
            : jsx(Button, { 'data-action': 'idea-confirm', disabled: busy, onClick: () => onConfirm?.(preview.token), children: busy ? 'Sending…' : 'Confirm' }),
          result ? null : jsx(Button, { variant: 'ghost', 'data-action': 'idea-cancel', disabled: busy, onClick: () => onCancel?.(), children: 'Cancel' })
        ]
      })
    ]
  })
}

export function DigestView ({ digest, dates = [], selected, run, audioSlot = null, itemProps = {}, onSelect, onRun, onShowFeeds }) {
  const toolbar = jsxs('div', {
    className: `${ID}-toolbar`,
    children: [
      jsx('select', {
        'data-role': 'dates', value: selected || '', onChange: e => onSelect?.(e.target.value),
        children: dates.map(d => jsx('option', { value: d, children: d }, d))
      }),
      jsx(Button, { size: 'sm', 'data-action': 'run', disabled: !!run?.running, onClick: () => onRun?.(false), children: run?.running ? 'Building…' : 'Build today' }),
      jsx(Button, { size: 'sm', variant: 'ghost', 'data-action': 'rebuild', disabled: !!run?.running, onClick: () => onRun?.(true), children: 'Rebuild' }),
      jsx(Button, { size: 'sm', variant: 'ghost', 'data-action': 'feeds', onClick: () => onShowFeeds?.(), children: 'Feeds' }),
      run?.notice ? jsx('span', { className: `${ID}-muted`, 'data-role': 'run-notice', children: text(run.notice) }) : null
    ]
  })
  if (!digest) {
    return jsxs('div', {
      className: `${ID}-page`,
      children: [toolbar, jsx(EmptyState, {
        'data-role': 'empty',
        title: 'No digest yet',
        description: 'Build one now, or schedule the "Daily reading" blueprint.'
      })]
    })
  }
  const items = digest.items || []
  return jsxs('div', {
    className: `${ID}-page`,
    children: [
      toolbar,
      jsx('h2', { children: `Daily reading — ${text(digest.date)}` }),
      digest.intro ? jsx('p', { 'data-role': 'intro', className: `${ID}-intro`, children: text(digest.intro) }) : null,
      digest.summary_failed ? jsx('div', { className: `${ID}-warning`, 'data-role': 'summary-failed', children: 'The summary could not be made; the items are listed without it.' }) : null,
      audioSlot,
      items.length === 0
        ? jsx('div', { className: `${ID}-muted`, 'data-role': 'message', children: text(digest.message) || 'No items.' })
        : items.map(item => jsx(ItemCard, { item, actions: digest.actions, ...(itemProps[item.id] || {}), ...(itemProps['*'] || {}) }, item.id))
    ]
  })
}

export function FeedsView ({ feeds = [], problems = [], error = '', draft = {}, onDraft, onAdd, onEdit, onBack }) {
  return jsxs('div', {
    className: `${ID}-page`,
    children: [
      jsxs('div', { className: `${ID}-toolbar`, children: [jsx(Button, { size: 'sm', variant: 'ghost', 'data-action': 'back', onClick: () => onBack?.(), children: '← Digest' }), jsx('h2', { children: 'Feeds' })] }),
      feeds.map(f => jsxs('div', {
        className: `${ID}-feed`, 'data-feed': f.url,
        children: [
          jsx('span', { children: text(f.title || f.url) }),
          f.theme ? jsx(Badge, { children: text(f.theme) }) : null,
          f.paused ? jsx(Badge, { 'data-role': 'paused', children: 'Paused' }) : null,
          jsx(Button, { size: 'sm', variant: 'ghost', 'data-action': f.paused ? 'resume' : 'pause', onClick: () => onEdit?.(f.paused ? 'resume' : 'pause', f.url), children: f.paused ? 'Resume' : 'Pause' }),
          jsx(Button, { size: 'sm', variant: 'ghost', 'data-action': 'remove', onClick: () => onEdit?.('remove', f.url), children: 'Remove' })
        ]
      }, f.url)),
      problems.map((p, i) => jsx('div', { className: `${ID}-warning`, children: `Skipped ${text(p)}` }, `p${i}`)),
      jsxs('div', {
        className: `${ID}-toolbar`,
        children: [
          jsx(Input, { 'data-role': 'new-url', placeholder: 'https://example.com/feed.xml', value: draft.url || '', onChange: e => onDraft?.({ ...draft, url: e.target.value }) }),
          jsx(Input, { 'data-role': 'new-theme', placeholder: 'theme (optional)', value: draft.theme || '', onChange: e => onDraft?.({ ...draft, theme: e.target.value }) }),
          jsx(Button, { size: 'sm', 'data-action': 'add', onClick: () => onAdd?.(draft), children: 'Add feed' })
        ]
      }),
      error ? jsx('div', { className: `${ID}-error`, 'data-role': 'feeds-error', children: text(error) }) : null
    ]
  })
}

// ── containers ─────────────────────────────────────────────────────────────
function AudioPlayer ({ day, count }) {
  const [index, setIndex] = useState(1)
  const [src, setSrc] = useState(null)
  const [error, setError] = useState('')
  const urlRef = useRef(null)
  useEffect(() => { setIndex(1) }, [day])
  useEffect(() => {
    let cancelled = false
    setError('')
    if (!count) return undefined
    rest(`/digest/${day}/audio/${index}`).then(out => {
      if (cancelled) return
      const bytes = Uint8Array.from(atob(out.data), c => c.charCodeAt(0))
      const url = URL.createObjectURL(new Blob([bytes], { type: out.mime }))
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
      urlRef.current = url
      setSrc(url)
    }).catch(e => { if (!cancelled) setError(errText(e)) })
    return () => { cancelled = true }
  }, [day, index, count])
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }, [])
  if (!count) return null
  return jsxs('div', {
    className: `${ID}-audio`,
    children: [
      src ? jsx('audio', { controls: true, src, autoPlay: index > 1, onEnded: () => { if (index < count) setIndex(index + 1) } }) : jsx(GlyphSpinner, {}),
      count > 1 ? jsx('span', { className: `${ID}-muted`, children: `Part ${index} of ${count}` }) : null,
      error ? jsx('span', { className: `${ID}-error`, children: error }) : null
    ]
  })
}

function DailyReadingPage () {
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('digest')
  const [busy, setBusy] = useState({})
  const [errors, setErrors] = useState({})
  const [preview, setPreview] = useState(null)
  const [ideaBusy, setIdeaBusy] = useState(false)
  const [ideaResult, setIdeaResult] = useState(null)
  const [ideaError, setIdeaError] = useState('')
  const [runNotice, setRunNotice] = useState('')
  const [draft, setDraft] = useState({})
  const [feedsError, setFeedsError] = useState('')

  const list = useQuery({ queryKey: [ID, 'digests'], queryFn: () => rest('/digests'), refetchInterval: 15000 })
  const day = selected || list.data?.latest || null
  const digest = useQuery({ queryKey: [ID, 'digest', day], queryFn: () => rest(`/digest/${day}`), enabled: !!day })
  const feeds = useQuery({ queryKey: [ID, 'feeds'], queryFn: () => rest('/feeds'), enabled: view === 'feeds' })
  const refresh = () => queryClient.invalidateQueries({ queryKey: [ID] })

  const act = async (item, kind, call) => {
    setBusy(b => ({ ...b, [item.id]: { ...(b[item.id] || {}), [kind]: true } }))
    setErrors(e => ({ ...e, [item.id]: '' }))
    try { await call(); refresh() } catch (e) { setErrors(x => ({ ...x, [item.id]: errText(e) })) } finally {
      setBusy(b => ({ ...b, [item.id]: { ...(b[item.id] || {}), [kind]: false } }))
    }
  }
  const handlers = {
    onOpen: url => { void openExternalFn(url) },
    onToggleRead: item => act(item, 'read', () => rest(`/digest/${day}/items/${item.id}/read`, { method: 'POST', body: { read: !item.read } })),
    onFragment: item => act(item, 'fragment', () => rest(`/digest/${day}/items/${item.id}/fragment`, { method: 'POST', body: {} })),
    onIdea: item => act(item, 'idea', async () => {
      setIdeaResult(null); setIdeaError('')
      setPreview(await rest(`/digest/${day}/items/${item.id}/idea/preview`, { method: 'POST', body: {} }))
    })
  }
  const itemProps = { '*': handlers }
  for (const [id, b] of Object.entries(busy)) itemProps[id] = { busy: b, error: errors[id] || '' }
  for (const [id, e] of Object.entries(errors)) itemProps[id] = { ...(itemProps[id] || {}), error: e }

  const onConfirm = async token => {
    setIdeaBusy(true); setIdeaError('')
    try { setIdeaResult(await rest('/ideas/confirm', { method: 'POST', body: { token } })); refresh() } catch (e) {
      setIdeaError(errCode(e) === 'stale' ? `${errText(e)}` : errText(e))
    } finally { setIdeaBusy(false) }
  }
  const onRun = async force => {
    try {
      const out = await rest('/run', { method: 'POST', body: { force } })
      setRunNotice(out.status === 'in_progress' ? 'A run is already in progress.' : 'Building the digest…')
    } catch (e) { setRunNotice(errText(e)) }
    refresh()
  }

  if (view === 'feeds') {
    return jsx(ScrollArea, {
      children: jsx(FeedsView, {
        feeds: feeds.data?.feeds || [], problems: feeds.data?.problems || [], error: feedsError, draft,
        onDraft: setDraft, onBack: () => setView('digest'),
        onAdd: async d => {
          setFeedsError('')
          try { await rest('/feeds', { method: 'POST', body: { action: 'add', url: d.url || '', theme: d.theme || undefined } }); setDraft({}); refresh() } catch (e) { setFeedsError(errText(e)) }
        },
        onEdit: async (action, url) => {
          setFeedsError('')
          try { await rest('/feeds', { method: 'POST', body: { action, url } }); refresh() } catch (e) { setFeedsError(errText(e)) }
        }
      })
    })
  }
  if (list.isError) return jsx(ErrorState, { title: 'Daily reading is unavailable', description: errText(list.error) })
  if (list.isLoading || (day && digest.isLoading)) return jsx(GlyphSpinner, {})
  const data = digest.data || null
  const run = { running: !!list.data?.run?.running, notice: runNotice || (list.data?.run?.last?.message ? '' : '') }
  return jsx(ScrollArea, {
    children: jsxs('div', {
      children: [
        jsx(DigestView, {
          digest: data, dates: list.data?.dates || [], selected: day, run, itemProps,
          audioSlot: data && !data.audio?.failed ? jsx(AudioPlayer, { day, count: data.audio?.count || 0 }) : null,
          onSelect: setSelected, onRun, onShowFeeds: () => setView('feeds')
        }),
        jsx(IdeaDialog, {
          preview, busy: ideaBusy, result: ideaResult, error: ideaError, onConfirm,
          onCancel: () => { setPreview(null); setIdeaResult(null); setIdeaError('') }
        })
      ]
    })
  })
}

const STYLE = `
.${ID}-page{display:flex;flex-direction:column;gap:12px;padding:16px;max-width:860px}
.${ID}-toolbar,.${ID}-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.${ID}-item{border-top:1px solid var(--border);padding:10px 0;display:flex;flex-direction:column;gap:6px}
.${ID}-read{opacity:.6}
.${ID}-item-head{display:flex;gap:6px;align-items:baseline;font-weight:600}
.${ID}-muted,.${ID}-hint{color:var(--muted-foreground);font-size:12px}
.${ID}-error{color:var(--destructive,#c33);font-size:12px}
.${ID}-warning{color:var(--warning,#b80);font-size:12px}
.${ID}-intro{font-size:15px;line-height:1.5}
.${ID}-dialog{position:fixed;right:24px;bottom:24px;max-width:460px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:6px;z-index:50}
.${ID}-feed{display:flex;gap:8px;align-items:center}
`

function ensureStyles () {
  if (typeof document === 'undefined' || document.getElementById(`${ID}-style`)) return
  const el = document.createElement('style')
  el.id = `${ID}-style`
  el.textContent = STYLE
  document.head.appendChild(el)
}

export default {
  id: ID,
  name: 'Daily reading',
  description: 'Your daily reading digest: summary, audio and items, with read, fragment and article-idea actions.',
  register (ctx) {
    ensureStyles()
    setRuntime({ restFn: ctx.rest, openExternal: ctx.os?.openExternal ? url => ctx.os.openExternal(url) : null })
    return ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PAGE_PATH }, render: () => jsx(DailyReadingPage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 61, data: { codicon: 'book', label: 'Daily reading', path: PAGE_PATH } },
      {
        id: 'open', area: PALETTE_AREA,
        data: { id: `${ID}.open`, label: 'Daily reading: Open', keywords: ['reading', 'digest', 'rss'], run: () => host.navigate(PAGE_PATH) }
      }
    ])
  }
}
