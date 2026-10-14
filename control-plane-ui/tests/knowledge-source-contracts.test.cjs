const assert = require('node:assert/strict');
const { afterEach, test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const typescript = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const sourceRoot = path.resolve(__dirname, '../src');
const originalResolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...options) {
  return originalResolve.call(this, request.startsWith('@/') ? path.join(sourceRoot, request.slice(2)) : request, parent, ...options);
};
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const result = typescript.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: typescript.ModuleKind.CommonJS, jsx: typescript.JsxEmit.ReactJSX, target: typescript.ScriptTarget.ES2022 },
      fileName: filename,
    });
    module._compile(result.outputText, filename);
  };
}

const { knowledgeSourcePayload, apiFetch } = require('../src/lib/api.ts');
const { EMPTY_KNOWLEDGE_SOURCE_FORM, sourcePayload, sourceForm, KnowledgeSourceForm } = require('../src/components/knowledge-source-form.tsx');
const { MOCK_KNOWLEDGE_SOURCES, MOCK_CONFLUENCE_CONNECTIONS, MOCK_GITHUB_CONNECTIONS } = require('../src/mock-data/knowledge-sources.ts');
const { MOCK_BACKGROUND_JOBS } = require('../src/mock-data/background-jobs.ts');
const { handleMockApiRequest } = require('../src/mock-data/index.ts');
const { TaskInitiator } = require('../src/components/task-initiator.tsx');
const { MOCK_KNOWLEDGE_SOURCE_VERSIONS } = require('../src/mock-data/knowledge-sources.ts');

function renderSourceDetail(source, versions, runs) {
  const originalLoad = Module._load;
  const originalState = React.useState;
  const originalEffect = React.useEffect;
  const states = [source, sourceForm(source), versions, runs, MOCK_GITHUB_CONNECTIONS, MOCK_CONFLUENCE_CONNECTIONS, null, false];
  try {
    Module._load = function (request, ...args) {
      return request === 'next/navigation' ? { useParams: () => ({ sourceId: source.id }) } : originalLoad.call(this, request, ...args);
    };
    React.useState = () => [states.shift(), () => {}];
    React.useEffect = () => {};
    const DetailPage = require('../src/app/knowledge-sources/[sourceId]/page.tsx').default;
    return renderToStaticMarkup(React.createElement(DetailPage));
  } finally {
    Module._load = originalLoad;
    React.useState = originalState;
    React.useEffect = originalEffect;
  }
}

test('detail page renders each linked version once in one compact history', () => {
  for (const source of MOCK_KNOWLEDGE_SOURCES) {
    const version = structuredClone(MOCK_KNOWLEDGE_SOURCE_VERSIONS[source.id][0]);
    version.stats.chunk_count = 330;
    version.stats.scrub_signature = 'internal-scrub-signature';
    const html = renderSourceDetail(source, [version], [{
      id: 'sync', trigger: 'manual', started_at: version.created_at, status: 'succeeded', duration_sec: 6,
      knowledge_source_version_id: version.id, error: null, warnings: [],
    }]);
    assert.equal((html.match(/Sync history/g) || []).length, 1);
    assert.doesNotMatch(html, /Current version|Version history|Config:|internal-scrub-signature/);
    assert.ok(!html.includes(version.index_config_hash));
    assert.ok(!html.includes(version.source_revision));
    assert.equal((html.match(source.index_kind === 'code_graph' ? /Graphify/g : /Hybrid index/g) || []).length, 1);
    assert.match(html, /Current index:/);
    assert.match(html, /Current<\/span>/);
    if (source.source_kind === 'confluence') {
      assert.match(html, /40 pages · 330 chunks · 18 embedded · 312 reused/);
    } else {
      assert.ok(html.includes(source.source_config.repository_url));
      assert.match(html, /files · .*nodes · .*edges/);
    }
  }
});

test('merged history retains unlinked versions, failures and active syncs in date order', () => {
  const source = MOCK_KNOWLEDGE_SOURCES.find((item) => item.source_kind === 'confluence');
  const version = structuredClone(MOCK_KNOWLEDGE_SOURCE_VERSIONS[source.id][0]);
  const olderVersion = { ...version, id: 'older', source_revision: 'older-snapshot', status: 'failed',
    created_at: '2026-10-01T08:00:00Z', error: 'Historical failure', warnings: ['Historical warning'] };
  const html = renderSourceDetail(source, [olderVersion, version], [
    { id: 'failed', trigger: 'scheduled', started_at: '2026-10-03T08:00:00Z', status: 'failed', duration_sec: 3,
      knowledge_source_version_id: null, error: 'Provider unavailable', warnings: ['Retry later'] },
    { id: 'active', trigger: 'manual', started_at: '2026-10-04T08:00:00Z', status: 'queued', duration_sec: null,
      knowledge_source_version_id: null, error: null, warnings: [] },
    { id: 'success', trigger: 'manual', started_at: version.created_at, status: 'succeeded', duration_sec: 6,
      knowledge_source_version_id: version.id, error: null, warnings: ['Shared warning'] },
  ]);
  assert.equal((html.match(/Hybrid index/g) || []).length, 2);
  assert.match(html, /Historical failure/);
  assert.match(html, /Historical warning/);
  assert.match(html, /Provider unavailable/);
  assert.match(html, /Retry later/);
  assert.match(html, /disabled=""[^>]*>.*?Sync active/);
  assert.ok(html.indexOf('queued') < html.indexOf('Provider unavailable'));
  assert.ok(html.indexOf('Provider unavailable') < html.indexOf('Hybrid index'));
  assert.ok(html.indexOf('Hybrid index') < html.indexOf('older-snapsh'));
});

const initialSources = structuredClone(MOCK_KNOWLEDGE_SOURCES);
const initialJobs = structuredClone(MOCK_BACKGROUND_JOBS);
const originalFetch = global.fetch;
afterEach(() => {
  MOCK_KNOWLEDGE_SOURCES.splice(0, MOCK_KNOWLEDGE_SOURCES.length, ...structuredClone(initialSources));
  MOCK_BACKGROUND_JOBS.splice(0, MOCK_BACKGROUND_JOBS.length, ...structuredClone(initialJobs));
  global.fetch = originalFetch;
});
const request = (method, route, body, params = new URLSearchParams()) => handleMockApiRequest(method, route.split('/'), params, body);

test('toggle payload clones Confluence config and never invents GitHub fields', () => {
  const source = MOCK_KNOWLEDGE_SOURCES.find((item) => item.source_kind === 'confluence');
  const payload = knowledgeSourcePayload(source);
  assert.equal(payload.source_kind, 'confluence');
  assert.equal(payload.index_kind, 'hybrid_vector');
  assert.ok(!('repository' in payload));
  assert.deepEqual(payload.source_config, source.source_config);
  payload.source_config.root_page_ids.push('999');
  assert.ok(!source.source_config.root_page_ids.includes('999'));
});

test('generic task initiator renders only populated escaped identities', () => {
  assert.equal(renderToStaticMarkup(React.createElement(TaskInitiator, { initiator: null })), '');
  const html = renderToStaticMarkup(React.createElement(TaskInitiator, { initiator: '<alice>' }));
  assert.match(html, /Initiated By/);
  assert.match(html, /&lt;alice&gt;/);
  assert.doesNotMatch(html, /<alice>/);
});

test('GitHub payload preserves alias, connection, scopes and custom base paths', () => {
  const source = structuredClone(MOCK_KNOWLEDGE_SOURCES[0]);
  source.source_config.repository_url = 'https://github.example/custom/base/org/repo.git';
  const payload = knowledgeSourcePayload(source);
  assert.equal(payload.repository, 'org/repo');
  assert.equal(payload.canonical_alias, source.canonical_alias);
  assert.deepEqual(payload.include_paths, source.include_paths);
  payload.include_paths.push('new/**');
  assert.ok(!source.include_paths.includes('new/**'));
});

test('form round trips both kinds and preserves nonstandard sync intervals', () => {
  for (const source of MOCK_KNOWLEDGE_SOURCES) {
    const form = sourceForm({ ...source, sync_policy: { interval_sec: 12345 }, enabled: false });
    assert.equal(form.schedule, 'custom');
    const payload = sourcePayload(form);
    assert.deepEqual(payload.sync_policy, { interval_sec: 12345 });
    assert.equal(payload.enabled, false);
    assert.equal(payload.canonical_alias, source.canonical_alias);
    assert.equal(payload.source_kind, source.source_kind);
    if (payload.source_kind === 'confluence') {
      assert.deepEqual(payload.source_config.root_pages, source.source_config.root_page_ids);
      assert.equal(payload.source_config.include_descendants, true);
      assert.equal(payload.source_config.body_format, 'storage');
    }
  }
});

test('forms render source-specific controls without credentials and lock edit identity', () => {
  const render = (form, editing = false) => renderToStaticMarkup(React.createElement(KnowledgeSourceForm, {
    form, editing, setForm: () => {}, onSubmit: () => {}, submitLabel: 'Save',
    connections: MOCK_GITHUB_CONNECTIONS, confluenceConnections: MOCK_CONFLUENCE_CONNECTIONS,
  }));
  const github = render(EMPTY_KNOWLEDGE_SOURCE_FORM);
  const aliasPattern = github.match(/pattern="([^"]*)"/)[1];
  assert.doesNotThrow(() => new RegExp(aliasPattern, 'v'));
  assert.match(github, /Repository \(organization\/repository\)/);
  assert.doesNotMatch(github, /Root page URLs/);
  const wiki = render(sourceForm(MOCK_KNOWLEDGE_SOURCES.find((item) => item.source_kind === 'confluence')), true);
  assert.match(wiki, /Root page URLs or numeric IDs/);
  assert.match(wiki, /Lexical language/);
  assert.match(wiki, /Include subpages/);
  assert.match(wiki, /Body scrub regexes/);
  assert.match(wiki, /readonly=""/);
  assert.match(wiki, /disabled=""/);
  assert.doesNotMatch(wiki, /Repository \(organization\/repository\)|type="password"|API token|Embedding model/);
});

test('exact-page selection and ordered regexes round trip through form and mock API', async () => {
  const form = { ...EMPTY_KNOWLEDGE_SOURCE_FORM, source_kind: 'confluence', canonical_alias: 'exact-pages',
    credential_ref: 'corporate-wiki', root_pages: '123', include_descendants: false,
    scrub_patterns: '  (?i)secret=\\S+\n\n(?s)private.*key' };
  const payload = sourcePayload(form);
  assert.equal(payload.source_config.include_descendants, false);
  assert.deepEqual(payload.source_config.scrub_patterns, ['  (?i)secret=\\S+', '(?s)private.*key']);
  const created = await request('POST', 'platform/knowledge-sources', payload);
  assert.equal(created.status, 201);
  const edited = sourceForm(created.data);
  assert.equal(edited.include_descendants, false);
  assert.equal(edited.scrub_patterns, payload.source_config.scrub_patterns.join('\n'));
  const cloned = knowledgeSourcePayload(created.data);
  cloned.source_config.scrub_patterns.push('extra');
  assert.equal(created.data.source_config.scrub_patterns.length, 2);
});

test('mock connection and version routes return complete redacted contracts', async () => {
  const connections = await request('GET', 'platform/knowledge-sources/confluence-connections');
  assert.equal(connections.status, 200);
  assert.deepEqual(Object.keys(connections.data[0]).sort(), ['base_url', 'name']);
  for (const source of MOCK_KNOWLEDGE_SOURCES) {
    assert.equal(typeof source.display_name, 'string');
    assert.ok('serving_suspended_at' in source);
    const result = await request('GET', `platform/knowledge-sources/${source.id}/versions`);
    for (const version of result.data) {
      assert.ok(version.source_revision);
      assert.ok(version.index_config_hash);
      assert.ok(version.stats);
      if (version.index_kind === 'hybrid_vector') assert.equal(version.commit_sha, null);
    }
  }
});

test('mock Confluence create, disable, sync, active protection and suspension work', async () => {
  const payload = sourcePayload({ ...EMPTY_KNOWLEDGE_SOURCE_FORM, source_kind: 'confluence', canonical_alias: 'new-runbooks', credential_ref: 'corporate-wiki', root_pages: '123\nhttps://company.atlassian.net/wiki/pages/viewpage.action?pageId=456' });
  const created = await request('POST', 'platform/knowledge-sources', payload);
  assert.equal(created.status, 201);
  assert.deepEqual(created.data.source_config.root_page_ids, ['123', '456']);
  const route = `platform/knowledge-sources/${created.data.id}`;
  let updated = await request('PUT', route, { ...knowledgeSourcePayload(created.data), enabled: false });
  assert.equal(updated.status, 200);
  assert.equal((await request('POST', `${route}/sync`)).status, 409);
  updated = await request('PUT', route, { ...knowledgeSourcePayload(updated.data), enabled: true });
  const changed = { ...knowledgeSourcePayload(updated.data), source_config: { ...updated.data.source_config, root_page_ids: ['789'] } };
  const suspended = await request('PUT', route, changed);
  assert.equal(suspended.status, 200);
  assert.ok(suspended.data.serving_suspended_at);
  const sync = await request('POST', `${route}/sync`);
  assert.equal(sync.status, 202);
  assert.equal(sync.data.knowledge_source_id, created.data.id);
  assert.equal((await request('POST', `${route}/sync`)).status, 409);
  assert.equal((await request('PUT', route, { ...changed, source_config: { ...changed.source_config, root_page_ids: ['999'] } })).status, 409);
  const jobs = await request('GET', 'platform/background-jobs', undefined, new URLSearchParams({ knowledge_source_id: created.data.id }));
  assert.equal(jobs.data.items[0].id, sync.data.id);
});

test('mock rejects unknown fields, foreign roots and immutable identity edits', async () => {
  const source = MOCK_KNOWLEDGE_SOURCES.find((item) => item.source_kind === 'confluence');
  const route = `platform/knowledge-sources/${source.id}`;
  assert.equal((await request('PUT', route, { ...knowledgeSourcePayload(source), canonical_alias: 'renamed' })).status, 422);
  const payload = sourcePayload({ ...EMPTY_KNOWLEDGE_SOURCE_FORM, source_kind: 'confluence', canonical_alias: 'new-runbooks', credential_ref: 'corporate-wiki', root_pages: 'https://evil.example/wiki/spaces/OPS/pages/123' });
  assert.equal((await request('POST', 'platform/knowledge-sources', payload)).status, 422);
  assert.equal((await request('POST', 'platform/knowledge-sources', { ...payload, source_config: { root_page_ids: ['123'], token: 'secret' } })).status, 422);
  assert.equal((await request('POST', 'platform/knowledge-sources', { ...payload, index_kind: 'unknown' })).status, 422);
});

test('API errors display actionable messages and Pydantic field locations', async () => {
  global.fetch = async () => new Response(JSON.stringify({ detail: 'Wait for the active sync to finish' }), { status: 409 });
  await assert.rejects(apiFetch('/api/platform/knowledge-sources'), /Wait for the active sync/);
  global.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'confluence', 'source_config', 'root_pages'], msg: 'List required' }] }), { status: 422 });
  await assert.rejects(apiFetch('/api/platform/knowledge-sources'), /confluence.source_config.root_pages: List required/);
});