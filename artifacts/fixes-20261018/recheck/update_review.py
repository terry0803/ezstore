from pathlib import Path
import json,shutil
ROOT=Path('D:/筆電2/資料探勘第一次作業/ezstore')
OUT=Path(__file__).parent
ART=ROOT/'artifacts/fixes-20261018/recheck'
ART.mkdir(parents=True,exist_ok=True)
for p in OUT.iterdir():
    if p.suffix in {'.log','.json','.py'}:shutil.copy2(p,ART/p.name)
slides=json.loads((OUT.parent/'ezstore_reaudit_strict_20261018/EZStore-Agent-Workshop-LAB_AIG.pptx.json').read_text(encoding='utf-8'))
(ART/'workshop-references.json').write_text(json.dumps([s for s in slides if s['slide'] in (10,17,20)],ensure_ascii=False,indent=2),encoding='utf-8')
cloud_note='CLI 雲端評分路徑未設定 GCP 專案；選用時另需 ADC 等認證。講義允許 AI Studio API key，未要求購買雲端服務；助教正式成績與雲端服務是兩件事。'
new_note='同日再檢查發現金額捨入問題，尚未修正：650 × 0.3333 × 3 儲存後單價 216.65、小計 649.94，但單價 × 數量應為 649.95。'
report=ROOT/'reports/修正與完整自檢_20261018.html'
s=report.read_text(encoding='utf-8')
s=s.replace('<h2>這次驗證的範圍</h2>',f'<div class="notice"><strong>後續再檢查更新：</strong>{new_note} <a href="再檢查與GCP說明_20261018.html">查看重現證據與 GCP／ADC 更正</a></div><h2>這次驗證的範圍</h2>')
s=s.replace('本地驗收已補；正式雲端待環境','本地驗收已補；CLI 雲端路徑待設定')
s=s.replace('原版託管評分仍缺 GCP／ADC，不把本地分數當教師成績。',cloud_note)
s=s.replace('合法值先捨入四位再計價，避免儲存與金額不一致。','合法因子先捨入四位再計價，修正因子超過四位時的計價差異；貨幣單價的捨入另見後續發現。')
report.write_text(s,encoding='utf-8',newline='\n')
p=ROOT/'reports/可信賴度報告.md';s=p.read_text(encoding='utf-8')
s=s.replace('非教師正式雲端成績','非助教私有題庫的正式成績').replace('正式託管評分仍缺 GCP／ADC；',cloud_note)
s=s.replace('**結論與限制。**',f'**同日再檢查：尚未修正。** {new_note} [重現與說明](再檢查與GCP說明_20261018.html)\n\n**結論與限制。**')
p.write_text(s,encoding='utf-8',newline='\n')
p=ROOT.parent/'影片/簡報.html';s=p.read_text(encoding='utf-8')
s=s.replace('正式雲端評分待環境','CLI 雲端評分路徑待設定').replace('教師正式託管評分缺 GCP／ADC','CLI 雲端評分未設定 GCP 專案')
s=s.replace('<h2>還沒覆蓋的風險</h2>','<h2>已知問題與驗證限制</h2>')
s=s.replace('<li>評審和被評的是同一個模型，可能偏寬</li>','<li class="warn">新發現：單價與小計分別捨入，216.65 × 3 與小計 649.94 不一致，尚未修正</li>\n    <li>評審和被評的是同一個模型，可能偏寬；CLI 雲端評分不等於助教正式成績</li>')
p.write_text(s,encoding='utf-8',newline='\n')
body='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EZStore 再檢查與 GCP 說明</title>
<style>body{font:17px/1.7 system-ui,"Microsoft JhengHei",sans-serif;background:#eef2f5;color:#203344;margin:0}main{max-width:1040px;margin:32px auto;background:white;padding:36px;border-radius:14px}h1{font-size:29px}h2{font-size:22px;margin-top:28px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #ccd5df;text-align:left}th{background:#e9eff4}a{color:#096c95}.notice{padding:16px;background:#fff1d6;border-left:5px solid #b47b1c}code{overflow-wrap:anywhere}</style><main>
<h1>EZStore 再檢查與 GCP／ADC 說明</h1><p>2026-10-18｜本次為重新檢查；未修改業務程式。修正前次報告的雲端評分措辭，並記錄新發現。</p>
<div class="notice"><strong>仍有一項已重現的程式問題：</strong>金額單價與小計的四捨五入不一致。既有測試全部通過，不能據此宣稱沒有 BUG。</div>
<h2>新發現：P2 金額精度不一致（尚未修正）</h2>
<p>在隔離後端 <code>127.0.0.1:58080</code> 新增報價，商品牌價 650、因子 0.3333、數量 3。再次 GET 讀回：</p>
<table><tr><th>欄位</th><th>金額</th></tr><tr><td>儲存單價</td><td>216.65</td></tr><tr><td>儲存小計</td><td>649.94</td></tr><tr><td>單價 × 數量</td><td>216.65 × 3 = 649.95</td></tr><tr><td>差異</td><td>小計少 0.01</td></tr></table>
<p>原因：<code>backend/services/quotation_service.go:213</code> 用未捨入單價計算小計，模型中的單價與小計欄位各自儲存成兩位小數，造成分別捨入。影響單據核算與資料一致性；修正時需統一貨幣計算精度，並讓前端預覽、後端儲存及顧問驗證採用一致規則。</p>
<p><a href="../artifacts/fixes-20261018/recheck/rounding-probe.json">實際請求與讀回資料</a> · <a href="../artifacts/fixes-20261018/recheck/probe_rounding.py">隔離環境重現程式</a></p>
<h2>本次重跑結果與範圍</h2><ul>
<li>Python 549 項＋4 子測試全部通過（294＋255）；Go 11 個測試函式通過；瀏覽器 17／17 通過。</li>
<li>199 份受測檔案在檢查開始時與上一輪雜湊一致；兩個 Agent 執行中的來源、31 個知識檔與本機檔案一致，四個服務健康／路由檢查回傳 200。</li>
<li>本次未重新消耗 Gemini 額度，也未重跑 30＋19 項真實模型測試或 LLM 評審；那些結果屬上一輪同版本證據，95.0／100 仍是本地自評。</li>
<li>原資料庫仍為 15 客戶、20 商品、12 報價、10 訂單，逐筆雜湊與修正前相同。新重現只寫隔離資料庫。</li>
</ul><p><a href="../artifacts/fixes-20261018/recheck/python-agent.log">Python 第一組</a> · <a href="../artifacts/fixes-20261018/recheck/python-advisor.log">Python 第二組</a> · <a href="../artifacts/fixes-20261018/recheck/go-tests.log">Go</a> · <a href="../artifacts/fixes-20261018/recheck/e2e-tests.log">UI 10 項</a> · <a href="../artifacts/fixes-20261018/recheck/e2e-existing.log">其餘 UI 7 項</a> · <a href="../artifacts/fixes-20261018/recheck/source-and-auth.json">版本與設定狀態</a></p>
<h2>更正「老師雲端缺 GCP／ADC」的說法</h2>
<p>前次把工具的雲端評分路徑稱為「教師正式雲端評分」，不夠準確。講義第 10 頁允許 AI Studio API key，GCP／Vertex AI 是可選方式；第 17 頁說明助教用私有題庫在本機評分，未要求學生購買雲端服務。</p>
<table><tr><th>名詞</th><th>在這個專案的意思</th></tr><tr><td>GCP project</td><td>Google Cloud 的專案識別，用於指定雲端服務所屬專案、權限及配額。</td></tr><tr><td>ADC</td><td>Application Default Credentials；Google 函式庫尋找身分憑證的機制，讓程式代表已授權的使用者或服務帳號呼叫雲端服務。</td></tr><tr><td>Gemini API key</td><td>目前 Agent 透過 AI Studio 路徑呼叫 Gemini 使用的金鑰；持有 key 不表示 CLI 已配置專案及雲端認證。</td></tr></table>
<p>目前安裝的 <code>agents-cli</code> v1.10.0，對老師設定的 <code>refusal_or_action</code> prompt 指標會走雲端評分服務，<code>cmd_grade.py:245</code> 先要求解析 project。本次直接錯誤是 <code>Could not determine GCP project</code>；標準本機 ADC 檔也不存在，但尚未走到雲端權限、API 啟用或計費驗證，不能說是已收到 ADC 驗證失敗。</p>
<p>所以：Agent 使用 API key 對話與「此 CLI 指標呼叫雲端評分服務」是兩條路徑。沒有配置後者不表示 Agent 不能運作，也不表示作業必須部署到老師的雲端。本地自評與助教正式成績應持續分開標示。</p>
<p><a href="../artifacts/fixes-20261018/recheck/workshop-references.json">講義第 10／17／20 頁文字</a> · <a href="../artifacts/fixes-20261018/teacher-grade.log">前次 CLI 原始錯誤</a> · <a href="https://docs.cloud.google.com/docs/authentication/application-default-credentials">Google 官方 ADC 說明</a></p>
<h2>繳交前仍應揭露</h2><p>本版修補了老師限制的基底檔案（4 個功能檔、3 個測試檔），嚴格基底檢查仍不相符；使用者允許修補不等於老師核准。另有尚未修正的金額精度問題，不能標示全部問題已解決。</p>
<p><a href="修正與完整自檢_20261018.html">上一輪 14 項修正與證據</a> · <a href="可信賴度報告_20261018.pdf">更新的一頁報告</a></p></main></html>'''
(ROOT/'reports/再檢查與GCP說明_20261018.html').write_text(body,encoding='utf-8',newline='\n')
print('Updated review, current report, slide disclosure, and evidence.')
