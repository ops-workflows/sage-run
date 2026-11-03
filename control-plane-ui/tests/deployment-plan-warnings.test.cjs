const assert = require('node:assert/strict');
const { test } = require('node:test');
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

function renderPlan(drift) {
  const status = {
    source_mode: 'remote',
    source_url: 'https://example.invalid/workflows',
    platform_version: '1.0.6',
    deployment_enabled: true,
    bundle_errors: {},
  };
  const plan = {
    ref: 'main',
    current_commit: '111111111111',
    target_commit: '222222222222',
    current_version: '1.0.6',
    target_version: '1.0.6',
    version_changed: false,
    resources: { create: [], roll: [], update: [], delete: [] },
    workflows: { create: [], update: [], delete: [] },
    reloads: [],
    migrations: [],
    drift,
  };
  const states = [[], false, null, status, [], null, plan, false, 'main', false, null];
  const originalState = React.useState;
  const originalEffect = React.useEffect;
  const pagePath = require.resolve('../src/app/workflows/page.tsx');
  try {
    React.useState = () => [states.shift(), () => {}];
    React.useEffect = () => {};
    delete require.cache[pagePath];
    const Page = require(pagePath).default;
    return renderToStaticMarkup(React.createElement(Page));
  } finally {
    React.useState = originalState;
    React.useEffect = originalEffect;
    delete require.cache[pagePath];
  }
}

test('deployment preview displays approximate plan notes as an informational status', () => {
  const html = renderPlan(['The preview is approximate because live data was unavailable.']);
  assert.match(html, /role="status"/);
  assert.doesNotMatch(html, /--color-error/);
  assert.match(html, /--color-info/);
  assert.match(html, /Note:/);
  assert.match(html, /The preview is approximate because live data was unavailable\./);
  assert.match(html, /Confirm deploy/);
});

test('deployment preview without notes does not show an informational banner', () => {
  const html = renderPlan([]);
  assert.doesNotMatch(html, /Note:/);
  assert.match(html, /Confirm deploy/);
});
