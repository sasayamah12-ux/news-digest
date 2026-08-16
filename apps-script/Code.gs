/**
 * 毎朝のニュースダイジェスト用クリック/インプレッション追跡サーバー。
 *
 * イベント種別(event列):
 * - impression: そのページ表示時に「並んでいた」記事(クリックされたかどうかは問わない)
 * - click: 見出しの実クリック(実際に記事へ遷移)
 * - chip_click: 深掘りチップのタップ(claude.aiへ遷移)
 *
 * エンドポイント:
 * - GET  (event未指定=click / event=chip_click): 1件のクリック系イベントを記録
 * - POST (JSON配列): ページ表示時のインプレッションをまとめて記録
 * - GET ?mode=summary: 直近のクリック/インプレッション件数をカテゴリ別に返す(要シークレットキー)
 * - GET ?mode=raw: 直近の生ログ行を返す(要シークレットキー)
 *
 * サイト側はfetch(...,{keepalive:true})のビーコンとして叩くだけで、記事へのリンク自体は
 * 直接記事URLを指す(Apps ScriptのHtmlOutputは常にサンドボックスiframe経由になり、外部サイトへの
 * JSリダイレクトがフレーム埋め込みを拒否するサイトで失敗するため、リダイレクト方式は採用していない)。
 */

const SHEET_NAME = 'Events';
const HEADER = ['timestamp', 'event', 'kind', 'category', 'position', 'source', 'title', 'keyword', 'dest'];

function doGet(e) {
  const params = e.parameter || {};
  if (params.mode === 'summary') return handleSummary(params);
  if (params.mode === 'raw') return handleRaw(params);
  return handleClick(params);
}

function doPost(e) {
  return handleImpressions(e);
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
  sheet.appendRow(HEADER);
  return sheet;
}

function rowFromParams(p) {
  return [
    new Date(),
    p.event || 'click',
    p.kind || '',
    p.cat || '',
    p.pos || '',
    p.src || '',
    p.t || '',
    p.keyword || '',
    p.dest || '',
  ];
}

function handleClick(params) {
  try {
    getSheet().appendRow(rowFromParams(params));
  } catch (err) {
    // 記録に失敗してもビーコン呼び出し元(fetch)は気にしないので黙って無視
  }
  return jsonOutput({ ok: true });
}

function handleImpressions(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const records = Array.isArray(body) ? body : [];
    if (records.length > 0) {
      const sheet = getSheet();
      const rows = records.slice(0, 200).map(function (p) {
        return [
          new Date(),
          'impression',
          p.kind || '',
          p.cat || '',
          p.pos || '',
          p.src || '',
          p.t || '',
          '',
          p.dest || '',
        ];
      });
      sheet
        .getRange(sheet.getLastRow() + 1, 1, rows.length, HEADER.length)
        .setValues(rows);
    }
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
  const stats = {}; // category -> { clicks, impressions }

  for (let i = 1; i < values.length; i++) {
    const row = values[i];
    const ts = row[0];
    const event = row[1];
    const kind = row[2];
    const category = row[3];
    if (!(ts instanceof Date) || ts < since) continue;
    if (!category) continue;
    if (kindFilter && kind !== kindFilter) continue;
    if (event !== 'click' && event !== 'impression') continue;

    if (!stats[category]) stats[category] = { clicks: 0, impressions: 0 };
    if (event === 'click') stats[category].clicks += 1;
    else stats[category].impressions += 1;
  }

  return jsonOutput(stats);
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
      event: row[1],
      kind: row[2],
      category: row[3],
      position: row[4],
      source: row[5],
      title: row[6],
      keyword: row[7],
      dest: row[8],
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
