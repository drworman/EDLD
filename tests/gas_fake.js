// tests/gas_fake.js — enough of Apps Script to run EDLD's sheet code under Node.
//
// Values, formulas, properties, fetches, locks and dialogs are real enough to
// assert on. Formatting is not: any method the sheet code calls purely for
// appearance (colours, fonts, borders, widths, validation, conditional
// formats) is accepted and does nothing, via a Proxy, so a styling call added
// later does not need this file changed. A *read* this file does not implement
// — any get…() — throws instead: answering it with the proxy made one test
// pass against code that never saw the value it asked for. A value with a leading apostrophe is
// stored as the text after it, which is what Sheets does.
//
// Used by tests/test_sheets_loader.py. Reads a JSON scenario on stdin and
// prints what happened as JSON.
'use strict';
const fs = require('fs');
const crypto = require('crypto');

const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
const log = { alerts: [], prompts: [], toasts: [], menus: [], fetched: [], results: [] };

// Any property not defined is a method that does nothing and returns the object.
function chain(base) {
  const p = new Proxy(base, {
    get(t, k) {
      if (k in t) return t[k];
      if (typeof k === 'symbol' || k === 'then' || k === 'toJSON') return undefined;
      if (/^get[A-Z]/.test(k)) {
        return () => { throw new Error('gas_fake.js does not implement ' + k + '()'); };
      }
      return () => p;
    },
  });
  return p;
}

function colNum(s) { let n = 0; for (const ch of s) n = n * 26 + ch.charCodeAt(0) - 64; return n; }
function parseA1(a1) {
  const m = /^\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$/.exec(a1);
  if (!m) throw new Error('fake cannot parse A1 ' + a1);
  const r1 = +m[2], c1 = colNum(m[1]);
  const r2 = m[4] ? +m[4] : r1, c2 = m[3] ? colNum(m[3]) : c1;
  return [r1, c1, r2 - r1 + 1, c2 - c1 + 1];
}
const stored = (v) => (typeof v === 'string' && v.startsWith("'")) ? v.slice(1) : v;
const revive = (v) => (v && typeof v === 'object' && v.__date) ? new Date(v.__date) : v;

function makeSheet(ss, name, rows) {
  rows = (rows || []).map(r => r.map(revive));
  const at = (r, c) => (rows[r - 1] && rows[r - 1][c - 1] !== undefined) ? rows[r - 1][c - 1] : '';
  const put = (r, c, v) => {
    while (rows.length < r) rows.push([]);
    while (rows[r - 1].length < c) rows[r - 1].push('');
    rows[r - 1][c - 1] = stored(v);
  };
  const sheet = chain({
    _rows: rows, _name: name, _hidden: false,
    getName: () => sheet._name,
    setName: (n) => { sheet._name = n; return sheet; },
    getParent: () => ss,
    hideSheet: () => { sheet._hidden = true; return sheet; },
    getLastRow: () => { let n = rows.length; while (n && !rows[n - 1].some(v => v !== '' && v !== null)) n--; return n; },
    getLastColumn: () => rows.reduce((m, r) => { let n = r.length; while (n && (r[n - 1] === '' || r[n - 1] === null)) n--; return Math.max(m, n); }, 0),
    getMaxRows: () => Math.max(1000, rows.length),
    getMaxColumns: () => 26,
    _frozen: 0,
    setFrozenRows: (n) => { sheet._frozen = n; return sheet; },
    deleteRow: (r) => { rows.splice(r - 1, 1); },
    copyTo: (dest) => dest._add('Copy of ' + sheet._name, JSON.parse(JSON.stringify(rows))),
    getDataRange: () => sheet.getRange(1, 1, Math.max(1, sheet.getLastRow()), Math.max(1, sheet.getLastColumn())),
    getRangeList: () => chain({}),
    getRange: (a, b, c, d) => {
      let r, col, nr, nc;
      if (typeof a === 'string') [r, col, nr, nc] = parseA1(a);
      else [r, col, nr, nc] = [a, b, c || 1, d || 1];
      const range = chain({
        getRow: () => r, getColumn: () => col, getLastRow: () => r + nr - 1,
        getLastColumn: () => col + nc - 1, getNumRows: () => nr, getNumColumns: () => nc,
        getSheet: () => sheet,
        getValues: () => Array.from({ length: nr }, (_, i) => Array.from({ length: nc }, (_, j) => at(r + i, col + j))),
        getDisplayValues: () => range.getValues().map(row => row.map(v => v instanceof Date ? v.toISOString().slice(0, 10) : String(v))),
        getDisplayValue: () => range.getDisplayValues()[0][0],
        getValue: () => at(r, col),
        setValues: (vs) => { vs.forEach((row, i) => row.forEach((v, j) => put(r + i, col + j, v))); return range; },
        setValue: (v) => { put(r, col, v); return range; },
        setFormula: (f) => { put(r, col, f); return range; },
        setFormulas: (fs2) => range.setValues(fs2),
        clearContent: () => { for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) if (rows[r - 1 + i] && rows[r - 1 + i][col - 1 + j] !== undefined) rows[r - 1 + i][col - 1 + j] = ''; return range; },
      });
      return range;
    },
  });
  return sheet;
}

const sheets = [];
const ss = chain({
  _add: (name, rows, index) => {
    if (sheets.some(s => s._name === name)) throw new Error('A sheet with the name "' + name + '" already exists');
    const s = makeSheet(ss, name, rows);
    if (index === undefined) sheets.push(s); else sheets.splice(index, 0, s);
    return s;
  },
  getSheetByName: (n) => sheets.find(s => s._name === n) || null,
  insertSheet: (n, index) => ss._add(n, [], index),
  deleteSheet: (sh) => {
    if (sheets.length < 2) throw new Error('cannot delete the only sheet');
    sheets.splice(sheets.indexOf(sh), 1);
  },
  getSheets: () => sheets.slice(),
  toast: (msg) => { log.toasts.push(String(msg)); },
});
for (const [name, rows] of Object.entries(spec.sheets || {})) ss._add(name, rows);

const uiReplies = (spec.ui || []).slice();
const ui = chain({
  Button: { YES: 'YES', NO: 'NO', OK: 'OK', CANCEL: 'CANCEL' },
  ButtonSet: { YES_NO: 'YES_NO', OK: 'OK', OK_CANCEL: 'OK_CANCEL' },
  alert: (title, msg, buttons) => {
    log.alerts.push(String(msg === undefined ? title : msg));
    return buttons === 'YES_NO' ? (uiReplies.shift() || 'NO') : 'OK';
  },
  prompt: (title, msg) => {
    log.prompts.push(String(msg));
    const reply = uiReplies.shift() || { button: 'CANCEL', text: '' };
    return { getSelectedButton: () => reply.button, getResponseText: () => reply.text };
  },
  createMenu: (name) => {
    const items = [];
    const menu = chain({
      addItem: (label, fn) => { items.push([label, fn]); return menu; },
      addSeparator: () => { items.push(['-', '']); return menu; },
      addToUi: () => { log.menus.push({ name, items }); },
    });
    return menu;
  },
});

function propStore(init) {
  const data = Object.assign({}, init || {});
  return {
    _data: data,
    getProperty: (k) => (k in data ? data[k] : null),
    setProperty: (k, v) => { data[k] = String(v); },
    setProperties: (o, del) => { if (del) for (const k of Object.keys(data)) delete data[k]; for (const [k, v] of Object.entries(o)) data[k] = String(v); },
    getProperties: () => Object.assign({}, data),
    deleteProperty: (k) => { delete data[k]; },
  };
}
const scriptProps = propStore(spec.scriptProps);
const docProps = propStore(spec.docProps);

let locked = false;
Object.assign(globalThis, {
  SpreadsheetApp: chain({
    getActive: () => ss, getActiveSpreadsheet: () => ss, getUi: () => ui,
    BorderStyle: { SOLID: 'SOLID' },
    newDataValidation: () => chain({}), newConditionalFormatRule: () => chain({}),
  }),
  PropertiesService: { getScriptProperties: () => scriptProps, getDocumentProperties: () => docProps },
  LockService: { getDocumentLock: () => ({
    tryLock: () => !locked, waitLock: () => { locked = true; }, releaseLock: () => { locked = false; },
  }) },
  ContentService: { createTextOutput: (t) => ({ setMimeType: () => JSON.parse(t) }), MimeType: { JSON: 'json' } },
  UrlFetchApp: { fetch: (url) => {
    log.fetched.push(url);
    const body = (spec.urls || {})[url];
    return { getResponseCode: () => (body === undefined ? 404 : 200), getContentText: () => body || '' };
  } },
  Utilities: {
    DigestAlgorithm: { SHA_256: 'sha256' }, Charset: { UTF_8: 'utf8' },
    computeDigest: (alg, text) => Array.from(crypto.createHash('sha256').update(text, 'utf8').digest()).map(b => (b > 127 ? b - 256 : b)),
    getUuid: () => crypto.randomUUID(),
    formatDate: (d, tz, fmt) => fmt === 'yyyy-MM-dd' ? d.toISOString().slice(0, 10) : d.toISOString().slice(0, 16).replace('T', ' ').replace(':', ''),
  },
  Session: { getScriptTimeZone: () => 'UTC' },
  Logger: { log: () => {} },
  console: Object.assign(Object.create(console), { error: () => {} }),
});

for (const file of spec.files) (0, eval)(fs.readFileSync(file, 'utf8'));

for (const step of spec.steps) {
  let out = null;
  try {
    if (step.call) out = globalThis[step.call]();
    else if (step.post) out = doPost({ postData: { contents: JSON.stringify(step.post) } });
  } catch (err) { out = { thrown: String(err && err.message || err) }; }
  log.results.push(out === undefined ? null : out);
}

const dump = (v) => v instanceof Date ? { __date: v.toISOString() } : v;
process.stdout.write(JSON.stringify(Object.assign(log, {
  sheets: Object.fromEntries(sheets.map(s => [s._name, { rows: s._rows.map(r => r.map(dump)), hidden: s._hidden, frozen: s._frozen }])),
  order: sheets.map(s => s._name),
  scriptProps: scriptProps._data, docProps: docProps._data,
})));
