/**
 * EDLD sheet loader — the one file a sheet owner pastes.
 *
 * Paste this as the only file in the sheet's Apps Script project, save,
 * reload the sheet, and run ED Dashboard > Upgrade. That fetches EDLD's sheet
 * code, checks it, stores it in this project's properties and brings the
 * sheet's layout up to date. Every later release is the same menu item. Full
 * instructions: sheets/README.md in the EDLD repo.
 *
 * Where updates come from
 * -----------------------
 * A branch of the EDLD repository: sheets/release.json on that branch, and the
 * bundle it names from beside it. No tag and no GitHub Release is involved, so
 * a sheet can follow dev to test sheet code before any of it is released.
 * Sheets follow main unless their owner picks another branch with ED Dashboard
 * > Update from branch…; merging to main is what releases sheet code.
 *
 * Why a loader
 * ------------
 * An Apps Script project can only rewrite its own files through the Apps
 * Script API, and that API is disabled in the hidden Cloud project every
 * sheet script gets — enabling it means a trip to the Cloud console for every
 * sheet owner. So this file never changes. It keeps the entry points Google
 * calls (doPost, onOpen, the menu) and runs the real code, which lives in
 * script properties and is replaced by Upgrade. The web app deployment points
 * at this file, so an upgrade needs no redeploy and the URL and token
 * squadron members hold never change.
 *
 * What it trusts
 * --------------
 * Code comes only from raw.githubusercontent.com, only from beside the
 * manifest that names it, and only if its SHA-256 matches that manifest. The
 * hash catches a truncated or corrupted download; it does not make the code
 * more trustworthy than the repository it came from, which is the same trust
 * as pasting it by hand. Nothing is installed without the owner confirming
 * the version, and the stored code is re-checked against its hash every time
 * it is loaded.
 *
 * Change only when unavoidable: every change is another paste for every
 * owner. A release that needs a newer loader says so, via min_loader.
 */

var LOADER_VERSION = 1;

/** This repository's raw file host. A fork changes this line and nothing else. */
var EDLD_REPO_RAW = 'https://raw.githubusercontent.com/drworman/EDLD';

/** The branch a sheet follows until its owner picks another. */
var EDLD_DEFAULT_BRANCH = 'main';

var LP_ = {
  CODE: 'EDLD_CODE_',            // EDLD_CODE_0, EDLD_CODE_1, …
  PARTS: 'EDLD_CODE_PARTS',
  SHA: 'EDLD_CODE_SHA256',
  VERSION: 'EDLD_CODE_VERSION',
  FROM: 'EDLD_CODE_FROM',        // the manifest URL the installed code came from
  TOKEN: 'EDLD_TOKEN',           // read by Code.gs
  BRANCH: 'EDLD_BRANCH',         // set from the menu
  RELEASE_URL: 'EDLD_RELEASE_URL' // a full manifest URL; overrides the branch
};

/** Property values are capped at 9 kB; characters, not bytes, are counted here. */
var LOADER_CHUNK_ = 4000;

// ── the stored code ───────────────────────────────────────────────────────────

var edldModule_ = null;

function sha256Hex_(text) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text,
                                      Utilities.Charset.UTF_8);
  return bytes.map(function (b) {
    return ('0' + (b & 0xff).toString(16)).slice(-2);
  }).join('');
}

function compile_(src) {
  var mod = new Function('LOADER', src)({ version: LOADER_VERSION });
  if (!mod || typeof mod.doPost !== 'function' ||
      typeof mod.upgradeSheet !== 'function') {
    throw new Error('the code does not look like an EDLD sheet bundle');
  }
  return mod;
}

/** The installed code, loaded once per execution. Null if none is installed. */
function edld_() {
  if (edldModule_) return edldModule_;
  var props = PropertiesService.getScriptProperties().getProperties();
  var parts = parseInt(props[LP_.PARTS] || '0', 10);
  if (!parts) return null;
  var src = '';
  for (var i = 0; i < parts; i++) src += props[LP_.CODE + i] || '';
  if (sha256Hex_(src) !== props[LP_.SHA]) {
    throw new Error('the stored EDLD code is incomplete or has been altered — ' +
                    'run ED Dashboard > Upgrade to reinstall it');
  }
  edldModule_ = compile_(src);
  return edldModule_;
}

/** As edld_(), but a failure is logged and treated as nothing installed. */
function edldQuiet_() {
  try { return edld_(); } catch (err) { console.error(err); return null; }
}

function storeCode_(src, version, sha, from) {
  var sp = PropertiesService.getScriptProperties();
  var old = parseInt(sp.getProperty(LP_.PARTS) || '0', 10);
  var props = {};
  var parts = Math.max(1, Math.ceil(src.length / LOADER_CHUNK_));
  for (var i = 0; i < parts; i++) {
    props[LP_.CODE + i] = src.slice(i * LOADER_CHUNK_, (i + 1) * LOADER_CHUNK_);
  }
  props[LP_.PARTS] = String(parts);
  props[LP_.SHA] = sha;
  props[LP_.VERSION] = version;
  props[LP_.FROM] = from;
  sp.setProperties(props, false);                 // one write, all or nothing
  for (var j = parts; j < old; j++) sp.deleteProperty(LP_.CODE + j);
  edldModule_ = null;
}

// ── entry points Google calls ─────────────────────────────────────────────────

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var m;
  try { m = edld_(); } catch (err) { return json_({ ok: false, error: String(err.message || err) }); }
  if (!m) {
    return json_({ ok: false, error: 'EDLD is not installed in this sheet yet — ' +
                   'open it and run ED Dashboard > Upgrade' });
  }
  return m.doPost(e);
}

function doGet(e) {
  var m = edldQuiet_();
  if (!m) return json_({ ok: false, error: 'EDLD is not installed in this sheet yet' });
  return m.doGet(e);
}

function onOpen(e) {
  var m = edldQuiet_();
  var menu = SpreadsheetApp.getUi().createMenu('ED Dashboard');
  var items = (m && m.MENU) || [];
  for (var i = 0; i < items.length && i < 8; i++) {
    menu.addItem(items[i].label, 'edldMenu' + i);
  }
  if (items.length) menu.addSeparator();
  menu.addItem(m ? 'Upgrade…' : 'Install / Upgrade…', 'edldUpgrade')
      .addItem('Update from branch…', 'edldSetBranch')
      .addItem('Set sheet token…', 'edldSetToken')
      .addItem('About', 'edldAbout')
      .addToUi();
  if (m && m.sheetVersion() < m.SHEET_VERSION) {
    SpreadsheetApp.getActive().toast(
      'This sheet has upgrade steps waiting. Run ED Dashboard > Upgrade.',
      'ED Dashboard', 10);
  }
}

function onEdit(e) {
  var m = edldQuiet_();
  if (m && m.onEdit) m.onEdit(e);
}

function onSelectionChange(e) {
  var m = edldQuiet_();
  if (m && m.onSelectionChange) m.onSelectionChange(e);
}

// Fixed names the menu can point at; which item each runs is the bundle's.
function edldMenu_(i) {
  var m = edld_();
  if (m && m.MENU && m.MENU[i]) m.MENU[i].run();
}
function edldMenu0() { edldMenu_(0); }
function edldMenu1() { edldMenu_(1); }
function edldMenu2() { edldMenu_(2); }
function edldMenu3() { edldMenu_(3); }
function edldMenu4() { edldMenu_(4); }
function edldMenu5() { edldMenu_(5); }
function edldMenu6() { edldMenu_(6); }
function edldMenu7() { edldMenu_(7); }

// ── Upgrade ───────────────────────────────────────────────────────────────────

function fetchText_(url) {
  if (!/^https:\/\/raw\.githubusercontent\.com\//.test(url)) {
    throw new Error('refusing to fetch from ' + url +
                    ' — sheet code comes only from raw.githubusercontent.com');
  }
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) {
    var err = new Error('could not fetch ' + url + ' (HTTP ' + res.getResponseCode() + ')');
    err.status = res.getResponseCode();
    throw err;
  }
  return res.getContentText('UTF-8');
}

var BRANCH_RE_ = /^[A-Za-z0-9][A-Za-z0-9._\/-]{0,99}$/;

function branch_() {
  var b = PropertiesService.getScriptProperties().getProperty(LP_.BRANCH);
  return b && BRANCH_RE_.test(b) ? b : EDLD_DEFAULT_BRANCH;
}

function overridden_() {
  return !!PropertiesService.getScriptProperties().getProperty(LP_.RELEASE_URL);
}

function releaseUrl_() {
  return PropertiesService.getScriptProperties().getProperty(LP_.RELEASE_URL) ||
         EDLD_REPO_RAW + '/' + branch_() + '/sheets/release.json';
}

/** Where updates come from, in words. */
function sourceName_() {
  if (overridden_()) return releaseUrl_();
  var b = branch_();
  return 'branch ' + b + (b === EDLD_DEFAULT_BRANCH ? ' (releases)' : ' (development builds)');
}

/**
 * A file named by the manifest, from beside the manifest. Only a bare file
 * name is accepted, so a manifest cannot send the loader anywhere else.
 */
function besideManifest_(manifestUrl, file) {
  if (!/^[A-Za-z0-9._-]+$/.test(String(file || ''))) {
    throw new Error('the release manifest names its bundle as "' + file +
                    '"; only a file name beside the manifest is accepted');
  }
  return manifestUrl.replace(/[^\/]*$/, file);
}

/** Fetch and check the release manifest. Throws with a readable message. */
function fetchRelease_() {
  var url = releaseUrl_();
  var rel;
  try {
    rel = JSON.parse(fetchText_(url));
  } catch (err) {
    if (err.status === 404) {
      throw new Error('there is no sheet release on ' + sourceName_() +
                      ' — ' + url + ' was not found. ' +
                      (overridden_() ? 'Check the EDLD_RELEASE_URL script property.'
                                     : 'Pick another branch with ED Dashboard > ' +
                                       'Update from branch…, or wait until one is merged.'));
    }
    throw err;
  }
  if (!rel.version || !rel.bundle || !rel.bundle.file || !rel.bundle.sha256) {
    throw new Error('the release manifest is missing version or bundle details');
  }
  rel.manifestUrl = url;
  rel.bundleUrl = besideManifest_(url, rel.bundle.file);
  rel.sha256 = String(rel.bundle.sha256).toLowerCase();
  return rel;
}

/** "20260926-dev" alone, or with the bundle's hash when versions tie. */
function label_(version, sha, other) {
  return version + (other && sha ? ' (' + sha.slice(0, 8) + ')' : '');
}

function edldUpgrade() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActive();
  var sp = PropertiesService.getScriptProperties();
  var installed = sp.getProperty(LP_.VERSION) || '';
  var installedSha = sp.getProperty(LP_.SHA) || '';
  var current = edldQuiet_();
  // Recorded on the sheet, so it is known even with no code installed.
  var sheetHave = Number(PropertiesService.getDocumentProperties()
                           .getProperty('EDLD_SHEET_VERSION') || 0);

  var rel;
  try { rel = fetchRelease_(); } catch (err) {
    ui.alert('Upgrade', 'Could not read the latest release from ' + sourceName_() +
             '. Nothing was changed.\n\n' + err.message, ui.ButtonSet.OK);
    return;
  }
  if (Number(rel.min_loader || 1) > LOADER_VERSION) {
    ui.alert('Upgrade',
      'EDLD ' + rel.version + ' needs a newer loader than the one in this sheet.\n\n' +
      'Replace this project\'s Loader.gs with the one from that release ' +
      '(sheets/Loader.gs), save, reload the sheet and run Upgrade again. ' +
      'Nothing has been changed.', ui.ButtonSet.OK);
    return;
  }
  var sheetTo = Number(rel.sheet_version || 0);
  // By hash, not version: a development branch keeps one version across many
  // commits, and each of them is new code to install.
  if (current && installedSha === rel.sha256 && sheetHave >= sheetTo) {
    ui.alert('Upgrade', 'This sheet is up to date — EDLD ' + installed +
             ', sheet layout v' + sheetHave + ', from ' + sourceName_() + '.',
             ui.ButtonSet.OK);
    return;
  }

  var tie = installed === rel.version;
  var ask = (installed ? 'Upgrade this sheet from EDLD ' + label_(installed, installedSha, tie) +
                         ' to ' + label_(rel.version, rel.sha256, tie) + '?'
                       : 'Install EDLD ' + rel.version + ' in this sheet?') +
            '\n\nFrom ' + sourceName_() + '.' +
            '\n\nThe sheet code is replaced' +
            (sheetTo > sheetHave ? ', and the layout goes from v' + sheetHave + ' to v' +
             sheetTo + ':' + (rel.sheet_steps || []).filter(function (st) {
               return st.to > sheetHave; }).map(function (st) {
               return '\n  • ' + st.name; }).join('') +
             '\n\nDeposits is copied to a hidden backup tab first' : '') +
            '. Your deposits, settings, URL and token are kept.' +
            (sheetTo < sheetHave
              ? '\n\nThis sheet\'s layout (v' + sheetHave + ') is newer than this code ' +
                'expects (v' + sheetTo + ') — usually a step back from a development ' +
                'build. Nothing in the sheet is undone; the older code leaves the ' +
                'newer columns alone.'
              : '');
  if (ui.alert('Upgrade', ask, ui.ButtonSet.YES_NO) !== ui.Button.YES) return;

  var src, mod;
  try {
    src = fetchText_(rel.bundleUrl);
    var sha = sha256Hex_(src);
    if (sha !== rel.sha256) {
      throw new Error('the downloaded code does not match the release manifest ' +
                      '(SHA-256 ' + sha.slice(0, 12) + '…, expected ' +
                      rel.sha256.slice(0, 12) + '…). GitHub can serve a file ' +
                      'for a few minutes after a push changes it; if this ' +
                      'branch was pushed just now, wait five minutes and run ' +
                      'Upgrade again.');
    }
    mod = compile_(src);
  } catch (err) {
    ui.alert('Upgrade', 'Nothing was changed.\n\n' + err.message, ui.ButtonSet.OK);
    return;
  }

  if (!sp.getProperty(LP_.TOKEN) && !askToken_(ui, true)) {
    ui.alert('Upgrade', 'Nothing was changed. A token is needed before EDLD ' +
             'can accept deposits.', ui.ButtonSet.OK);
    return;
  }

  // The same lock doPost holds, so a commander's write waits for the upgrade
  // instead of landing between the new code and the layout it expects.
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  var done;
  try {
    storeCode_(src, rel.version, rel.sha256, rel.manifestUrl);
    done = edld_().upgradeSheet();
  } catch (err) {
    ui.alert('Upgrade', 'The upgrade stopped part way.\n\n' + err.message +
             '\n\nRun Upgrade again: finished steps are recorded and are not ' +
             'repeated. Deposits are untouched.', ui.ButtonSet.OK);
    return;
  } finally {
    lock.releaseLock();
  }

  var lines = ['EDLD ' + rel.version + ' is installed.'];
  if (done.steps.length) {
    lines.push('', 'Sheet layout v' + done.from + ' → v' + done.to + ':');
    done.steps.forEach(function (s) { lines.push('  • ' + s); });
  }
  if (done.backup) lines.push('', 'Backup of Deposits: hidden tab "' + done.backup + '".');
  if (!installed) {
    lines.push('', 'One last manual step, only this once: Deploy > Manage ' +
               'deployments > edit (pencil) > Version: New version > Deploy. ' +
               'The web app keeps its URL, and from now on upgrades need no redeploy.');
  }
  ui.alert('Upgrade', lines.join('\n'), ui.ButtonSet.OK);
  onOpen();
}

// ── where updates come from ───────────────────────────────────────────────────

function edldSetBranch() {
  var ui = SpreadsheetApp.getUi();
  var sp = PropertiesService.getScriptProperties();
  var res = ui.prompt('Update from branch',
    'Which branch of EDLD should this sheet take its code from?\n\n' +
    'Now: ' + sourceName_() + '\n\n' +
    '  main — releases. Leave the box blank for this.\n' +
    '  dev — development builds, to try sheet changes before they are released.\n\n' +
    'Changing this installs nothing by itself: run Upgrade afterwards.',
    ui.ButtonSet.OK_CANCEL);
  if (res.getSelectedButton() !== ui.Button.OK) return;
  var branch = String(res.getResponseText() || '').trim() || EDLD_DEFAULT_BRANCH;
  if (!BRANCH_RE_.test(branch) || branch.indexOf('..') >= 0) {
    ui.alert('Update from branch', '"' + branch + '" is not a branch name. ' +
             'Nothing was changed.', ui.ButtonSet.OK);
    return;
  }
  if (branch === EDLD_DEFAULT_BRANCH) sp.deleteProperty(LP_.BRANCH);
  else sp.setProperty(LP_.BRANCH, branch);
  ui.alert('Update from branch', 'This sheet now updates from ' + sourceName_() +
           '. Run ED Dashboard > Upgrade to install from it.' +
           (overridden_() ? '\n\nNote: the EDLD_RELEASE_URL script property is ' +
                            'set, and takes precedence over the branch.' : ''),
           ui.ButtonSet.OK);
}

// ── token ─────────────────────────────────────────────────────────────────────

function edldSetToken() { askToken_(SpreadsheetApp.getUi(), false); }

/**
 * Ask for the token squadron members use. Returns whether one was stored.
 * First-time installs are offered the old one from Code.gs — it cannot be
 * read out of a file that has already been replaced by this one.
 */
function askToken_(ui, firstTime) {
  var res = ui.prompt('Sheet token',
    (firstTime
      ? 'If this sheet already had EDLD set up, paste the token from the old ' +
        'Code.gs (the text between the quotes in TOKEN = \'…\') so everybody\'s ' +
        'EDLD keeps working.\n\n'
      : 'Paste a new token. Everybody\'s EDLD must then be given it.\n\n') +
    'Leave it blank to generate a new one.', ui.ButtonSet.OK_CANCEL);
  if (res.getSelectedButton() !== ui.Button.OK) return false;
  var token = String(res.getResponseText() || '').trim();
  if (!token) {
    token = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    ui.alert('Sheet token', 'New token — give it to everybody who publishes to ' +
             'this sheet, in EDLD\'s Options:\n\n' + token, ui.ButtonSet.OK);
  } else if (token.length < 16 || /\s/.test(token)) {
    ui.alert('Sheet token', 'A token needs at least 16 characters and no spaces. ' +
             'Nothing was changed.', ui.ButtonSet.OK);
    return false;
  }
  PropertiesService.getScriptProperties().setProperty(LP_.TOKEN, token);
  return true;
}

// ── About ─────────────────────────────────────────────────────────────────────

function edldAbout() {
  var sp = PropertiesService.getScriptProperties();
  var m = edldQuiet_();
  var sha = sp.getProperty(LP_.SHA) || '';
  SpreadsheetApp.getUi().alert('ED Dashboard',
    'EDLD sheet code: ' + (sp.getProperty(LP_.VERSION) || 'not installed') +
    (sha ? ' (' + sha.slice(0, 8) + ')' : '') + '\n' +
    'Sheet layout: v' + Number(PropertiesService.getDocumentProperties()
                                 .getProperty('EDLD_SHEET_VERSION') || 0) +
    (m ? ' (this code expects v' + m.SHEET_VERSION + ')' : '') + '\n' +
    'Loader: v' + LOADER_VERSION + '\n' +
    'Token: ' + (sp.getProperty(LP_.TOKEN) ? 'set' : 'not set') + '\n' +
    'Updates from: ' + sourceName_() + '\n' +
    'Installed from: ' + (sp.getProperty(LP_.FROM) || '—'),
    SpreadsheetApp.getUi().ButtonSet.OK);
}
