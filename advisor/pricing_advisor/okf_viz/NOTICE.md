# 來源與授權

`viz.html`、`viz.css`、`viz.js` 原封不動取自
[GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
的 `src/reference_agent/viewer/`（main 分支，2026-10-17 取得），版權屬 Google LLC，
授權為 Apache License 2.0（https://www.apache.org/licenses/LICENSE-2.0），檔案開頭保留原本的聲明。

`__init__.py` 是本專案改寫的資料產生程式，參考原本的 `viewer/generator.py`：
連結以 `/` 開頭（相對於知識庫根目錄）也算關聯、`sources` 指到知識庫內的條目也畫成關聯，
信任等級與過期狀態改用 `pricing_advisor.okf` 計算。
