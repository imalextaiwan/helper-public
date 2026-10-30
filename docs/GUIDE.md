# Helper 3.0 使用與維護

| 項目 | 內容 |
|---|---|
| 對象 | 在測試機上執行工具的人、新增軟體與系統設定任務的人、開發者 |
| 最後更新 | 2026-10-27 |
| 依據 | Helper 3.0.2、`docs/DESIGN.md` v1.10。3.0.1 以前的名稱誤寫為「Hpler」 |
| 詳細說明 | [`DEPLOYMENT.md`](DEPLOYMENT.md)（部署）、[`MAINTENANCE.md`](MAINTENANCE.md)（維護） |
| HTML 版 | [`guide.html`](guide.html)：內容相同，可以傳給沒有 repo 權限的人。GitHub 上只會顯示原始碼，請下載後用瀏覽器開啟 |

Helper 在測試機上批次安裝測試軟體、套用系統設定。這份是一頁的重點整理，細節以上面兩份文件為準。

> **還沒驗收的部分：** 真實的系統設定任務（包括由 2.0 的 INI 轉換來的 .cmd）、在沒有安裝 Python 的電腦上執行。系統設定任務會停用 UAC、防火牆、Defender，請先在可以重灌的電腦上試。兩個會修改安全設定的軟體（關閉核心隔離；關閉 HVCI 與易受攻擊驅動程式封鎖清單）沒有以工具實際安裝過。其他項目已在繁體中文與英文版 Windows 11 上驗收。

- [使用](#使用)
- [維護](#維護)
- [開發者](#開發者)

---

## 使用

在測試機上執行工具的人。

### 部署（只做一次）

從 [GitHub Release](https://github.com/imalextaiwan/helper-public/releases/latest) 下載最新版的 `helper.exe`，和資源資料夾放在同一層。目標電腦不需要安裝 Python。

```
D:\Helper\
├─ helper.exe
└─ helper_software\               資源資料夾（也可以叫 Helper，再保留一個版本）
   ├─ software.xml                軟體清單
   ├─ system_tasks.xml            系統設定任務清單（選用）
   ├─ software.xsd、system_tasks.xsd   給編輯器檢查格式用（選用）
   ├─ helper_icon.ico             視窗圖示（選用；3.0.1 以前的 hpler_icon.ico 也可以）
   ├─ tasks\<任務 id>.cmd
   └─ <各軟體子資料夾>\
```

- **權限**：工具以系統管理員身分執行資料夾裡的安裝檔與 .cmd，所以 `D:\Helper` 只能讓系統管理員寫入。以系統管理員身分開啟命令提示字元執行下面的指令，只對這個專用資料夾執行：
  ```bat
  icacls "D:\Helper" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX
  ```
- **空間**：執行時先把勾選的軟體複製到「下載」資料夾。真實資料全選約複製 18.2 GB，「下載」所在的磁碟至少要有約 20 GB 可用空間。
- **網路磁碟**：用 `\\server\share\Helper\helper.exe` 這種路徑，或先複製到本機。`Z:` 這類磁碟機代號在提權後可能看不到。
- **從 3.0.0、3.0.1 升級**：只要換掉 `helper.exe`，設定檔都相同。舊版留下的 `Hpler_*` 暫存資料夾會在下一輪自動刪除；舊的日誌（`Hpler_….log`）留在原處；資源資料夾裡的 `hpler_icon.ico` 照樣可以用。

### 執行

1. 雙擊 `helper.exe`，UAC 按「是」。按「否」工具不會開啟。
2. 如果跳出「設定檔的問題」，表示有項目設定錯了。那些項目不會出現在清單上，其他照常使用。按「複製」可以把內容貼給維護的人。
3. 選「軟體安裝」或「系統設定」分頁，勾選要執行的項目（預設全部勾選）。「全選」「全不選」只作用於目前的分頁。
4. 按「開始執行」。工具先把勾選的軟體複製到「下載」裡的 `Helper_<日期時間>`，全部複製完才依序執行，全部結束後刪除這個資料夾。
5. 執行中可以按「暫停」（再按一次是「繼續」）或「取消」，都在目前的項目完成後才生效。執行中關閉視窗，會先問你確定要關閉嗎。
6. 完成對話框列出成功與失敗的數量；按「取消」時沒有執行的項目另外列出，不算失敗。
7. 「日誌資料夾」會開啟桌面的 `QT_TOOL_LOGS`。每執行一輪一個檔案（`Helper_軟體安裝_<日期時間>.log`），裡面有每個項目的完整命令列與輸出。回報問題時請附上。

### 項目旁的狀態

| 狀態 | 意思 |
|---|---|
| 等待中 | 還沒輪到 |
| 複製中、已複製 | 正在複製到暫存資料夾、已經複製好 |
| 執行中 | 正在執行 |
| 成功 | 結束碼是 0，或是設定為成功的結束碼 |
| 成功（3010） | 成功，但安裝程式要求重新開機 |
| 失敗（5） | 以括號裡的結束碼結束；原因在日誌 |
| 逾時 | 超過時間，這個項目與它啟動的程式都已被結束 |
| 無法啟動 | 找不到或無法執行安裝檔；原因在日誌 |
| 複製失敗 | 複製到暫存資料夾時出錯（例如網路中斷、檔案被鎖定），這個項目沒有執行 |

### 常見狀況

| 看到的狀況 | 原因與處理 |
|---|---|
| 「Helper 無法啟動」，列出預期的目錄結構 | 找不到 `software.xml`，或檔案不是合法的 XML、不是 UTF-8。依訊息修正 |
| 「空間不足」 | 「下載」所在的磁碟不夠。清出空間，或少勾幾個大型軟體 |
| 完成對話框列出「刪不掉的檔案」 | 有程式還在使用暫存檔。下一輪執行時會再刪除，也可以重新開機後再執行一次 |
| 系統設定分頁顯示「系統設定無法使用」 | 找不到 `system_tasks.xml`，或檔案有錯誤。原因顯示在分頁上，也在問題清單裡 |
| 「無法建立日誌檔」 | 桌面的 `QT_TOOL_LOGS` 無法建立（例如有同名的檔案）。沒有執行任何項目，處理後再按「開始執行」 |

---

## 維護

新增、修改軟體與系統設定任務的人。

### 開始之前

- 所有設定都在 `helper_software\` 裡；資料夾只有系統管理員能寫入，要以系統管理員身分編輯。
- 建議用 VS Code 加上 Red Hat 的「XML」擴充功能：XML 開頭指向同一個資料夾裡的 XSD，打錯欄位或漏掉必填欄位會即時標示。
- XML 以 UTF-8 存檔；名稱裡的 `&` 寫成 `&amp;`，`<` 寫成 `&lt;`。
- `id` 只能用小寫英文、數字、底線，同一個檔案裡不可重複。XML 裡的順序就是畫面上與執行的順序。

### 新增軟體

1. 在 `helper_software\` 建立子資料夾，放入安裝檔。要顯示圖示的話，放一個 `icon.png`（或 .ico、.jpg、.gif）。
2. 在 `software.xml` 想要顯示的位置加一筆：
   ```xml
   <item id="cpu_z">
     <name>CPU-Z</name>
     <folder>CPU-Z</folder>
     <executable>cpu-z_2.20.2-en.exe</executable>
     <args>/silent</args>
   </item>
   ```
3. 重新開啟工具，確認沒有跳出問題清單、新的軟體出現在清單上，再到測試機上實際安裝一次。

| 欄位 | 說明 |
|---|---|
| `<name>` | 畫面上顯示的名稱，可以用中文 |
| `<folder>` | 子資料夾名稱；不能是絕對路徑，也不能含 `..` |
| `<executable>` | 子資料夾裡的安裝檔名稱，只寫檔名 |
| `<args>` | 選用。參數原樣傳給安裝檔，例如 `/D=C:\Program Files\App` 不會被拆開 |
| `successCodes` | 選用，寫在 `<item>` 上。安裝程式以 3010 表示「成功，要重新開機」時，寫 `successCodes="0,3010"` |
| `copyFirst` | 選用，預設 `true`。見下一段 |

### 什麼時候設定 `copyFirst="false"`

預設會先把整個子資料夾複製到「下載」裡的暫存資料夾，從複本執行，結束後刪除。下面兩種情況改成 `copyFirst="false"`，直接從資源資料夾執行：

- **本身就會把檔案複製到桌面**：例如 SampleDeskTool（28.6 GB）、SampleDeskFiles。不用複製兩次。
- **執行後還要用自己資料夾裡的檔案**：例如建立的捷徑指向自己的資料夾。暫存資料夾刪除後，捷徑會失效。

不確定時保留預設值，在測試機上執行一次，確認暫存資料夾刪除後仍然正常。

### 新增系統設定任務

1. 從原始碼的 `resources\templates\` 擇一複製，改名為 `tasks\<任務 id>.cmd`：`run_all.cmd`（每一步都執行，有一步失敗就算失敗）或 `stop_on_error.cmd`（任何一步失敗就停）。
2. 寫好指令，例如：
   ```bat
   @echo off
   rem Helper system task: run every step, fail if any step failed
   setlocal
   set "FAILED=0"

   powercfg /change monitor-timeout-ac 0 || set "FAILED=1"
   powercfg /change standby-timeout-ac 0 || set "FAILED=1"

   exit /b %FAILED%
   ```
3. 在 `system_tasks.xml` 對應的分類裡加上：
   ```xml
   <task id="power_008">
     <name>螢幕與待機永不關閉</name>
     <description>插電時不關閉螢幕、不進入待機</description>
   </task>
   ```
4. **在測試機上以系統管理員身分雙擊 .cmd 測一次**，確認結果正確、結束時沒有停下來等輸入。再重新開啟工具，確認任務出現在清單上。

.cmd 的規則：

- 成功時 `exit /b 0`，失敗時以非 0 結束，不然失敗會被當成成功。
- 存成 ANSI（Big5），或內容只用英文；換行用 CRLF（記事本預設）。
- 不要用 `pause` 或任何要等輸入的指令；不要用 `wmic`（Windows 11 24H2 起預設停用）。
- 要印出 `%` 時寫 `%%`，`for` 迴圈的變數寫 `%%i`；設定變數寫成 `set "X=1"`。
- 新增分類：在 `system_tasks.xml` 加上 `<category id="…" name="畫面上的名稱">`，裡面放 `<task>`。

### 改完之後：看問題清單

工具啟動時會檢查兩個 XML。有問題的項目不顯示在清單上，並跳出問題清單。常見的訊息：

| 訊息 | 處理 |
|---|---|
| 找不到執行檔 | `<folder>` 或 `<executable>` 打錯，或檔案還沒放進子資料夾 |
| 找不到腳本 `tasks\…cmd` | .cmd 的檔名和 `id` 不同，或還沒放進 `tasks\` |
| `tasks\….cmd` 沒有登記 | `tasks\` 裡有 .cmd，但 XML 沒有對應的 `<task>` |
| 有不認得的元素／屬性 | 欄位名稱打錯，例如把 `<args>` 寫成 `<arg>`：這個欄位會被忽略 |
| id 重複 | 只保留第一筆 |
| 不是合法的 XML：第 N 行第 M 欄 | 標籤沒有關閉、`&` 沒有寫成 `&amp;` 等，依行號修正 |

### 從 2.0 的 INI 轉換

3.0 不讀 2.0 的 `config.ini`、`system_optimizations.ini`。在有原始碼與 Python 3.12 的電腦上執行：

```bat
python tools\ini2xml.py <2.0 的資源資料夾> <輸出資料夾> --no-copy-first software17,software18
```

- 輸出資料夾必須是新的或空的；`--no-copy-first` 列出要設為 `copyFirst="false"` 的軟體 id。
- 逐項看過轉換報告 `ini2xml_report.txt`，再把輸出的 XML、XSD、`tasks\` 放進資源資料夾。
- 轉換出來的每個 .cmd 都要在測試機上以系統管理員身分執行一次。
- 要退回 2.0.x 時，換回 2.0.x 的執行檔即可：INI 和 XML 可以放在同一個資源資料夾。

---

## 開發者

修改程式、打包、發版的人。

### 常用指令

```bat
pip install -r requirements-dev.txt
python -m pytest
pyinstaller --clean --noconfirm helper.spec
```

- 需要 Python 3.12 x64（含 tkinter）。打包的輸出是 `dist\helper.exe`；Windows 的檔名不分大小寫，會蓋掉 `dist\` 裡同名的 `Helper.exe`。
- 產品名稱與版本號只寫在 `hpler/__init__.py`。套件名稱沿用 `hpler`：使用者看不到，改成 `helper` 會和 `helper.py` 同名（設計第 2.4 節）。
- 3.x 的修改開 PR 到預設分支；2.0.x 的修正在 `release/2.0` 分支。
- 發版：驗收清單通過 → 更新 [`CHANGELOG.md`](../CHANGELOG.md) → 合併 → 建立標籤 → GitHub Release 附上驗收過的執行檔。詳見 [`ROADMAP.md`](ROADMAP.md) 第 7 節。

### 還沒完成的事

- 在可以重灌的繁中 Windows 11 測試機上補做驗收清單 C 第 19、31 項，以及每個轉換後的 .cmd 實際執行一次（驗收資料夾與說明已準備好）。
- 建立 `main` 分支與保護規則；設定 GitHub Actions（之後由 CI 跑測試與打包）。
