import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const file = await FileBlob.load("D:/scalperagent_v4/outputs/acetry-7d-mtf-tables/acetry-7d-mtf-spike-tables.xlsx");
const workbook = await SpreadsheetFile.importXlsx(file);
const overview = await workbook.inspect({ kind: "sheet,table", include: "id,name", tableMaxRows: 2, tableMaxCols: 4, maxChars: 5000 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(overview.ndjson);
console.log(errors.ndjson);
