/**
 * 毎朝のニュースダイジェスト用クリック追跡サーバー。
 * - 通常のGET: クリックをスプレッドシートに記録するだけ(サイト側はfetch(...,{keepalive:true})の
 *   ビーコンとして叩く。記事へのリンクは直接飛ばすので、ここでのリダイレクトは行わない。
 *   Apps ScriptのHtmlOutputは常にサンドボックスiframe経由になり、外部サイトへのJSリダイレクトが
 *   フレーム埋め込みを拒否するサイトで失敗するため、リダイレクト方式は採用していない)
 * - ?mode=summary: 直近のクリック傾向をJSONで返す(生成スクリプトのパーソナライズ用、要シークレットキー)
 */

const SHEET_NAME = 'Clicks';

function doGet(e) {
  const params = e.parameter || {};
  if (params.mode === 'summary') {
    return handleSummary(params);
  }
  if (params.mode === 'raw') {
    return handleRaw(params);
  }
  return handleClick(params);
}

function getSpreadsheet() {
  const props = PropertiesService.getScriptProperties();
  const existingId = props.getProperty('SPREADSHEET_ID');
  if (existingId) {
    try {
      return SpreadsheetApp.openById(existingId);
    } catch (err) {
      // 保存されたIDが無効な場合は新規作成にフォールバック
    }
  }
  const ss = SpreadsheetApp.create('News Digest Clicks');
  props.setProperty('SPREADSHEET_ID', ss.getId());
  return ss;
}

function getSheet() {
  const ss = getSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (sheet) return sheet;

  const sheets = ss.getSheets();
  if (sheets.length === 1 && sheets[0].getLastRow() === 0) {
    sheet = sheets[0];
    sheet.setName(SHEET_NAME);
  } else {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  sheet.appendRow(['timestamp', 'kind', 'category', 'title', 'dest']);
  return sheet;
}

function handleClick(params) {
  const dest = params.dest || '';
  const kind = params.kind || '';
  const category = params.cat || '';
  const title = params.t || '';

  try {
    getSheet().appendRow([new Date(), kind, category, title, dest]);
  } catch (err) {
    // 記録に失敗してもビーコン呼び出し元(fetch)は気にしないので黙って無視
  }

  return jsonOutput({ ok: true });
}

function handleSummary(params) {
  const secret = PropertiesService.getScriptProperties().getProperty('SUMMARY_SECRET');
  if (!secret || params.key !== secret) {
    return jsonOutput({ error: 'unauthorized' });
  }

  const kindFilter = params.kind || '';
  const days = Number(params.days) > 0 ? Number(params.days) : 30;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);

  const values = getSheet().getDataRange().getValues();
  const counts = {};

  for (let i = 1; i < values.length; i++) {
    const row = values[i];
    const ts = row[0];
    const kind = row[1];
    const category = row[2];
    if (!(ts instanceof Date) || ts < since) continue;
    if (!category) continue;
    if (kindFilter && kind !== kindFilter) continue;
    counts[category] = (counts[category] || 0) + 1;
  }

  return jsonOutput(counts);
}

function handleRaw(params) {
  const secret = PropertiesService.getScriptProperties().getProperty('SUMMARY_SECRET');
  if (!secret || params.key !== secret) {
    return jsonOutput({ error: 'unauthorized' });
  }

  const limit = Number(params.limit) > 0 ? Number(params.limit) : 50;
  const values = getSheet().getDataRange().getValues();
  const rows = values.slice(1).map(function (row) {
    return {
      timestamp: row[0] instanceof Date ? row[0].toISOString() : row[0],
      kind: row[1],
      category: row[2],
      title: row[3],
      dest: row[4],
    };
  });
  rows.reverse(); // 新しい順
  return jsonOutput(rows.slice(0, limit));
}

function jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
