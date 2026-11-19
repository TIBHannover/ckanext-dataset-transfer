const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function transferSource() {
  return fs.readFileSync(
    path.join(__dirname, '..', 'public', 'transfer.js'),
    'utf8'
  );
}

function loadTransferScript() {
  const source = transferSource();
  const jquery = function () {
    return {ready: function () {}};
  };
  jquery.trim = function (value) { return String(value || '').trim(); };
  jquery.each = function (items, callback) {
    for (let index = 0; index < items.length; index += 1) {
      if (callback(index, items[index]) === false) { break; }
    }
  };
  const context = {
    console,
    document: {},
    setTimeout,
    clearTimeout,
    $: jquery
  };
  vm.createContext(context);
  vm.runInContext(source, context, {filename: 'transfer.js'});
  return context;
}

function mockRegistrySuccess(context, data) {
  context.$.ajax = function () {
    return {
      then: function (resolve) { return Promise.resolve(resolve(data)); }
    };
  };
}

function mockRegistryFailure(context, status, textStatus) {
  context.$.ajax = function () {
    return {
      then: function (_, reject) {
        return Promise.resolve(reject({status}, textStatus || 'error'));
      }
    };
  };
}

test('ORCID validates format, checksum, URL normalization, and X check digits', () => {
  const context = loadTransferScript();
  let result = context.normalize_orcid('0000-0002-1825-0097');
  assert.equal(result.formatValid, true);
  assert.equal(result.checksumValid, true);
  assert.equal(result.canonical, 'https://orcid.org/0000-0002-1825-0097');

  result = context.normalize_orcid('https://orcid.org/0000-0002-1825-0097');
  assert.equal(result.checksumValid, true);
  assert.equal(context.normalize_orcid('0000-0002-1825-0098').checksumValid, false);
  assert.equal(context.normalize_orcid('not-an-orcid').formatValid, false);
  assert.equal(context.normalize_orcid('').formatValid, false);
  assert.equal(context.normalize_orcid('0000-0002-1694-233X').checksumValid, true);
});

test('ROR validates format, check characters, bare IDs, and canonical URLs', () => {
  const context = loadTransferScript();
  let result = context.normalize_ror('04aj4c181');
  assert.equal(result.formatValid, true);
  assert.equal(result.checksumValid, true);
  assert.equal(result.canonical, 'https://ror.org/04aj4c181');

  result = context.normalize_ror('https://ror.org/04aj4c181');
  assert.equal(result.checksumValid, true);
  assert.equal(context.normalize_ror('04aj4c180').checksumValid, false);
  assert.equal(context.normalize_ror('04aj4ci81').formatValid, false);
  assert.equal(context.normalize_ror('').formatValid, false);
});

test('official registry success and organization name responses are parsed', async () => {
  const context = loadTransferScript();
  mockRegistrySuccess(context, {});
  let result = await context.verify_identifier_in_registry('orcid', '0000-0002-1825-0097');
  assert.equal(result.status, 'verified');
  assert.equal(result.name, '');

  mockRegistrySuccess(context, {
    names: [
      {types: ['label'], value: 'LUH'},
      {types: ['ror_display'], value: 'Leibniz University Hannover'}
    ]
  });
  result = await context.verify_identifier_in_registry('ror', '04aj4c181');
  assert.equal(result.status, 'verified');
  assert.equal(result.name, 'Leibniz University Hannover');
});

test('registry errors distinguish not found, timeout, rate limiting, and network failure', async () => {
  const context = loadTransferScript();
  for (const [kind, id] of [['orcid', '0000-0002-1825-0097'], ['ror', '04aj4c181']]) {
    for (const [status, textStatus, expected] of [
      [404, 'error', 'not_found'],
      [0, 'timeout', 'timeout'],
      [429, 'error', 'rate_limited'],
      [503, 'error', 'rate_limited'],
      [0, 'error', 'unavailable']
    ]) {
      mockRegistryFailure(context, status, textStatus);
      const result = await context.verify_identifier_in_registry(kind, id);
      assert.equal(result.status, expected);
    }
  }
});

test('concurrent verification reuses one request and caches stable results', async () => {
  const context = loadTransferScript();
  let requests = 0;
  context.$.ajax = function () {
    requests += 1;
    return {then: function (resolve) { return Promise.resolve(resolve({})); }};
  };
  const first = context.verify_identifier_with_cache('orcid', '0000-0002-1825-0097');
  const second = context.verify_identifier_with_cache('orcid', '0000-0002-1825-0097');
  assert.equal(first, second);
  assert.equal(requests, 1);
  assert.equal((await first).status, 'verified');
});

test('stale verification responses are ignored after an identifier changes', () => {
  const context = loadTransferScript();
  assert.equal(
    context.identifier_verification_is_current(4, 'ror', '04aj4c181', 4, 'ror', '04aj4c181'),
    true
  );
  assert.equal(
    context.identifier_verification_is_current(4, 'ror', '04aj4c181', 5, 'ror', '04aj4c181'),
    false
  );
  assert.equal(
    context.identifier_verification_is_current(4, 'ror', '04aj4c181', 4, 'ror', '03yrm5c26'),
    false
  );
});

test('delegated handlers cover existing and dynamic identifier fields without changing the payload', () => {
  const source = transferSource();
  const delegatedSelector = '.radar-orcid, .radar-affiliation-ror, .radar-publisher-identifier, .radar-rights-holder-identifier';
  assert.ok(source.includes("$(document).on('input', '" + delegatedSelector));
  assert.ok(source.includes("$(document).on('blur', '" + delegatedSelector));
  assert.match(source, /template === 'creator' \|\| template === 'contributor'/);
  assert.match(source, /class="form-control radar-orcid"/);
  assert.match(source, /class="form-control radar-affiliation-ror"/);
  assert.match(source, /class="form-control radar-publisher-identifier"/);
  assert.match(source, /class="form-control radar-rights-holder-identifier"/);
  assert.ok(source.includes("formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));"));
  assert.ok(!source.includes('orcid_verified'));
  assert.ok(!source.includes('ror_verified'));
  assert.ok(!source.includes('verification_status'));
  assert.match(source, /if\(creator\.orcid && !valid_orcid_format/);
  assert.match(source, /if\(creator\.affiliation_ror && !valid_ror_format/);
  assert.match(source, /if\(publisher\.name_identifier_scheme === 'ROR'/);
  assert.match(source, /if\(holder\.name_identifier_scheme === 'ROR'/);
});
