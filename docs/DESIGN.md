# Helper 設計文件

| 項目 | 內容 |
|---|---|
| 狀態 | **定版 v1.10**（2026-10-27）。之後修改設計，須記錄在第 18 節 |
| 最後更新 | 2026-10-27 |
| 依據 | `docs/REQUIREMENTS.md` v1.3 |
| 適用版本 | 3.0.x 為主；2.0.1、2.0.2 見第 15 節 |

---

## 1. 概述

本文件說明 Helper **怎麼實作**需求規格裡的每一條需求。每一節的標題都標出對應的需求編號，第 17 節有完整的需求追溯表。

**設計原則：**

1. **設定與程式分開**：新增或修改軟體、任務時只改設定檔，不改程式（NFR-03）。
2. **非介面邏輯不依賴 tkinter**：路徑、設定讀取、執行都能在沒有視窗的環境下測試（NFR-04）。
3. **錯誤不靜默**：任何被略過或失敗的項目，都會顯示在畫面上或寫進日誌（NFR-05）。
4. **Windows API 集中管理**：只有 `paths`、`admin`、`runner`、`staging` 四個模組會呼叫 Windows API 或 Windows 專屬的指令，其他模組可以在任何平台上測試。

---

## 2. 系統架構（3.0）

### 2.1 模組

| 模組 | 職責 | 可以依賴 |
|---|---|---|
| `helper.py` | 進入點：權限處理 → 讀設定 → 啟動介面 | 所有 `hpler` 模組 |
| `hpler/__init__.py` | 產品名稱、版本號（全程式唯一來源） | — |
| `hpler/models.py` | 資料模型（純資料，沒有任何邏輯） | — |
| `hpler/paths.py` | 執行檔位置、資源資料夾、桌面與下載資料夾路徑 | — |
| `hpler/admin.py` | 權限檢查、以管理員身分重新啟動 | — |
| `hpler/config.py` | 讀取兩個 XML、執行啟動檢查 | `models`、`paths` |
| `hpler/staging.py` | 暫存資料夾：空間檢查、建立與權限、複製、刪除、清除殘留（第 7.7 節） | `models`、`paths` |
| `hpler/runner.py` | 一輪執行的三個階段（複製、執行、刪除）；執行安裝檔與 .cmd、逾時、輸出解碼 | `models`、`staging`、`logs`、`paths`（下載資料夾的位置） |
| `hpler/logs.py` | 每輪執行的日誌檔 | `paths` |
| `hpler/gui.py` | Tkinter 介面 | `models`、`config`、`runner`、`logs` |
| `tools/ini2xml.py` | 2.0 INI 轉 3.0 XML 與 .cmd（不打包進執行檔） | `config`（讀回比對，第 11 節） |

### 2.2 依賴規則

```
helper.py
   │
   ├──► gui ──► config ──► models
   │      │        └─────► paths
   │      ├──► runner ──► models
   │      │        ├─────► staging ──► paths
   │      │        ├─────► logs ──► paths
   │      │        └─────► paths
   │      └──► logs
   └──► admin
```

- 箭頭只能往下指，不能反向依賴。
- **只有 `gui` 可以 import tkinter**（含會載入 tkinter 的 `PIL.ImageTk`）。
- `hpler/__init__.py` 只有產品名稱與版本號，每個模組都可以使用。
- 只用於型別標註的 import（放在 `if TYPE_CHECKING:` 裡）執行時不會載入，不算依賴。
- 違反規則的 import 由 `tests/test_architecture.py` 檢查（見第 14 節）；T03 完成後也在 CI 執行。

### 2.3 部署結構

```
X:\
├─ helper.exe                  單一執行檔（PyInstaller onefile）
└─ helper_software\            資源資料夾（Helper\ 也接受，見第 3 節）
   ├─ software.xml             軟體清單
   ├─ software.xsd             給編輯器檢查用
   ├─ system_tasks.xml         系統設定任務清單
   ├─ system_tasks.xsd         給編輯器檢查用
   ├─ helper_icon.ico          視窗圖示（3.0.1 以前是 hpler_icon.ico，見第 2.4 節）
   ├─ tasks\                   每個任務一個 .cmd
   │  └─ power_001.cmd …
   └─ <各軟體子資料夾>\
      ├─ setup.exe …
      └─ icon.png（選用）
```

執行時另外在「下載」資料夾建立暫存資料夾，結束後刪除，見第 7.7 節。

### 2.4 產品名稱（FR-23）

產品名稱是 **Helper**。2.0～3.0.1 誤寫為「Hpler」，3.0.2 起更正（DD18）。

**原則：使用者看得到的名稱一律改為 Helper，程式內部的識別名稱不改。**

| 項目 | 3.0.1 以前 | 3.0.2 起 | 舊名稱的相容 |
|---|---|---|---|
| 介面（視窗標題、對話框、狀態列）、日誌開頭的工具名稱 | Hpler | Helper（取自 `PRODUCT_NAME`） | — |
| 執行檔版本資訊的產品名稱、描述 | Hpler | Helper（`helper.spec` 取自 `PRODUCT_NAME`，和版本號相同） | — |
| 日誌檔名 | `Hpler_<模式>_<時間>.log` | `Helper_<模式>_<時間>.log`（第 8 節） | 舊的日誌留在原處，不改名；工具不會讀取舊的日誌 |
| 暫存資料夾、標記檔 | `Hpler_<時間>\`、`.hpler_staging` | `Helper_<時間>\`、`.helper_staging`（第 7.7 節） | 清除殘留時也刪除 3.0.0、3.0.1 留下的 `Hpler_*`，安全條件相同（第 7.7 節） |
| 資源資料夾裡的視窗圖示 | `hpler_icon.ico` | `helper_icon.ico` | 沒有 `helper_icon.ico` 時使用 `hpler_icon.ico`，現有的部署只換執行檔就能使用；兩個都沒有時不顯示圖示，和現在相同 |
| 打包用的圖示 | `assets/hpler_icon.ico` | `assets/helper_icon.ico` | 只在 repo 裡，不影響部署 |
| .cmd 範本與轉換工具輸出的註解 | `rem Hpler system task: …` | `rem Helper system task: …`（附錄 A） | 只是註解：已轉換的 .cmd 不需要重新轉換 |
| XSD 裡的說明文字 | Hpler | Helper | 只供編輯器顯示 |

**不改的名稱：**

- Python 套件 `hpler/`：使用者看不到；改成 `helper/` 會和進入點 `helper.py` 同名，`import helper`（`tests/test_entry.py`）會載入套件而不是進入點。
- 程式內部的識別名稱（例如 Tk 的樣式名稱 `Hpler.TNotebook`）：使用者看不到，改名只會增加變動。
- 本來就正確的名稱：`helper.exe`、`helper_software\`、`Helper\`、日誌資料夾 `QT_TOOL_LOGS`。
- 2.0.x（`release/2.0`）：維持 Hpler，見第 15 節。

---

## 3. 資源資料夾解析（FR-10～FR-13、FR-22）

**執行檔位置**：打包後以 `sys.executable` 所在的資料夾為準；直接執行 .py 時，以主程式所在的資料夾為準。兩者都不使用目前的工作目錄，所以從捷徑或其他資料夾啟動，結果都相同（FR-13）。

**尋找順序**：

| 順序 | 2.0.1 | 3.0 |
|---|---|---|
| 1 | `Helper\config.ini` | `helper_software\software.xml` |
| 2 | `helper_software\config.ini` | `Helper\software.xml`（保留一個版本，FR-22） |
| 3 | 執行檔旁邊的 `config.ini`（舊佈局，FR-12） | 執行檔旁邊的 `software.xml`（DD8） |
| 都找不到 | 回傳第 1 順位的路徑，讓錯誤訊息指出預期位置 | 同左 |

找到的資料夾就是資源資料夾，之後所有相對路徑都以它為基準。

---

## 4. 設定檔格式（FR-16、FR-18、FR-19、FR-32）

### 4.1 共通規則

| 規則 | 說明 |
|---|---|
| 編碼 | UTF-8，有沒有 BOM 都可以（FR-15） |
| `id` | 只能用小寫英文、數字、底線（`^[a-z0-9_]+$`），同一個檔案內不可重複 |
| 順序 | XML 裡的排列順序，就是介面顯示與執行的順序 |
| 特殊字元 | 手動編輯時，`&` 要寫成 `&amp;`、`<` 要寫成 `&lt;`。用轉換工具產生的檔案會自動處理 |
| 逾時 | 寫在根元素的 `timeout` 屬性，單位是秒，省略時預設 300 秒（DD6） |

### 4.2 `software.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<software timeout="1000"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:noNamespaceSchemaLocation="software.xsd">
  <item id="3dmark">
    <name>3DMark</name>
    <folder>3DMark</folder>
    <executable>setup.exe</executable>
    <args>/S</args>
  </item>
  <item id="vcredist" successCodes="0,3010">
    <name>Visual C++ 可轉散發套件</name>
    <folder>VCRedist</folder>
    <executable>vc_redist.x64.exe</executable>
    <args>/install /quiet /norestart</args>
  </item>
  <item id="sample_desk_tool" copyFirst="false">
    <name>SampleDeskTool</name>
    <folder>SampleDeskTool</folder>
    <executable>SampleDeskTool.exe</executable>
  </item>
</software>
```

| 元素或屬性 | 必填 | 說明 |
|---|---|---|
| `<software timeout>` | `timeout` 選填 | 根元素 |
| `<item id>` | 是 | 一個軟體項目 |
| `<item successCodes>` | 否 | 視為成功的結束碼，以逗號分隔，預設 `0`。例如安裝程式以 3010 表示「成功，但需要重新開機」時，寫成 `0,3010`（FR-41） |
| `<item copyFirst>` | 否 | 執行前是否先複製到暫存資料夾（第 7.7 節），`true` 或 `false`，預設 `true`。本身就會把檔案複製到桌面的工具設為 `false`，避免複製兩次（FR-46、DD14） |
| `<name>` | 是 | 介面上顯示的名稱 |
| `<folder>` | 是 | 子資料夾名稱，相對於資源資料夾；不可以是絕對路徑，也不可含 `..` |
| `<executable>` | 是 | 子資料夾裡的執行檔名稱 |
| `<args>` | 否 | 參數，原樣傳給執行檔（見第 7.2 節） |

圖示沿用 2.0 的慣例：子資料夾裡有 `icon.ico`／`.png`／`.jpg`／`.jpeg`／`.gif` 就自動使用，XML 不另外設定（FR-16）。圖示是選用的，沒有圖示的項目照常顯示（Q10）。

2.0 的 `base_path` 設定在 3.0 取消，軟體子資料夾一律直接放在資源資料夾底下（DD7）。

### 4.3 `system_tasks.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<systemTasks timeout="300"
             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
             xsi:noNamespaceSchemaLocation="system_tasks.xsd">
  <category id="power" name="電源與穩定性優化">
    <task id="power_001">
      <name>高效能電源</name>
      <description>切換為高效能電源計畫</description>
    </task>
  </category>
  <category id="security" name="安全性與存取優化">
    <task id="security_001">
      <name>關閉 UAC</name>
      <description>停用使用者帳戶控制提示</description>
    </task>
  </category>
</systemTasks>
```

| 元素或屬性 | 必填 | 說明 |
|---|---|---|
| `<systemTasks timeout>` | `timeout` 選填 | 根元素 |
| `<category id name>` | 兩者都必填 | 一個分類，介面上顯示為一個區塊（FR-32） |
| `<task id>` | 是 | 一個任務；`id` 在整個檔案內唯一 |
| `<name>` | 是 | 介面上顯示的名稱 |
| `<description>` | 否 | 說明 |

**腳本位置固定為 `tasks\<id>.cmd`**，XML 不另外寫路徑，避免兩邊對不起來。

### 4.4 .cmd 撰寫規則（FR-19、FR-42）

| # | 規則 | 不遵守的後果 |
|---|---|---|
| 1 | 成功時 `exit /b 0`；任何一步失敗時以非 0 結束 | 失敗會被判成成功 |
| 2 | 存成 ANSI（Big5），或內容只用英文 | 用 UTF-8 存的話，中文 `echo` 會變成亂碼 |
| 3 | 換行用 CRLF（repo 以 `.gitattributes` 強制） | 只有 LF 時，`goto`／`call :label` 可能出錯 |
| 4 | 檔名只用英文小寫、數字、底線，和 `id` 相同 | 找不到腳本 |
| 5 | 不使用 `pause` 或任何需要輸入的指令 | 沒有地方讓人輸入，任務會卡住直到逾時 |
| 6 | 不使用 `wmic` | Windows 11 24H2 起預設停用，指令會失敗 |
| 7 | 寫好後以系統管理員身分雙擊測試一次 | 和工具執行時的環境不一致 |

依失敗時要不要繼續，從附錄 A 的兩個範本擇一使用。

### 4.5 XSD（Q6）

- `software.xsd`、`system_tasks.xsd` 和 XML 放在一起，XML 透過 `xsi:noNamespaceSchemaLocation` 指向它們。
- **用途只有一個**：在 VS Code 等編輯器裡即時提示格式錯誤。
- 程式執行時不讀 XSD，所以不需要額外的套件。程式端的檢查由第 6.2 節負責，其中「腳本檔是否存在」這類檢查是 XSD 做不到的。

---

## 5. 資料模型（`hpler/models.py`）

```python
@dataclass(frozen=True)
class Software:
    id: str
    name: str
    folder: Path            # 絕對路徑
    executable: Path        # 絕對路徑
    args: str               # 原始字串，不切割
    success_codes: frozenset[int]  # 預設 {0}
    copy_first: bool        # 預設 True（第 7.7 節）
    icon: Path | None

@dataclass(frozen=True)
class SystemTask:
    id: str
    name: str
    description: str
    script: Path            # 絕對路徑：<資源資料夾>\tasks\<id>.cmd

@dataclass(frozen=True)
class TaskCategory:
    id: str
    name: str
    tasks: tuple[SystemTask, ...]

@dataclass(frozen=True)
class Problem:
    severity: Literal["fatal", "error", "warning"]
    file: str               # 例如 "software.xml"
    item_id: str | None
    message: str

@dataclass(frozen=True)
class LoadResult:
    resource_dir: Path
    software: tuple[Software, ...]
    software_timeout: int
    categories: tuple[TaskCategory, ...]
    task_timeout: int
    problems: tuple[Problem, ...]

@dataclass(frozen=True)
class TaskResult:
    item_id: str
    status: Literal["success", "failed", "timeout", "error", "copy_failed"]
    exit_code: int | None
    duration_s: float
    output: str             # 已解碼的 stdout + stderr；失敗時含原因

@dataclass(frozen=True)
class CleanupResult:
    removed: tuple[Path, ...]      # 刪除的暫存資料夾
    leftovers: tuple[str, ...]     # 刪不掉的檔案與原因

@dataclass(frozen=True)
class BatchResult:
    results: tuple[TaskResult, ...]
    cleanup: CleanupResult
    aborted: str | None     # 沒有執行任何項目的原因，例如空間不足；正常為 None
```

所有模型都是唯讀的。介面的勾選狀態不放在模型裡，由 `gui` 以 `id` 對應自己的 `BooleanVar`。這樣讀設定時不需要建立任何 tkinter 物件，也就能在沒有視窗的環境下測試。

---

## 6. 啟動流程與檢查（FR-01、FR-02、FR-14、FR-15、FR-17、FR-20、FR-36）

### 6.1 流程

```
helper.py
 ├─ 1. 權限檢查（第 10 節）
 ├─ 2. paths：找出資源資料夾
 ├─ 3. config.load(resource_dir) → LoadResult
 │     └─ 有 fatal 問題 → 顯示錯誤（含預期的目錄結構）→ 結束（FR-14）
 ├─ 4. 建立介面
 └─ 5. problems 不是空的 → 顯示問題清單（FR-36）
```

### 6.2 檢查規則

| 狀況 | 嚴重度 | 處理方式 |
|---|---|---|
| 找不到資源資料夾或 `software.xml` | fatal | 顯示預期的目錄結構，結束 |
| `software.xml` 不是合法的 XML、不是 UTF-8 編碼，或根元素不是 `<software>` | fatal | 顯示檔名、行號、欄號，結束；不是 UTF-8 時提示改以 UTF-8 儲存 |
| 找不到 `system_tasks.xml` | warning | 系統設定分頁顯示「找不到設定檔」，並停用 |
| `system_tasks.xml` 不是合法的 XML、不是 UTF-8 編碼，或根元素不是 `<systemTasks>` | error | 系統設定分頁停用，列出行號、欄號 |
| 缺少必填欄位、必填欄位重複、`id` 不符合規則、`id` 重複 | error | 略過該項目；`id` 重複時保留第一筆 |
| `<folder>` 是絕對路徑或含 `..`；`<executable>` 含路徑 | error | 略過該項目 |
| 不認得的元素或屬性 | warning | 忽略該欄位。例如把 `<args>` 拼錯時，安裝檔會在沒有參數的情況下執行，所以要提醒 |
| 找不到執行檔或 `tasks\<id>.cmd` | error | 略過該項目，不顯示在清單上（DD4） |
| `tasks\` 裡有 .cmd，但 XML 沒有登記 | warning | 提醒（可能是忘了登記，或是應該刪掉的舊檔） |
| 分類裡沒有任何可用的任務 | warning | 不顯示該分類 |
| `timeout` 不是正整數 | error | 改用預設值 300 秒 |
| `successCodes` 不是以逗號分隔的整數 | error | 略過該項目（不套用預設值，避免把失敗誤判為成功） |
| `copyFirst` 不是 `true` 或 `false` | error | 改用預設值 `true` |

### 6.3 問題清單的呈現

- 啟動後，如果有 error 或 warning，跳出一個可以捲動的視窗，依檔案分組列出。每一筆顯示嚴重度、項目 `id` 和原因。
- 視窗提供「複製」按鈕，方便回報給維護者。
- 關掉視窗後，工具照常使用，被略過的項目不會出現在清單上。

---

## 7. 執行設計（FR-40～FR-48、FR-51）

### 7.1 執行緒與控制

```
主執行緒（介面）                       背景執行緒
────────────────                     ──────────
按「開始執行」
 └─ runner.run_batch(...) ──────────► 1. 複製：空間檢查，逐項複製到暫存資料夾（第 7.7 節）
                                       2. 執行：依序執行每個項目
                                          ├─ 每個項目開始前：
                                          │    檢查 cancel → 已設定就停止（FR-44）
                                          │    等待 resume → 暫停中就停在這裡（FR-43）
                                          └─ 執行完：on_progress(id, 結果)
                                       3. 刪除（finally）：刪除暫存資料夾
畫面更新 ◄── root.after(0, …) ────────┘
```

- **三個階段**：刪除放在 `finally`，全部完成、按「取消」、發生非預期錯誤時都會執行（FR-48）。
- **控制訊號**：取消和暫停都用 `threading.Event`，取代 2.0 在兩個執行緒之間共用的一般變數。
- **檢查時機**：取消和暫停只在兩個項目之間檢查，正在執行的項目不會被中斷（Q2）。複製階段也一樣，在兩個項目的複製之間檢查。
- **介面更新**：`runner` 不碰介面，只呼叫 `on_progress`。由 `gui` 透過 `root.after` 在主執行緒更新畫面，所以執行期間介面不會凍結（FR-40）。

### 7.2 軟體項目（FR-41）

- `copyFirst` 為 `true` 時，`folder` 與 `executable` 改用暫存資料夾裡的複本（第 7.7 節）；為 `false` 時直接用資源資料夾裡的檔案。
- 在 `<folder>` 底下執行 `<executable>`，參數 `<args>` **原樣**接在後面：
  ```python
  cmdline = subprocess.list2cmdline([str(executable)]) + (" " + args if args else "")
  subprocess.Popen(cmdline, cwd=folder, ...)
  ```
- Windows 上的程式本來就是自己解析命令列，原樣傳遞才符合各安裝檔的預期。
- **修正 2.0 的缺陷**：2.0 用 `shlex.split` 以 Unix 的規則切割參數，會吃掉反斜線、拆開路徑。實測 `/D=C:\Program Files\App` 會變成 `/D=C:Program` 和 `FilesApp`（DD5）。
- 結束碼屬於該項目的 `success_codes` 時為成功，預設只有 0（DD2）。成功代碼不是 0 時，狀態文字會顯示代碼，例如「成功（3010）」，提醒可能需要重新開機。

### 7.3 系統設定任務（FR-42）

- 勾選的 .cmd 一律先複製到 `<暫存資料夾>\tasks\`（DD16），再執行 `%SystemRoot%\System32\cmd.exe /d /s /c ""<暫存資料夾>\tasks\<id>.cmd""`，工作目錄設為暫存資料夾的 `tasks\`。
  - 用 `cmd.exe` 的完整路徑，避免執行到其他位置的同名檔案。
  - `/d` 停用登錄機碼裡的 AutoRun 設定，讓每台電腦的執行環境一致。
  - `/s` 加上兩層引號：路徑含空白時（例如使用者名稱有空白，下載資料夾就在 `C:\Users\John Smith\Downloads`），`cmd.exe` 仍能正確解析。
  - 先複製是因為資源資料夾放在網路磁碟（`\\server\share`）時，`cmd.exe` 不接受網路路徑作為工作目錄。.cmd 檔很小，複製的成本可以忽略。
- 結束碼 0 為成功，其他都是失敗。
- 腳本不接受任何參數，所以沒有參數注入的問題。

### 7.4 逾時（FR-41、FR-42）

- 軟體項目和任務各自使用所屬 XML 的 `timeout`，以「一個項目」為單位計算。2.0 是把時間平均分給每條指令，3.0 不再這樣做。
- 時間一到，以 `taskkill /PID <pid> /T /F` 結束整個行程樹（DD3）。
  - 只結束直接啟動的那個行程不夠：安裝程式常常會再啟動子行程（例如 `msiexec`）。子行程如果繼續執行，下一個安裝可能因為「另一個安裝正在進行」而失敗。
- 結果記為 `timeout`，算在失敗數裡。
- **輸出的讀取**：以背景執行緒逐段讀取，不用 `communicate()`。項目結束後最多再等 5 秒讀完輸出：安裝程式啟動的程式（例如安裝完自動開啟的軟體）如果還開著輸出管線，不能無限期等下去，這時在輸出後註明「它啟動的其他程式仍在執行」。
- **沒有輸入**：標準輸入接到空裝置。違反撰寫規則 5（`pause`、等待輸入）時，指令會立刻結束，不會卡到逾時。
- **不另開視窗**：以 `CREATE_NO_WINDOW` 啟動，主控台程式不會閃出黑色視窗；輸出已經寫進日誌。

### 7.5 輸出解碼（FR-45）

- 讀取原始的位元組，**逐行**解碼：能以 UTF-8 嚴格解碼的行用 UTF-8，其他行以系統的 OEM 碼頁解碼（`GetOEMCP()`，繁中 Windows 是 950），並加上 `errors="replace"`。
- **為什麼要判斷 UTF-8**：`cmd.exe` 和多數主控台程式以 OEM 碼頁輸出，但以 Python 等撰寫的工具常把輸出固定為 UTF-8（真實資料裡有好幾個這樣的包裝程式）。只用 OEM 碼頁解碼時，這些中文會變成亂碼（T44 繁中驗收發現，v1.9）。同一個 .cmd 裡可能兩種都有（例如先 `echo` 中文、再呼叫 Python 工具），所以逐行判斷，不是整段判斷。
- **誤判的機會很小**：cp950 的中文幾乎不會剛好是合法的 UTF-8。以本 repo 文件裡 1,572 行含中文的文字轉成 cp950 實測，沒有一行是合法的 UTF-8。可能誤判的只有「一行裡只有一兩個特定的中文字（例如單獨的『讀』），其他都是英數」，這種行會顯示成其他文字；結果的判定不受影響。
- 以 `\r`、`\n` 分行不會切開一個字：這兩個位元組不會出現在 UTF-8 或 cp950 的多位元組字元裡。換行字元原樣保留。
- 如果使用者開啟了「使用 Unicode UTF-8 提供全球語言支援」，OEM 碼頁會變成 65001，兩種方式都是 UTF-8。
- **解碼一定不會失敗**。2.0 以 UTF-8 嚴格解碼：輸出含中文時，subprocess 讀取輸出的執行緒會中止，`stdout`／`stderr` 變成 `None`。結果是失敗項目的錯誤訊息記不進日誌，系統設定任務也會因此出錯，略過同一個任務後面的指令（Python 3.12 實測，T20）。

### 7.6 結果判定與計數（FR-51）

| 狀態 | 條件 | 算成功嗎 |
|---|---|---|
| `success` | 結束碼屬於成功代碼（軟體項目預設 0，可設定；系統設定任務一律為 0） | 是 |
| `failed` | 結束碼不屬於成功代碼 | 否 |
| `timeout` | 超過逾時時間 | 否 |
| `error` | 無法啟動（例如執行檔被刪掉） | 否 |
| `copy_failed` | 複製到暫存資料夾失敗，沒有執行（FR-47） | 否 |

完成對話框直接統計 `TaskResult.status`。每個項目只有一個結果，成功數不會算錯。刪不掉的檔案（`CleanupResult.leftovers`）也列在完成對話框上（FR-48）。

### 7.7 暫存資料夾（FR-46～FR-48、NFR-07）

**位置**：`<下載>\Helper_<YYYYMMDD_HHMMSS>\`（3.0.1 以前是 `Hpler_`，見第 2.4 節）。下載資料夾以已知資料夾 API（`FOLDERID_Downloads`）取得，理由同 DD10（DD13）。

```
<下載>\Helper_20261021_153000\
├─ .helper_staging         標記檔：工具版本、建立時間、行程 ID
├─ 3DMark\                 copyFirst 為 true 的軟體子資料夾
├─ CrystalDiskInfo\
└─ tasks\                  系統設定模式：勾選的 .cmd
```

**建立：**

1. 建立資料夾，寫入標記檔 `.helper_staging`。只有帶標記檔的資料夾會被刪除。
2. 立刻設定權限：**整個權限清單（DACL）換成只有 Administrators 與 SYSTEM 完整控制**，並禁止繼承；擁有者改為 Administrators。標記檔的權限也重設為只從資料夾繼承。以 SDDL `O:BAD:P(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)` 與 `SetNamedSecurityInfoW` 設定，不受系統語系影響。
   - 理由：下載資料夾一般使用者可以寫入。不設權限的話，一般權限的程式可以在執行前替換複本，再由工具以管理員權限執行（NFR-07）。
   - **不能只「移除繼承的權限」**（原本的 `icacls /inheritance:r /grant:r`）：T44 驗收時發現，使用者資料夾（「下載」「桌面」）的權限沒有自動繼承的標記，子資料夾得到的使用者完整控制，`icacls` 不當成繼承的權限，移除不掉，一般權限的程式仍然可以寫入。所以改為整個換掉。
   - **擁有者改為 Administrators**：擁有者一定可以修改權限；如果擁有者是使用者本人，一般權限的程式可以先改權限再寫入。直接執行 .py 而且不是系統管理員時（只有測試）無法變更擁有者，保留原本的擁有者。
   - 影響：使用者以一般權限在檔案總管開啟這個資料夾時，會被要求提權。資料夾執行完就會刪除，平常看不到。

**流程：**

| 階段 | 做什麼 | 失敗時 |
|---|---|---|
| 1. 空間檢查 | 加總要複製的資料夾大小，加上 1 GB 餘裕，和下載資料夾所在磁碟的可用空間比較 | 不執行任何項目，訊息列出需要與可用的空間；`BatchResult.aborted` 記錄原因（FR-47） |
| 2. 複製 | 依清單順序逐項複製，項目狀態顯示「複製中」 | 該項目記為 `copy_failed`，刪除複製到一半的檔案，其他項目照常（FR-47） |
| 3. 執行 | 和第 7.2、7.3 節相同，路徑改用複本 | — |
| 4. 刪除 | 放在 `finally`，一定會執行 | 見下方 |

**刪除（FR-48）：**

- **時機**：所有項目都結束後才刪除，不在每個項目完成後立刻刪除。安裝程式結束時，它啟動的子程式可能還在讀取暫存資料夾裡的檔案（DD15）。
- **被佔用的檔案**：每 2 秒重試，最多 60 秒。仍然刪不掉就列在完成對話框與日誌，資料夾保留到下一輪再刪。
- **標記檔最後才刪**：先刪除其他所有檔案，全部刪掉後才刪標記檔與資料夾本身。有檔案刪不掉時保留標記檔，下一輪才認得出這是工具建立的資料夾（T46 的測試發現：標記檔先被刪掉的話，這個資料夾就永遠不會再被刪除）。
- **殘留**：同時刪除下載資料夾裡其他帶標記檔的 `Helper_*` 資料夾（先前異常結束留下的），以及 3.0.0、3.0.1 留下的 `Hpler_*` 資料夾（第 2.4 節）。舊名稱的相容在 3.x 一直保留：只多比對一組名稱，成本很低；拿掉之後，舊版留下的資料夾就永遠不會被刪除。
- **安全檢查**：工具以管理員權限執行，刪錯會造成無法復原的損失。只刪除同時符合下列條件的資料夾：
  1. 直接位於下載資料夾底下
  2. 名稱以 `Helper_` 開頭，或以 `Hpler_` 開頭（3.0.0、3.0.1 建立的）
  3. 有和名稱同一組的標記檔：`Helper_` 對 `.helper_staging`，`Hpler_` 對 `.hpler_staging`。不是同一組的（例如 `Helper_*` 裡只有 `.hpler_staging`）不刪除：工具從來不會建立這種資料夾
  4. 不是資源資料夾，也不在資源資料夾裡面
- 目錄連結（junction）只刪除連結本身，不刪除它指向的內容（Python 3.8 起 `shutil.rmtree` 的行為，由整合測試確認）。

**容量與時間**：以真實設定全選為例，SampleDeskTool、SampleDeskFiles 設為不先複製時約需複製 18.2 GB；全部都複製則約 48 GB。複製時間取決於資源資料夾所在位置（隨身碟、網路磁碟）的讀取速度。路徑長度：真實資料最長的相對路徑是 114 個字元，加上暫存資料夾的路徑仍在 Windows 260 個字元的限制內。

---

## 8. 日誌（FR-50、FR-52～FR-54）

- **位置**：`<桌面>\QT_TOOL_LOGS\Helper_<模式>_<YYYYMMDD_HHMMSS>.log`（3.0.1 以前是 `Hpler_`，舊的日誌留在原處，見第 2.4 節）。
  - 桌面路徑用 Windows 的已知資料夾 API（`SHGetKnownFolderPath`）取得（DD10）。Windows 11 開啟 OneDrive 備份桌面時，實際的桌面在 `OneDrive\Desktop`，用 `使用者資料夾\Desktop` 會寫到看不見的位置。
- **每輪一個檔案**：每次執行建立一個專屬的 logger 和 FileHandler，結束時關閉。不使用 `logging.basicConfig`，所以同一次開啟執行多輪也不會寫錯檔案。
- **內容**（FR-54）：日誌要足以事後判斷每個項目做了什麼、為什麼失敗。依時間順序寫入下列區段：

  | 區段 | 內容 |
  |---|---|
  | 開頭 | 工具版本、電腦名稱、Windows 版本與組建、使用者、是否為管理員、資源資料夾、暫存資料夾、模式、逾時設定 |
  | 問題清單 | 啟動時的問題清單（FR-20）；沒有問題時寫「無」 |
  | 勾選的項目 | 依執行順序列出 `id`、名稱、是否先複製 |
  | 複製 | 每個項目的來源、目的地、檔案數、大小、耗時；失敗時列出失敗的檔案與原因 |
  | 執行 | 每個項目的完整命令列、工作目錄、開始與結束時間、結束碼、狀態、耗時、解碼後的**完整**輸出（不截斷，DD17） |
  | 刪除 | 刪除的資料夾；刪不掉的檔案與原因 |
  | 結尾 | 成功、失敗、逾時、無法啟動、複製失敗的數量；失敗項目清單；總耗時 |
  | 非預期錯誤 | 發生時立刻寫入完整的錯誤堆疊（traceback） |

- **立即寫入**：每一筆紀錄寫入後立刻 flush（`logging.FileHandler` 的預設行為），工具異常結束時，日誌仍保留到最後一刻的內容。
- **編碼**：UTF-8。
- **異常保護**：日誌建立失敗時，記錄的原因會顯示在對話框上，執行按鈕恢復可用（FR-53）。
- 「日誌資料夾」按鈕以 `os.startfile` 開啟同一個資料夾（FR-52）。

---

## 9. 介面（FR-30～FR-36）

沿用 2.0 的版面：標題列、兩個分頁、按鈕列、狀態列、免責聲明（FR-30、FR-31、FR-33、FR-35）。3.0 的變更：

| 項目 | 2.0 | 3.0 |
|---|---|---|
| 系統設定的分類 | 程式寫死兩個區塊 | 依 XML 的 `<category>` 動態產生（FR-32） |
| 勾選狀態 | 以名稱為鍵，同名項目會互相覆蓋 | 以 `id` 為鍵 |
| 執行中的進度條 | 顯示固定的百分比（10、30、50…），並非真實進度 | 執行中顯示「不確定」模式的動畫，完成時填滿，旁邊顯示狀態文字（DD9、FR-34） |
| 問題清單 | 沒有 | 啟動時顯示（FR-36、第 6.3 節） |
| 項目狀態 | 等待中、執行、成功、失敗 | 加上「複製中」「複製失敗」（FR-46、FR-47） |
| 完成對話框 | 成功與失敗的數量 | 加上刪不掉的檔案（FR-48） |
| 字型、顏色、產品名稱 | 寫死在 20 多處 | 集中為檔案開頭的常數，產品名稱與版本號取自 `hpler/__init__.py` |

---

## 10. 權限（FR-01、FR-02）

**打包後（使用者實際執行的方式）**：`helper.spec` 加上 `--uac-admin`，在執行檔裡宣告「需要系統管理員權限」（DD1）。

- Windows 會在程式啟動**之前**跳出 UAC：同意就以管理員身分執行（FR-01）；按「否」程式就不會啟動（FR-02）。
- 程式啟動後一定已經有管理員權限，不需要再檢查或詢問。2.0 在按「開始執行」時的提權詢問，3.0 移除（FR-03 已刪除）。

**直接執行 .py 時（只用於開發）**：執行檔的宣告不會生效，所以保留程式內的提權：

1. 不是管理員時，以 `ShellExecuteW(…, "runas", …)` 重新啟動自己。
2. 回傳值大於 32 代表成功，目前的行程結束；小於等於 32 時顯示原因後結束。
3. 傳遞參數用 `list2cmdline([主程式的絕對路徑] + sys.argv[1:])`，修正 2.0 路徑含空白時會被斷開的問題。

---

## 11. 轉換工具（FR-21）

`python tools/ini2xml.py <2.0 資源資料夾> <輸出資料夾> [--no-copy-first id,id…]`

**輸出**：輸出資料夾必須是新的或空的（不覆蓋任何檔案），裡面有 `software.xml`、`system_tasks.xml`、兩個 XSD、`tasks\<id>.cmd`，以及轉換報告 `ini2xml_report.txt`。軟體子資料夾不複製：把這些檔案放進原本的資源資料夾即可。

| 2.0 INI | 3.0 輸出 |
|---|---|
| `[settings] timeout` | 兩個 XML 根元素的 `timeout` |
| `[settings] base_path` | 不轉換；不是 `.` 時列入報告（DD7） |
| `[settings] log_folder` | 不轉換：2.0 沒有使用這個設定，日誌一律寫到桌面（第 8 節）；有設定時列入報告 |
| `[software_xxx]` | `<item id="software_xxx">`；名稱不符合 `id` 規則時，轉成小寫並把不允許的字元換成 `_`，列入報告 |
| `name`、`subfolder`、`executable`、`args` | `<name>`、`<folder>`、`<executable>`、`<args>` |
| `[power_xxx]`／`[security_xxx]` | 放進 `power`／`security` 分類；分類名稱使用 2.0 介面上的文字 |
| `name = 名稱, 說明` | 以第一個逗號切成 `<name>` 與 `<description>`（和 2.0 相同） |
| （INI 沒有對應的設定） | `copyFirst` 不寫，使用預設值 `true`。會自己把檔案複製到桌面的工具，以 `--no-copy-first` 列出它們的 `id`，寫成 `copyFirst="false"`（DD14） |
| `commands = a \| b`（含多行） | `tasks\<id>.cmd`，每條指令一行，套用「全部跑完」範本，和 2.0 的行為相同 |
| 2.0 本來就不讀的段落與項目 | 不轉換，列入報告：不是 `software`、`power_`、`security_` 開頭的段落；沒有 `executable` 的軟體；沒有 `commands` 的任務 |

**讀取 INI**：使用和 2.0.1 相同的讀取方式（相同的插值規則、`utf-8-sig`），確保讀到的內容和 2.0.1 執行時一致。

**命令列模式改成批次檔模式**：2.0 用 `cmd /c 指令` 執行（命令列模式），轉進 .cmd 檔後是批次檔模式，兩者對 `%` 的處理不同（T40 在 Windows 11 上實測）：

| 寫法 | 命令列模式 | 批次檔模式 | 轉換方式 |
|---|---|---|---|
| `for %i in (…)` 的迴圈變數（含 `%~ni` 等修飾） | 迴圈變數 | 錯誤 | 改成 `%%i` |
| 不屬於 `%名稱%` 的 `%`（例如 `50%`、`%%`） | 原樣保留 | 被吃掉 | 每個都改成 `%%` |
| `%名稱%` 環境變數（含 `%名稱:~0,3%`） | 已定義：展開；未定義：原樣保留 | 已定義：展開；未定義：變成空字串 | 保留，列入報告 |

轉換時由左到右掃描，和命令列模式的解析方式相同：先看是不是迴圈變數，再看是不是 `%名稱%`（名稱以英文字母或底線開頭，例如 `%ProgramFiles(x86)%`），其他的 `%` 都是一般字元。

**.cmd 檔**：以 Big5（cp950）、CRLF 存檔（第 4.4 節）。每一步寫成 `指令|| set "FAILED=1"`，`||` 前面不留空白：範本裡的 `指令 || …` 會讓程式收到的命令列結尾多一個空白，和 2.0 不同（T41 以替身程式實測；`set X=1 ||` 會把空白存進變數）。

**轉換報告**：列出所有需要人工確認的地方，包括：
- 含有 `%` 的指令，以及每個 `%` 的轉換方式
- 使用 `wmic` 的指令
- 無法以 Big5 儲存的字元（以 `?` 代替，必須人工修改）
- `id` 被改名的項目
- 沒有轉換的段落與項目、`base_path`、`log_folder`、`timeout` 不是整數
- 2.0 資源資料夾裡找不到的執行檔
- 讀回比對的結果

**驗證**：把轉換後的 XML 用 `config.load` 讀回來，和原 INI 的內容逐欄比對；.cmd 檔裡的指令也逐行比對。輸出資料夾沒有軟體子資料夾，讀回時在暫存資料夾放同名的空檔案代替執行檔。每個產生的 .cmd 都要在 Windows 上實際執行一次（T41）。

**結束代碼**：0 = 轉換完成（報告裡仍可能有需要人工確認的項目）；1 = 無法轉換，或讀回比對不一致；2 = 參數錯誤。

---

## 12. 建置、部署與安全（NFR-01、NFR-02、NFR-07、NFR-08）

| 項目 | 設計 |
|---|---|
| 打包 | PyInstaller `--onefile --uac-admin`，設定寫在 repo 的 `helper.spec`；只出 x64（C-02） |
| Python | 3.12 x64（DD11） |
| 相依套件 | Pillow（顯示 png、jpg 圖示）；版本鎖定在 `requirements.txt` |
| 執行檔資訊 | 圖示（`assets/helper_icon.ico`）、產品名稱與版本號（取自 `hpler/__init__.py`，第 2.4 節）寫進 exe 的檔案內容 |
| 部署 | 把 `helper.exe` 和資源資料夾複製到目標電腦，不需要安裝 Python（NFR-02） |
| 安全 | 部署說明要寫明：資源資料夾只讓系統管理員寫入（共用資料夾設 ACL，或用唯讀媒體）。因為工具會以管理員權限執行裡面的 .cmd 和安裝檔，能寫入的人就能讓自己的程式以管理員權限執行（NFR-07）。執行時的暫存資料夾由工具自己設定為只有系統管理員可寫入（第 7.7 節） |

---

## 13. 錯誤處理原則（NFR-05）

1. **只在邊界捕捉例外**：`run_batch` 的每個項目、介面的每個按鈕事件、`config.load` 的每個項目各包一層。其他地方不捕捉。
2. **捕捉就要留紀錄**：寫進日誌或問題清單，不允許 `except: pass`。
3. **指定例外類型**：捕捉明確的例外類型，不使用不指定類型的 `except:`。只有邊界的最外層可以捕捉 `Exception`，而且必須記錄完整的 traceback。

---

## 14. 測試設計（NFR-04）

| 層級 | 對象 | 環境 | 重點 |
|---|---|---|---|
| 單元 | `paths` | Linux、Windows | 三種佈局、兩種資料夾名稱、找不到時的回傳值、從其他資料夾啟動 |
| 單元 | `config` | Linux、Windows | 第 6.2 節的每一種狀況各一個測試；含 BOM、不含 BOM |
| 單元 | `runner` | Linux、Windows | 以假的程式模擬成功、失敗、逾時、無法啟動、非 0 的成功代碼；參數原樣傳遞；取消與暫停的時機；輸出解碼（OEM 碼頁、UTF-8、同一份輸出兩種都有） |
| 單元 | `staging` | Linux、Windows | 空間不足時不執行任何項目；複製失敗只影響該項目；取消與例外時仍會刪除；只刪除符合第 7.7 節四個條件的資料夾（含 3.0.1 以前的 `Hpler_*`，以及名稱與標記檔不是同一組時不刪）；拒絕刪除資源資料夾；被佔用的檔案列為未刪除 |
| 單元 | `logs` | Linux、Windows | 連續兩輪各自產生檔案；檔名以 `Helper_` 開頭；建立失敗時的處理；第 8 節的每個區段都有寫入；輸出不截斷 |
| 單元 | 產品名稱 | Linux、Windows | `PRODUCT_NAME` 是 Helper；打包設定的版本資訊取自 `PRODUCT_NAME`；視窗圖示優先 `helper_icon.ico`、沒有時用 `hpler_icon.ico`；使用者看得到的文字（介面常數、範本、XSD）沒有 Hpler（第 2.4 節） |
| 單元 | `tools/ini2xml` | Linux、Windows | 對照表的每一列；`%` 的三種轉換；報告內容 |
| 整合 | `runner` + 真的 `cmd.exe` | Windows | .cmd 的結束碼、CRLF、`%` 的處理、cp950 輸出、cp950 與 UTF-8（`chcp 65001`）在同一個 .cmd 的輸出、行程樹的結束 |
| 整合 | `staging` + 真的檔案系統 | Windows | 權限設定後一般使用者無法寫入；目錄連結不會被跟進刪除；執行中的檔案刪不掉時列為未刪除 |
| 整合 | 打包後的 exe | Windows | 打包成功；在沒有安裝 Python 的環境啟動 |
| 架構 | import 規則 | Linux | 只有 `gui` import tkinter；不違反第 2.2 節的依賴方向 |
| 驗收 | 介面、UAC、真實安裝檔 | Windows 11 實機 | 依需求規格的驗收標準逐條執行 |

測試用的範例 XML 與 .cmd 放在 `tests/fixtures/`，不使用真實的安裝檔。

---

## 15. 2.0.x 的設計

2.0.x 維持單一檔案的結構，只做必要的修改。產品名稱維持 Hpler（FR-23 從 3.0.2 起）。

**2.0.1**（重建前已經實作並測試過，實作時從備份還原）：

| 需求 | 實作方式 |
|---|---|
| FR-10～FR-13 | `paths.get_resource_dir()`，依第 3 節 2.0.1 欄位的順序尋找 |
| FR-14 | 錯誤時以 `root.after_idle(root.destroy)` 結束。原本的 `root.quit()` 在主迴圈開始前呼叫沒有作用 |
| FR-15 | 以 `utf-8-sig` 讀取 INI；遇到 `%TEMP%` 這類無法插值的值時保留原文 |
| FR-01、FR-02 | `helper.spec` 加上 `--uac-admin`。重建前程式內的提權處理（含 `ShellExecuteW` 回傳值檢查、按「開始執行」時的詢問）照樣保留：打包後不會執行到，只在直接執行 .py 時使用，3.0 重寫時移除 |

**2.0.2**：

| 需求 | 實作方式 |
|---|---|
| FR-45 | 以 OEM 碼頁解碼，並加上 `errors="replace"`（v1.8 以前第 7.5 節的方式；逐行判斷 UTF-8 從 3.0.1 起） |
| FR-50 | 依第 8 節的方式，每輪建立專屬的 logger |
| FR-53 | 先建立 logger 再進 `try`，例外處理裡一定呼叫 `reset_buttons` |
| FR-41 | **不納入 2.0.2**（DD5 已判斷）：真實 `config.ini` 的參數都沒有反斜線，2.0 的 `shlex.split` 不會改變它們。3.0 依第 7.2 節原樣傳遞 |

---

## 16. 設計決定

| 編號 | 決定 | 理由 | 來源 |
|---|---|---|---|
| DD1 | 打包時加上 `--uac-admin`，由 Windows 在啟動前要求管理員權限 | 少一次重新啟動、沒有參數傳遞的問題、需要測試的情況較少；需求已改為 v1.1 的 FR-02，FR-03 刪除 | 你的指示（10-21） |
| DD2 | `<item>` 加上選填的 `successCodes`，預設 `0` | 安裝程式常以 3010 表示「成功，但需要重新開機」 | 你的指示（10-21） |
| DD3 | 逾時時結束整個行程樹 | 避免殘留的安裝程式讓下一個安裝失敗 | 你的指示（10-21） |
| DD4 | 找不到執行檔的軟體項目不顯示在清單上，列在問題清單 | 清單上只出現能執行的項目，原因寫在問題清單 | 你的指示（10-21） |
| DD5 | 參數原樣傳遞；真實 `config.ini` 只要有參數含反斜線，就在 2.0.2 一併修正 | 2.0 會破壞含反斜線的路徑（已實測） | 你的指示（10-21）；已判斷（10-21）：真實 `config.ini` 的 9 個參數都沒有反斜線，**不納入 2.0.2**，3.0 照常實作 |
| DD6 | 逾時寫在各 XML 根元素的 `timeout`，預設 300 秒 | 每個檔案自己就看得懂；預設值和 2.0 相同 | 設計提出，無異議 |
| DD7 | 3.0 取消 `base_path` | 實際設定都是 `.`；轉換工具遇到其他值時會提示 | 設計提出，無異議 |
| DD8 | 3.0 仍接受 `software.xml` 和執行檔放在同一層 | 和 2.0 一致，成本很低 | 設計提出，無異議 |
| DD9 | 執行中的進度條改用「不確定」模式 | 安裝程式不會回報進度，2.0 的百分比是假的 | 設計提出，無異議 |
| DD10 | 桌面路徑以 Windows 已知資料夾 API 取得 | Windows 11 開啟 OneDrive 備份桌面時，路徑才會正確 | 設計提出，無異議 |
| DD11 | Python 3.12 x64 | 目前已實際測試過的版本 | 設計提出，無異議 |
| DD12 | 輸出逐行解碼：合法的 UTF-8 用 UTF-8，其他行以系統 OEM 碼頁解碼，並加上 `errors="replace"` | `cmd.exe` 以 OEM 碼頁輸出，Python 等工具常固定輸出 UTF-8，兩者可能在同一份輸出裡；開啟 UTF-8 全球語言支援時也正確；解碼一定不會失敗 | 設計提出，無異議；逐行判斷 UTF-8 是 T44 繁中驗收發現亂碼後加上（10-27，v1.9） |
| DD13 | 暫存資料夾放在使用者的「下載」資料夾（以已知資料夾 API 取得），並設定為只有系統管理員可寫入 | 位置依你的指示；下載資料夾一般使用者可以寫入，不設權限會違反 NFR-07 | 位置為你的指示（10-21）；權限為設計提出 |
| DD14 | `<item copyFirst>` 逐項設定是否先複製，預設 `true` | 會自己把檔案複製到桌面的工具（例如 SampleDeskTool，29 GB）不用複製兩次 | 你的指示（10-21，Q8） |
| DD15 | 全部項目結束後才刪除暫存資料夾，不逐項刪除 | 依你的指示；安裝程式結束時，子程式可能仍在使用暫存檔 | 你的指示（10-21） |
| DD16 | 系統設定任務的 .cmd 也先複製到暫存資料夾 | 資源資料夾在網路磁碟時，`cmd.exe` 不接受網路路徑作為工作目錄；.cmd 檔很小 | 設計提出 |
| DD17 | 日誌保留完整輸出，不截斷（原本最多 4,000 字元） | 完整日誌（FR-54）；安裝程式的輸出通常很少 | 你的指示（10-21） |
| DD18 | 產品名稱改為 Helper：使用者看得到的名稱都改，內部的識別名稱（含套件 `hpler/`）不改；清除殘留時也認得舊的 `Hpler_*` 暫存資料夾；視窗圖示沒有 `helper_icon.ico` 時使用 `hpler_icon.ico`（第 2.4 節） | 更正拼字錯誤；從 3.0.0、3.0.1 升級只需換掉執行檔；套件改名會和 `helper.py` 衝突，使用者也看不到 | 改名為你的指示（10-27）；相容與範圍依開發規劃第 4.6 節的建議（10-27） |

---

## 17. 需求追溯

| 需求 | 設計章節 |
|---|---|
| FR-01、FR-02 | 第 10 節（FR-03 已在需求 v1.1 刪除） |
| FR-10、FR-11、FR-12、FR-13 | 第 3 節 |
| FR-14、FR-15 | 第 6 節、第 4.1 節 |
| FR-16 | 第 4.2 節 |
| FR-17 | 第 6.2 節 |
| FR-18 | 第 4.2 節、第 4.5 節 |
| FR-19 | 第 4.3 節、第 4.4 節 |
| FR-20 | 第 6.2 節 |
| FR-21 | 第 11 節 |
| FR-22 | 第 3 節 |
| FR-23 | 第 2.4 節（第 7.7、8、12 節、附錄 A） |
| FR-30、FR-31、FR-33、FR-34、FR-35 | 第 9 節 |
| FR-32 | 第 4.3 節、第 9 節 |
| FR-36 | 第 6.3 節 |
| FR-40、FR-43、FR-44 | 第 7.1 節 |
| FR-41 | 第 7.2 節、第 7.4 節 |
| FR-42 | 第 7.3 節、第 7.4 節 |
| FR-45 | 第 7.5 節 |
| FR-46、FR-47、FR-48 | 第 7.1 節、第 7.7 節 |
| FR-50、FR-52、FR-53、FR-54 | 第 8 節 |
| FR-51 | 第 7.6 節 |
| NFR-01、NFR-02、NFR-08 | 第 12 節 |
| NFR-07 | 第 7.7 節、第 12 節 |
| NFR-03 | 第 4 節 |
| NFR-04 | 第 2.2 節、第 14 節 |
| NFR-05 | 第 6.3 節、第 13 節 |
| NFR-06 | 第 3 節、第 11 節 |
| NFR-09、NFR-10 | 開發規劃（下一份文件） |

---

## 18. 修訂紀錄

| 日期 | 內容 |
|---|---|
| 2026-10-21 | 初版 v0.1 |
| 2026-10-21 | **定版 v1.0**：DD1～DD5 依建議決定；依據改為需求規格 v1.1；第 4.2、5、6.2、7.2、7.6、14 節加入成功代碼；第 10 節改為 `--uac-admin`；第 12、15、16、17 節隨之更新 |
| 2026-10-21 | **v1.1**：依真實 INI（I2）更新。DD5 判斷為不納入 2.0.2（9 個參數都沒有反斜線），第 15、16 節隨之更新；第 11 節加入 `log_folder`（真實 `config.ini` 有這個設定，但 2.0 沒有使用） |
| 2026-10-21 | **v1.2**：依需求規格 v1.2 更新。新增 `staging` 模組與第 7.7 節（暫存資料夾：位置、權限、四個階段、刪除的安全條件）；`<item copyFirst>`（第 4.2 節）；第 7.1 節改為複製、執行、刪除三個階段；第 7.3 節的 .cmd 也先複製；第 8 節改為完整日誌（各區段、不截斷、立即寫入）；新增 DD13～DD17；第 1、2、5、6.2、7.6、9、11、12、14、17 節隨之更新 |
| 2026-10-22 | 勘誤（版本仍為 v1.2，設計不變）：第 7.5 節對 2.0 缺陷的描述，依 T20 在 Python 3.12 的實測更正 |
| 2026-10-22 | **v1.3**：實作 T33 時補充第 6.2 節的檢查：檔案不是 UTF-8 編碼、根元素不對（和「不是合法的 XML」同等處理）；必填欄位重複；`<executable>` 含路徑；不認得的元素或屬性列為 warning（拼錯選填欄位時，該欄位會被忽略，必須提醒） |
| 2026-10-22 | **v1.4**：實作 T46 時補充第 7.7 節：標記檔最後才刪，有檔案刪不掉時保留，下一輪才能再刪 |
| 2026-10-22 | **v1.5**：實作 T35 時補充：第 7.3 節 `cmd.exe` 改為 `/d /s /c ""路徑""`，路徑含空白時也正確；第 7.4 節補上輸出的讀取方式（背景執行緒、最多再等 5 秒）、沒有輸入、不另開視窗 |
| 2026-10-22 | **v1.6**：實作 T40 時補充第 11 節：輸出資料夾的內容與不覆蓋；`--no-copy-first`（取代轉換後人工修改）；2.0 本來就不讀的段落與項目；`%` 的轉換依實測補上兩種模式的差異與掃描方式（`%%` 也要轉換）；報告的完整項目；讀回時以空檔案代替執行檔；結束代碼；`||` 前面不留空白。第 2.1 節：轉換工具依賴 `config`（讀回比對） |
| 2026-10-22 | **v1.7**：實作 T43 時更正第 2.1、2.2 節，和程式一致：`runner` 依賴 `paths`（取得下載資料夾）；`hpler/__init__.py` 每個模組都可以使用；只用於型別標註的 import 不算依賴；tkinter 的規則包含 `PIL.ImageTk`；架構檢查改由 `tests/test_architecture.py` 執行，T03 完成後也在 CI 執行 |
| 2026-10-24 | **v1.8**：T44 驗收時發現暫存資料夾的權限沒有生效（一般權限的程式可以寫入，NFR-07），更正第 7.7 節：整個權限清單換成只有 Administrators 與 SYSTEM、禁止繼承、擁有者改為 Administrators、標記檔也重設；說明 `icacls /inheritance:r` 為什麼不夠 |
| 2026-10-27 | **v1.9**：T44 繁中驗收時發現，固定輸出 UTF-8 的程式（例如以 Python 撰寫的包裝程式），中文在日誌裡變成亂碼。第 7.5 節與 DD12 改為逐行解碼：合法的 UTF-8 用 UTF-8，其他行以 OEM 碼頁；說明誤判的機會與分行的方式。第 14 節加上對應的測試；第 15 節註明 2.0.2 仍是 v1.8 的方式。適用版本改為 3.0.x（3.0.1） |
| 2026-10-27 | **v1.10**：依需求規格 v1.3 的 FR-23，產品名稱改為 Helper（3.0.2）。新增第 2.4 節與 DD18：使用者看得到的名稱都改，內部的識別名稱不改（套件 `hpler/` 改名會和 `helper.py` 衝突）。第 7.7 節：暫存資料夾與標記檔改為 `Helper_`、`.helper_staging`，清除殘留時也刪除 3.0.0、3.0.1 留下的 `Hpler_*`，名稱與標記檔必須是同一組。第 2.3 節：視窗圖示改為 `helper_icon.ico`，沒有時使用 `hpler_icon.ico`。第 8 節日誌檔名、第 12 節版本資訊、附錄 A 範本的註解隨之更新。第 14、15、17 節隨之更新。先前修訂紀錄裡的 Hpler 保留原文 |

---

## 附錄 A：.cmd 範本

兩個範本都只用英文，存檔時不會有編碼問題。

**失敗即停**（後面的步驟依賴前面的步驟時使用）：

```bat
@echo off
rem Helper system task: stop at the first failing step
rem File name: <task id>.cmd / ASCII or ANSI / CRLF line endings
setlocal

powercfg /setactive SCHEME_MIN || exit /b 1
powercfg /hibernate off || exit /b 1

exit /b 0
```

**全部跑完**（各步驟彼此獨立時使用，和 2.0 的行為相同）：

```bat
@echo off
rem Helper system task: run every step, fail if any step failed
rem File name: <task id>.cmd / ASCII or ANSI / CRLF line endings
setlocal
set "FAILED=0"

powercfg /change monitor-timeout-ac 0 || set "FAILED=1"
powercfg /change standby-timeout-ac 0 || set "FAILED=1"

exit /b %FAILED%
```
