// Runs the generated workflows with fake agents: tests the order, the fix loop and the merge queue
// without starting a real agent.   node tools/delivery/test_engine.mjs
import { readFileSync, readdirSync } from 'node:fs'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const dir = process.argv[2] ?? fileURLToPath(new URL('../../.claude/workflows', import.meta.url))
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

function load(name) {
  const text = readFileSync(`${dir}/${name}.js`, 'utf8')
  assert.ok(text.startsWith('export const meta = {'), 'file must begin with the meta literal')
  const body = text.replace('export const meta', 'const meta')
  return new AsyncFunction('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', 'workflow', body)
}

const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
const tick = () => new Promise(resolve => setTimeout(resolve, 1))

async function run(name, args, script) {
  const calls = []
  const logs = []
  let merging = 0
  let maxMerging = 0
  const agent = async (prompt, opts) => {
    assert.ok(opts.schema && opts.schema.type === 'object', `${opts.label}: schema`)
    assert.ok(opts.model && opts.effort && opts.phase, `${opts.label}: model, effort, phase`)
    assert.ok(!prompt.includes('undefined') && !prompt.includes('[object'), `${opts.label}: prompt has a hole`)
    calls.push({ label: opts.label, model: opts.model, effort: opts.effort, phase: opts.phase, prompt })
    if (opts.phase === 'Merge') maxMerging = Math.max(maxMerging, ++merging)
    await tick()
    const out = await script(opts.label, prompt, calls)
    if (opts.phase === 'Merge') merging--
    return out
  }
  const result = await load(name)(args, agent, parallel, null, () => {}, m => logs.push(m), { total: null }, null)
  return { result, calls, logs, maxMerging }
}

const issues = (numbers, closed = []) => numbers.map(n => ({ n, state: closed.includes(n) ? 'CLOSED' : 'OPEN', pr: 0, prState: 'NONE' }))
const ok = {
  implement: n => ({ status: 'pr_ready', pr: 100 + n, summary: 'done' }),
  review: { verdict: 'approve', summary: 'fine', majors: [], minors: [{ title: 'rename x', detail: 'small', file: 'a.py' }] },
  verify: { verdict: 'pass', summary: 'all green', checks: [{ command: 'make check', passed: true }], acceptance: [{ item: 'runs', verdict: 'passed', evidence: 'saw it' }] },
  fix: { status: 'fixed', changes: ['x'] },
  merge: { status: 'merged', commit: 'abc', followUps: [900] },
  main: { ok: true, checks: ['make check'], problems: [] },
}
const number = label => Number(label.match(/(?:PBI|UI)-(\d+)/)[1])
function happy(prepare, overrides = {}) {
  return (label, prompt, calls) => {
    if (label in overrides) return overrides[label]
    if (label === 'prepare') return prepare
    if (label === 'validate main') return ok.main
    if (label.startsWith('implement')) return ok.implement(number(label))
    if (label.startsWith('review')) return ok.review
    if (label.startsWith('test and validate')) return ok.verify
    if (label.startsWith('fix')) return ok.fix
    if (label.startsWith('merge')) return ok.merge
    throw new Error(`no script for ${label}`)
  }
}
const order = calls => calls.map(c => c.label)
const before = (calls, a, b) => {
  const labels = order(calls)
  assert.ok(labels.indexOf(a) >= 0 && labels.indexOf(b) >= 0, `${a} and ${b} both ran`)
  assert.ok(labels.indexOf(a) < labels.indexOf(b), `${a} before ${b}`)
}

// 1. Dry run starts no agent.
{
  const { result, calls } = await run('foundation-6-auth', { dryRun: true }, () => assert.fail('no agent in a dry run'))
  assert.equal(calls.length, 0)
  assert.deepEqual(result.mustBeMergedFirst, ['#4', '#10', '#11', '#12', '#13', '#15'])
  assert.deepEqual(result.items.map(i => i.waitsFor), [[], ['#16'], ['#17'], ['#16']])
  assert.equal(result.items[0].review, 'opus (high)')
  console.log('ok  dry run')
}

// 2. Happy path of a chain: order, models, one merge at a time, main validated.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([1, 2, 3, 4]) }
  const { result, calls, maxMerging } = await run('foundation-1-bootstrap', undefined, happy(prepare))
  assert.equal(result.status, 'done')
  assert.deepEqual(result.results.map(r => r.status), ['merged', 'merged', 'merged', 'merged'])
  before(calls, 'merge PBI-001', 'implement PBI-002')
  before(calls, 'merge PBI-003', 'implement PBI-004')
  assert.equal(order(calls).at(-1), 'validate main')
  assert.equal(maxMerging, 1)
  assert.equal(calls.find(c => c.label === 'prepare').model, 'haiku')
  assert.equal(calls.find(c => c.label === 'implement PBI-003').effort, 'low')
  assert.ok(calls.find(c => c.label === 'implement PBI-002').prompt.includes('/repo/.worktrees/pbi-002'))
  assert.ok(calls.find(c => c.label === 'merge PBI-002').prompt.includes('rename x (a.py)'))
  assert.equal(calls.length, 1 + 4 * 4 + 1)
  console.log('ok  chain, happy path:', calls.length, 'agents')
}

// 3. Parallel branches: 6 and 7 both wait for 5, and run side by side; merges still one at a time.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([5, 6, 7, 4], [4]) }
  const { result, calls, maxMerging } = await run('foundation-2-quality', {}, happy(prepare))
  assert.equal(result.status, 'done')
  before(calls, 'merge PBI-005', 'implement PBI-006')
  before(calls, 'merge PBI-005', 'implement PBI-007')
  before(calls, 'implement PBI-007', 'merge PBI-006')
  assert.equal(maxMerging, 1)
  console.log('ok  parallel branches')
}

// 4. A dependency outside the run is still open: nothing starts.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([5, 6, 7, 4]) }
  const { result, calls } = await run('foundation-2-quality', {}, happy(prepare))
  assert.equal(result.status, 'not_started')
  assert.deepEqual(result.problems, ['#4 has to be merged before this workflow starts'])
  assert.equal(calls.length, 1)
  console.log('ok  open dependency stops the run')
}

// 5. Review blocks once: fix by the implementing model, second look, then merge.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([13, 14, 15, 7], [7]) }
  const blocked = { verdict: 'changes_required', summary: 'unsafe', majors: [{ title: 'alg none accepted', detail: 'refuse it', file: 'tokens.py' }], minors: [] }
  const { result, calls } = await run('foundation-5-platform', {}, happy(prepare, { 'review PBI-015': blocked }))
  assert.equal(result.status, 'done')
  const fix = calls.find(c => c.label === 'fix PBI-015 (1)')
  assert.equal(fix.model, 'sonnet')
  assert.ok(fix.prompt.includes('alg none accepted (tokens.py)'))
  const second = calls.find(c => c.label === 'review PBI-015 (2)')
  assert.equal(second.model, 'opus')
  assert.ok(second.prompt.includes('alg none accepted'))
  assert.equal(result.results.find(r => r.n === 15).fixRounds, 1)
  console.log('ok  one fix round')
}

// 6. Validation keeps failing: second fix goes to the stronger model, then blocked; the dependent is skipped, the sibling still merges.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([13, 14, 15, 7], [7]) }
  const failing = { verdict: 'fail', summary: 'header missing', checks: [{ command: 'make check', passed: false, output: 'E   assert' }], acceptance: [{ item: 'echo id', verdict: 'failed', evidence: 'no header' }] }
  const overrides = { 'test and validate PBI-013': failing, 'test and validate PBI-013 (2)': failing, 'test and validate PBI-013 (3)': failing }
  const { result, calls } = await run('foundation-5-platform', {}, happy(prepare, overrides))
  assert.equal(result.status, 'needs_attention')
  const by = Object.fromEntries(result.results.map(r => [r.n, r]))
  assert.equal(by[13].status, 'blocked')
  assert.equal(by[13].stage, 'checks')
  assert.equal(by[14].status, 'skipped')
  assert.equal(by[15].status, 'merged')
  assert.equal(calls.find(c => c.label === 'fix PBI-013 (2)').model, 'opus')
  assert.ok(!order(calls).includes('implement PBI-014'))
  assert.ok(!order(calls).includes('merge PBI-013'))
  assert.equal(order(calls).at(-1), 'validate main')
  console.log('ok  blocked after two fix rounds, dependent skipped')
}

// 7. Rerun: a closed issue is skipped, an open pull request is picked up without a new implement.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: [{ n: 8, state: 'CLOSED', pr: 30, prState: 'MERGED' }, { n: 9, state: 'OPEN', pr: 31, prState: 'OPEN' }, { n: 4, state: 'CLOSED', pr: 0, prState: 'NONE' }] }
  const { result, calls } = await run('foundation-3-enablement', {}, happy(prepare))
  assert.equal(result.status, 'done')
  assert.ok(!order(calls).some(l => l.startsWith('implement')))
  assert.ok(calls.find(c => c.label === 'merge PBI-009').prompt.includes('pull request #31'))
  console.log('ok  rerun picks up where it stopped')
}

// 8. merge: false stops at ready; only: narrows the run; an agent that dies blocks its PBI only.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([10, 11, 12, 7], [7, 10]) }
  const { result, calls } = await run('foundation-4-core', { merge: false, only: [11, 12] }, happy(prepare, { 'implement PBI-012': null }))
  assert.equal(result.status, 'needs_attention')
  const by = Object.fromEntries(result.results.map(r => [r.n, r]))
  assert.equal(by[11].status, 'ready')
  assert.equal(by[12].status, 'blocked')
  assert.ok(!order(calls).some(l => l.startsWith('merge') || l === 'validate main'))
  console.log('ok  merge: false, only, a dead agent')
}

// 9. Prepare reports a dirty checkout: nothing starts.
{
  const prepare = { repoDir: '/repo', ready: false, problems: ['the checkout has uncommitted changes'], issues: issues([1, 2, 3, 4]) }
  const { result, calls } = await run('foundation-1-bootstrap', {}, happy(prepare))
  assert.equal(result.status, 'not_started')
  assert.equal(calls.length, 1)
  console.log('ok  not ready stops the run')
}

// 10. A UI workflow: its own repository, branch names, checks and labels; the backend it is tried against.
{
  const prepare = { repoDir: '/ui', ready: true, problems: [], issues: issues([39, 40, 38], [38]) }
  const { result, calls } = await run('studio-ui-2-backend', { repoDir: '/ui', apiDir: '/api' }, happy(prepare))
  assert.equal(result.status, 'done')
  const prep = calls.find(c => c.label === 'prepare').prompt
  assert.ok(prep.includes('hardik-id/knowledge-extractor.') && prep.includes('branch studio/039-studio-http'))
  assert.ok(prep.includes('http://localhost:8000/api/v1/health'))
  const build = calls.find(c => c.label === 'implement UI-039')
  assert.equal(build.model, 'opus')
  assert.ok(build.prompt.includes('npm ci') && build.prompt.includes('/ui/.worktrees/pbi-039'))
  assert.ok(build.prompt.includes("--title 'Studio over HTTP against the Django API'"))
  assert.ok(build.prompt.includes('docker compose -f /api/compose.yaml exec -T api python manage.py mint_dev_token'))
  assert.ok(!build.prompt.includes('uv sync') && !build.prompt.includes('make check'))
  assert.ok(calls.find(c => c.label === 'merge UI-039').prompt.includes("--label 'source: code-review'"))
  before(calls, 'merge UI-039', 'implement UI-040')
  console.log('ok  UI workflow')
}

// 11. The hard tier: a second fix round goes to the strongest model. UI work without a backend says so.
{
  const prepare = { repoDir: '/repo', ready: true, problems: [], issues: issues([146, 147, 137, 144, 145], [137, 144, 145]) }
  const failing = { verdict: 'fail', summary: 'no events', checks: [], acceptance: [{ item: 'socket shows deltas', verdict: 'failed', evidence: 'nothing arrived' }] }
  const overrides = { 'test and validate PBI-146': failing, 'test and validate PBI-146 (2)': failing }
  const { result, calls } = await run('studio-5-assistant', {}, happy(prepare, overrides))
  assert.equal(result.status, 'done')
  assert.equal(calls.find(c => c.label === 'implement PBI-146').model, 'opus')
  assert.equal(calls.find(c => c.label === 'fix PBI-146 (1)').model, 'opus')
  assert.equal(calls.find(c => c.label === 'fix PBI-146 (2)').model, 'fable')
  assert.ok(calls.find(c => c.label === 'implement PBI-146').prompt.includes('.claude/skills/'))
  const ui = await run('studio-ui-1-apps', { dryRun: true }, () => assert.fail('no agent'))
  assert.equal(ui.result.kind, 'ui')
  const apps = await run('studio-ui-1-apps', { repoDir: '/ui' }, happy({ repoDir: '/ui', ready: true, problems: [], issues: issues([38]) }))
  assert.ok(apps.calls.find(c => c.label === 'prepare').prompt.includes('does not need the backend'))
  console.log('ok  hard tier, UI work without a backend')
}

// 12. The end-to-end suite is the merge gate.
{
  const e2e = 'npm run test:e2e'
  // UI work that needs the API: each PBI's validation runs it on its own E2E_PORT, and so does the final check.
  const prepare = { repoDir: '/ui', ready: true, problems: [], issues: issues([39, 40, 38], [38]) }
  const ui = await run('studio-ui-2-backend', { repoDir: '/ui', apiDir: '/api' }, happy(prepare))
  assert.equal(ui.result.status, 'done')
  for (const n of [39, 40]) {
    const text = ui.calls.find(c => c.label === `test and validate UI-0${n}`).prompt
    assert.ok(text.includes(`E2E_PORT=${7100 + n} ${e2e}`), `UI-0${n} validation runs e2e on its own port`)
    assert.ok(text.includes("don't start, stop, rebuild or reset it"), 'the shared stack is left alone')
    assert.ok(text.includes('never 3000 or 3100'))
  }
  const ports = ui.calls.filter(c => c.label.startsWith('test and validate')).map(c => c.prompt.match(/E2E_PORT=(\d+)/)[1])
  assert.equal(new Set(ports).size, ports.length, 'one E2E_PORT per agent')
  const uiMain = ui.calls.find(c => c.label === 'validate main').prompt
  assert.ok(uiMain.includes(`E2E_PORT=${6000 + 22} ${e2e}`) && uiMain.includes('failing test'))
  assert.equal(ui.calls.filter(c => c.prompt.includes(e2e) && !c.label.startsWith('test and validate') && c.label !== 'validate main').length, 0, 'only the validators and the final check run it')
  assert.ok(ui.calls.find(c => c.label === 'implement UI-039').prompt.includes('never use it either'))

  // UI work that needs no backend: no e2e anywhere.
  const apps = await run('studio-ui-1-apps', { repoDir: '/ui' }, happy({ repoDir: '/ui', ready: true, problems: [], issues: issues([38]) }))
  assert.ok(apps.calls.filter(c => c.label === 'validate main' || c.label.startsWith('test and validate')).every(c => !c.prompt.includes(e2e)))

  // API work: the per-PBI check does not run it; the final check rebuilds the stack from main and runs make e2e.
  const api = await run('studio-7-stack', { repoDir: '/repo', uiDir: '/ui' }, happy({ repoDir: '/repo', ready: true, problems: [], issues: issues([154, 155, 156, 139, 146, 152, 153], [139, 146, 152, 153]) }))
  assert.equal(api.result.status, 'done')
  assert.ok(api.calls.filter(c => c.label.startsWith('test and validate')).every(c => !c.prompt.includes('end-to-end suite')))
  const apiMain = api.calls.find(c => c.label === 'validate main').prompt
  assert.ok(apiMain.includes('cd /repo && make up'))
  assert.ok(apiMain.includes('E2E_PORT=6017 make e2e UI_DIR=/ui'))
  assert.ok(apiMain.includes("failing test's name in `problems`"))
  assert.ok(apiMain.indexOf('End-to-end suite') < apiMain.indexOf('Clean up'))
  assert.ok(api.calls.find(c => c.label === 'implement PBI-154').prompt.includes('Never use 3000'))

  // An item that changes only docs or the delivery tooling skips it: by its title or its label.
  const docs = { repoDir: '/ui', ready: true, problems: [], issues: [{ n: 39, state: 'OPEN', pr: 0, prState: 'NONE', labels: ['documentation'] }, { n: 40, state: 'OPEN', pr: 0, prState: 'NONE', labels: [] }, { n: 38, state: 'CLOSED', pr: 0, prState: 'NONE' }] }
  const skip = await run('studio-ui-2-backend', { repoDir: '/ui', apiDir: '/api', only: [39] }, happy(docs))
  assert.ok(!skip.calls.find(c => c.label === 'test and validate UI-039').prompt.includes(e2e))
  assert.ok(skip.calls.find(c => c.label === 'test and validate UI-039').prompt.includes('not run for it'))
  assert.ok(!skip.calls.find(c => c.label === 'validate main').prompt.includes(e2e), 'nothing but docs merged: no suite on main')
  const tooling = await run('e2e-5-engine', { repoDir: '/repo' }, happy({ repoDir: '/repo', ready: true, problems: [], issues: issues([363, 356], [356]) }))
  assert.ok(!tooling.calls.find(c => c.label === 'validate main').prompt.includes('End-to-end suite'), 'a delivery tooling PBI skips the suite on main')
  console.log('ok  end-to-end merge gate')
}

// Every file parses and dry-runs.
for (const file of readdirSync(dir).filter(f => f.endsWith('.js')).sort()) {
  const name = file.slice(0, -3)
  const { result } = await run(name, { dryRun: true }, () => assert.fail('no agent'))
  console.log(`    ${name}: ${result.items.map(i => i.pbi + (i.waitsFor.length ? `<-${i.waitsFor.join('+')}` : '')).join('  ')}   first: ${result.mustBeMergedFirst.join(' ') || '-'}`)
}
console.log('all scenarios passed')
