import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "D:/scalperagent_v4/backend/acetry-7d-mtf-spike-research.json";
const outputDir = "D:/scalperagent_v4/outputs/acetry-7d-mtf-tables";
const outputPath = `${outputDir}/acetry-7d-mtf-spike-tables.xlsx`;
const research = JSON.parse(await fs.readFile(inputPath, "utf8"));
const timeframes = ["1m", "5m", "15m", "1h", "4h"];
const labels = { "1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4" };
const indicatorFields = [
  ["alignment", "Yön"],
  ["adx", "ADX"],
  ["di_gap", "DI Farkı"],
  ["ema20_slope_3_pct", "EMA20 Eğim (3 mum) %"],
  ["atr_pct", "ATR %"],
  ["volume_ratio_20", "Hacim / 20 Ort."],
  ["bb_position", "Bollinger Konumu"],
  ["bb_width_pct", "Bollinger Genişliği %"],
  ["rsi_14", "RSI 14"],
  ["mfi_14", "MFI 14"],
];

function istanbulTime(ms) {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date(ms)).replace(" ", " ");
}

function valueOrNull(value) {
  return value === undefined ? null : value;
}

const workbook = Workbook.create();
for (const tf of timeframes) {
  const sheet = workbook.worksheets.add(labels[tf]);
  sheet.showGridLines = false;
  const title = `${labels[tf]} ACETRY Sıçrama Başlangıç Göstergeleri`;
  const headers = [
    "Sıçrama Başlangıcı (Europe/Istanbul)",
    ...indicatorFields.map(([, label]) => label),
    "MTF Bullish Sayısı", "MTF Alignment Skoru", "Başlangıç Fiyatı", "Zirve Fiyatı",
    "Başlangıç-Zirve Süresi (dk)", "Başlangıç-Zirve Getirisi %", "Karar-Zirve Getirisi %",
  ];
  sheet.getRange(`A1:${String.fromCharCode(64 + headers.length)}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A2:${String.fromCharCode(64 + headers.length)}2`).merge();
  sheet.getRange("A2").values = [["Etiket: sonraki 60 dakikada en az %2 yükseliş. Gelecek fiyatlar yalnızca sonuç etiketi olarak kullanılmıştır; göstergeler sıçrama başlangıcında kapanmış mumlardan hesaplanmıştır."]];
  sheet.getRange(`A4:${String.fromCharCode(64 + headers.length)}4`).values = [headers];

  const rows = research.events.map((event) => {
    const snap = event.features.timeframes[tf];
    return [
      istanbulTime(event.onset_time),
      ...indicatorFields.map(([key]) => valueOrNull(snap[key])),
      event.features.mtf_bullish_count,
      event.features.mtf_alignment_score,
      event.onset_price,
      event.peak_price,
      event.onset_to_peak_minutes,
      event.onset_to_peak_pct,
      event.decision_to_peak_pct,
    ];
  });
  if (rows.length) sheet.getRangeByIndexes(4, 0, rows.length, headers.length).values = rows;

  const lastRow = 4 + rows.length;
  const lastCol = String.fromCharCode(64 + headers.length);
  const table = sheet.tables.add(`A4:${lastCol}${lastRow}`, true, `${labels[tf]}SpikeTable`);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  sheet.freezePanes.freezeRows(4);
  sheet.freezePanes.freezeColumns(1);

  sheet.getRange(`A1:${lastCol}1`).format = { fill: "#0F3D56", font: { bold: true, color: "#FFFFFF", size: 14 }, horizontalAlignment: "center", verticalAlignment: "center" };
  sheet.getRange(`A1:${lastCol}1`).format.rowHeight = 28;
  sheet.getRange(`A2:${lastCol}2`).format = { fill: "#EAF3F7", font: { italic: true, color: "#274C5E", size: 9 }, wrapText: true, verticalAlignment: "center" };
  sheet.getRange(`A2:${lastCol}2`).format.rowHeight = 32;
  sheet.getRange(`A4:${lastCol}4`).format = { fill: "#1F6F8B", font: { bold: true, color: "#FFFFFF" }, wrapText: true, horizontalAlignment: "center", verticalAlignment: "center" };
  sheet.getRange(`A4:${lastCol}4`).format.rowHeight = 34;
  sheet.getRange(`A5:A${lastRow}`).format.numberFormat = "@";
  sheet.getRange(`B5:B${lastRow}`).format.horizontalAlignment = "center";
  sheet.getRange(`C5:K${lastRow}`).format.numberFormat = "0.000";
  sheet.getRange(`L5:M${lastRow}`).format.numberFormat = "0";
  sheet.getRange(`N5:O${lastRow}`).format.numberFormat = "0.000";
  sheet.getRange(`P5:P${lastRow}`).format.numberFormat = "0.0";
  sheet.getRange(`Q5:R${lastRow}`).format.numberFormat = "0.00";
  sheet.getRange(`A4:${lastCol}${lastRow}`).format.borders = { preset: "inside", style: "thin", color: "#D9E5EA" };
  sheet.getRange(`A:A`).format.columnWidth = 25;
  sheet.getRange(`B:B`).format.columnWidth = 12;
  sheet.getRange(`C:K`).format.columnWidth = 14;
  sheet.getRange(`L:M`).format.columnWidth = 13;
  sheet.getRange(`N:O`).format.columnWidth = 14;
  sheet.getRange(`P:R`).format.columnWidth = 16;
  sheet.getRange(`Q5:Q${lastRow}`).conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"] });
  sheet.getRange(`R5:R${lastRow}`).conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"] });
}

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

for (const tf of timeframes) {
  const preview = await workbook.render({ sheetName: labels[tf], range: "A1:R14", scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${labels[tf].toLowerCase()}-preview.png`, new Uint8Array(await preview.arrayBuffer()));
}

const check = await workbook.inspect({ kind: "table", range: "M1!A1:R10", include: "values,formulas", tableMaxRows: 10, tableMaxCols: 18, maxChars: 5000 });
console.log(check.ndjson);
console.log(`SAVED ${outputPath}`);
