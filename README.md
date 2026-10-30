# Helper

Windows 上的軟體安裝自動化與系統設定工具，以系統管理員權限執行。3.0.1 以前的名稱誤寫為「Hpler」，3.0.2 起更正。

> **公開版**：程式和內部使用的 v3.0.2 相同。文件與測試裡的內部軟體名稱改成範例（`SampleDeskTool`、`SampleDeskFiles`、`SampleMonitor` 等），驗收紀錄裡的本機路徑改為 `<工作資料夾>`。

## 目前狀態

依「需求 → 設計 → 規劃 → 實作」的順序進行：

| 步驟 | 文件 | 狀態 |
|---|---|---|
| 1. 需求 | [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | 定版 v1.3（2026-10-27） |
| 2. 設計 | [`docs/DESIGN.md`](docs/DESIGN.md) | 定版 v1.10（2026-10-27） |
| 3. 開發規劃 | [`docs/ROADMAP.md`](docs/ROADMAP.md) | 定版 v1.0（2026-10-21） |
| 4. 實作與測試 | — | **v3.0.2 已發行（2026-10-27）**：產品名稱從 Hpler 改為 Helper；繁中 Windows 的第 19、31 項待測試機。v3.0.1 已發行（2026-10-27）：修正輸出 UTF-8 的程式在日誌裡的中文亂碼。v3.0.0 已發行（2026-10-25）；v2.0.1 已發行（2026-10-22）；2.0.2 暫不發版 |

版本變更見 [`CHANGELOG.md`](CHANGELOG.md)。

**第一次使用或維護，先看 [`docs/GUIDE.md`](docs/GUIDE.md)（Helper 3.0 使用與維護，一頁的重點整理）。** 同樣內容的 HTML 版是 [`docs/guide.html`](docs/guide.html)，下載後用瀏覽器開啟，方便傳給同事。

3.0 的部署與維護的完整說明：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)（目錄結構、權限、暫存資料夾需要的空間）、[`docs/MAINTENANCE.md`](docs/MAINTENANCE.md)（新增軟體與任務、何時設定 `copyFirst`、問題清單、從 2.0 轉換）。

## 開發環境

需要 Python 3.12 x64（含 tkinter）。

```
pip install -r requirements-dev.txt     安裝開發用套件
python -m pytest                        執行測試
python helper.py                        直接執行（helper_software\ 放在 helper.py 旁邊）
pyinstaller --clean --noconfirm helper.spec   打包成 dist\helper.exe
python tools\ini2xml.py <2.0 資源資料夾> <輸出資料夾>   2.0 的 INI 轉成 3.0 的設定檔（設計第 11 節）
```

產品名稱與版本號只寫在 `hpler/__init__.py`，打包時會寫進執行檔的版本資訊。程式的套件名稱沿用 `hpler`：使用者看不到，改成 `helper` 會和 `helper.py` 同名（設計第 2.4 節）。
