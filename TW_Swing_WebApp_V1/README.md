# TW Swing 手機 Web App V1.0

公開、唯讀的台股籌碼看板。管理者登入後可透過 GitHub Actions 啟動更新；訪客無法更新。**目前仍是待連線驗證的 MVP，不代表全市場完成接入。**

## 功能與界線
- 公開：三級籌碼名單、5 日法人淨買股數、大戶持股占比、評分歷史、資料日期及 CSV 匯出。
- 僅管理者：登入後透過 GitHub API 發送 `workflow_dispatch`，查看工作執行頁。
- GitHub Actions：平日台灣時間 17:20 排程、下載官方 TWSE / TDCC、寫入 SQLite 及公開 CSV、提交 GitHub。
- 尚未接入：上櫃 TPEX 自動抓取、月營收、技術訊號、主力分點。**所以「準備下手」不會自動給股票。**
- 需先確認官方開放資料的再次散布條款，確定允許將輸出資料公開。

## 在 GitHub 部署
1. 建立一個 GitHub **公開 repository**，例如 `TW-Swing`，上傳此資料夾**內全部檔案**（包括隱藏的 `.github/workflows/update.yml`）；絕對不要上傳真實 `secrets.toml`。
2. 在 GitHub `Settings > Actions > General > Workflow permissions` 啟用允許 GitHub Actions 寫入 repository 的權限（如政策允許）。
3. 在 GitHub `Actions > Update public market data` 手動執行一次 workflow。首次資料抓取需要更多歷史：10 個交易日法人資料、至少 5 週集保資料；本程式**不自動補齊 TDCC 多週歷史**，所以初期評分可能全部顯示「資料不足」。
4. 前往 https://share.streamlit.io/ 以 GitHub 帳號部署 `app.py`，Python requirements 由 requirements.txt 提供。公開網址可用手機查看。網站是否休眠取決於服務方案。
5. 於 Streamlit App Settings > Secrets 填寫下面的 Secret 欄位；不要把真實密碼提交到 GitHub。若沒有 Secrets，前台仍可展示資料，但管理者更新會停用。

```toml
ADMIN_PASSWORD = "請換成夠長且唯一的管理者密碼"
GITHUB_PAT = "只授予該儲存庫 Actions: write 的 fine-grained PAT"
GITHUB_OWNER = "你的GitHub帳號"
GITHUB_REPO = "TW-Swing"
GITHUB_BRANCH = "main"
```

管理者專用 fine-grained personal access token（PAT）應只選擇單一 repository，授權 `Actions: write`，設定有效期限；定期輪換。如 App 不支援指定權限，請停止部署管理者按鈕，改使用 GitHub Actions 手動觸發。此程式不將 token 提供給瀏覽器。

## 資料處理及安全提醒
- `pipeline.py` 使用原始官方 API，未經此環境線上實際驗證；官方 API 異動可能造成失敗，需查看 Actions 紀錄。
- 目前內建 SQLite 保存在 repo，做為簡易 MVP 歷史累積；**資料量增加後建議遷移到 PostgreSQL / Supabase**，以避免 Git 歷史肥大、重複寫入等問題。
- 公開 repository 的 `output/`、SQLite 都是公開資料，不放使用者資料、交易庫存、授權金鑰。
- 目前管理者密碼是基本驗證，適合單人低頻使用，不是企業級身份驗證；沒有伺服器端 IP 限速。上線後宜改用獨立 OAuth 或 OIDC 登入。
- `streamlit` 頁面本身不是完整背景工作服務；按鈕只發送 GitHub Actions 工作，不會在手機上下載資料。
- 盤後排程可能延遲；不保證資料即時性；交易日期、可得時間與匯入時間不可混淆。

## 本機測試
```bash
pip install -r requirements.txt
streamlit run app.py
python pipeline.py --offline
```
`--offline` 不會抓真實數據，只產生空白報表作測試。 `pipeline.py` 可執行於 GitHub Actions，不需要手機持續開啟。

## 官方來源
- https://openapi.tdcc.com.tw/v1/opendata/1-5
- https://www.twse.com.tw/rwd/zh/fund/T86
