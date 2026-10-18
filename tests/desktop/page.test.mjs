// Spec reading-page, rendered without a browser: pure views expanded into a plain tree.
import { test } from 'node:test'
import assert from 'node:assert/strict'

const page = await import('../../desktop/plugin.js')
const { DigestView, IdeaDialog, ItemCard } = page

// Expand function components (pure views and SDK tag stubs) into { type, props } nodes.
function render (node) {
  if (node == null || node === false) return null
  if (Array.isArray(node)) return node.map(render)
  if (typeof node !== 'object') return node
  if (typeof node.type === 'function') return render(node.type(node.props))
  const children = node.props?.children
  return { type: node.type, props: { ...node.props, children: children === undefined ? undefined : render(children) } }
}

function all (tree, pred, out = []) {
  if (Array.isArray(tree)) { tree.forEach(t => all(t, pred, out)); return out }
  if (!tree || typeof tree !== 'object') return out
  if (pred(tree)) out.push(tree)
  all(tree.props?.children, pred, out)
  return out
}
const byRole = (tree, role) => all(tree, n => n.props?.['data-role'] === role)
const byAction = (tree, action) => all(tree, n => n.props?.['data-action'] === action)
const textOf = node => {
  if (node == null) return ''
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (typeof node !== 'object') return String(node)
  return textOf(node.props?.children)
}
// Every string anywhere in the tree must be a text child or a plain attribute, never markup to inject.
const htmlProps = tree => all(tree, n => n.props && 'dangerouslySetInnerHTML' in n.props)

const enabled = { fragment: { enabled: true, hint: '' }, idea: { enabled: true, hint: '' } }
const item = (over = {}) => ({
  number: 1, id: 'a1b2c3d4e5f6', title: 'Retries in Mule', link: 'https://a.com/1', paragraph: 'Why retries matter.',
  excerpt: '', sources: ['https://a.com/feed', 'https://b.com/rss'], themes: ['integration'], read: false,
  fragment_saved: false, idea: null, ...over
})
const digest = (over = {}) => ({
  date: '2026-10-19', intro: 'Good morning.', items: [item(), item({ number: 2, id: 'ffffffffffff', title: 'Second' })],
  message: '', summary_failed: false, audio: { count: 1, failed: false }, actions: enabled, ...over
})

test('Latest digest shown', () => {
  const tree = render(DigestView({ digest: digest(), dates: ['2026-10-19', '2026-10-18'], selected: '2026-10-19', run: {} }))
  assert.equal(textOf(byRole(tree, 'intro')), 'Good morning.')
  const cards = all(tree, n => n.type === 'article')
  assert.equal(cards.length, 2)
  assert.equal(textOf(byRole(cards[0], 'paragraph')), 'Why retries matter.')
  assert.equal(textOf(byRole(cards[0], 'sources')), 'a.com · b.com — integration')
  assert.equal(textOf(byAction(cards[0], 'open')), 'Retries in Mule')
})

test('No digest yet', () => {
  const tree = render(DigestView({ digest: null, dates: [], run: {} }))
  const [empty] = byRole(tree, 'empty')
  assert.equal(empty.props.title, 'No digest yet')
  assert.equal(byAction(tree, 'run').length, 1)
})

test('Markup in feed text', () => {
  const hostile = '<img src=x onerror=alert(1)><script>alert(2)</script>'
  const tree = render(DigestView({ digest: digest({ intro: hostile, items: [item({ title: hostile, paragraph: hostile })] }), run: {} }))
  assert.equal(htmlProps(tree).length, 0)
  assert.equal(textOf(byRole(tree, 'intro')), hostile) // shown as literal text
  assert.equal(all(tree, n => n.type === 'img' || n.type === 'script').length, 0)
})

test('Item without a valid link', () => {
  for (const link of [null, 'javascript:alert(1)', 'file:///etc/hosts']) {
    const tree = render(ItemCard({ item: item({ link }), actions: enabled }))
    assert.equal(byAction(tree, 'open').length, 0)
    assert.equal(textOf(byRole(tree, 'title')), 'Retries in Mule')
  }
  const opened = []
  const tree = render(ItemCard({ item: item(), actions: enabled, onOpen: url => opened.push(url) }))
  byAction(tree, 'open')[0].props.onClick()
  assert.deepEqual(opened, ['https://a.com/1'])
})

test('Actions disabled with a hint', () => {
  const actions = { fragment: { enabled: false, hint: 'Set fragments_dir to save fragments' }, idea: { enabled: false, hint: 'Set ideas.target to file or command' } }
  const tree = render(ItemCard({ item: item(), actions }))
  assert.equal(byAction(tree, 'fragment')[0].props.disabled, true)
  assert.equal(byAction(tree, 'idea')[0].props.disabled, true)
  assert.match(textOf(byRole(tree, 'fragment-hint')), /fragments_dir/)
  assert.match(textOf(byRole(tree, 'idea-hint')), /ideas\.target/)
  assert.equal(byAction(tree, 'read')[0].props.disabled, false)
})

test('Saved fragment and sent idea are shown', () => {
  const tree = render(ItemCard({ item: item({ fragment_saved: true, read: true, idea: { state: 'sent' } }), actions: enabled }))
  assert.equal(textOf(byAction(tree, 'fragment')), 'Saved as fragment')
  assert.equal(byAction(tree, 'fragment')[0].props.disabled, true)
  assert.equal(textOf(byRole(tree, 'idea-badge')), 'Idea sent')
  assert.equal(textOf(byAction(tree, 'read')), 'Mark unread')
})

test('Idea confirm and cancel', () => {
  const preview = { token: 'tok', payload: { title: 'T', url: 'https://a.com/1', summary: '', sources: 'https://a.com/feed' }, target: 'file', target_detail: '/x/ideas.md', warning: 'Already sent on 2026-10-19 07:10; confirming may create a duplicate.' }
  const calls = []
  const tree = render(IdeaDialog({ preview, onConfirm: t => calls.push(['confirm', t]), onCancel: () => calls.push(['cancel']) }))
  assert.equal(textOf(byRole(tree, 'idea-summary')), '(no summary paragraph)')
  assert.match(textOf(byRole(tree, 'idea-warning')), /duplicate/)
  byAction(tree, 'idea-cancel')[0].props.onClick()
  byAction(tree, 'idea-confirm')[0].props.onClick()
  assert.deepEqual(calls, [['cancel'], ['confirm', 'tok']])
  const done = render(IdeaDialog({ preview, result: { state: 'failed', output: 'exit 4: no permission' } }))
  assert.equal(textOf(byRole(done, 'idea-result')), 'Idea failed: exit 4: no permission')
  assert.equal(byAction(done, 'idea-confirm').length, 0)
  assert.equal(IdeaDialog({ preview: null }), null)
})

test('Errors from the backend are readable', () => {
  const e = new Error('409: {"detail":{"code":"stale","message":"This confirmation is no longer valid; ask for a new preview"}}')
  assert.equal(page.errText(e), 'This confirmation is no longer valid; ask for a new preview')
  assert.equal(page.errCode(e), 'stale')
})

test('register adds the page, the sidebar row and a palette command', () => {
  const seen = []
  page.default.register({ rest: async () => ({}), os: {}, registerMany: list => { seen.push(...list); return () => {} } })
  assert.deepEqual(seen.map(c => c.area), ['routes', 'sidebar-nav', 'palette'])
  assert.equal(seen[0].data.path, '/daily-reading')
})
