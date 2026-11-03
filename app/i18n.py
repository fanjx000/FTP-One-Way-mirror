"""Minimal translation layer (Chinese source strings -> English).

The Chinese text is used as the lookup key so the source stays readable and any
string that has no translation simply falls back to Chinese instead of breaking.
"""
from __future__ import annotations

LANG = "zh"

# Code -> name shown in the selector.  Names are intentionally NOT translated.
LANGUAGES = [("zh", "中文"), ("en", "English")]

_DEFAULT_LANG = "zh"

EN: dict[str, str] = {
    # ---------------------------------------------------------------- shell
    "FTP 单向同步": "FTP One-Way Sync",
    "把选定的 Windows 文件夹 / 文件镜像到 FTP 服务器":
        "Mirror selected Windows folders / files to an FTP server",
    "文件": "File",
    "工具": "Tools",
    "帮助": "Help",
    "打开数据目录": "Open data folder",
    "退出": "Exit",
    "服务器设置…": "Server settings…",
    "测试连接": "Test connection",
    "关于": "About",
    "在浏览器中打开配置目录": "Open the config folder",
    # ---------------------------------------------------------------- header
    "就绪": "Ready",
    "连接中": "Connecting",
    "已连接": "Connected",
    "连接失败": "Connection failed",
    "预览中": "Previewing",
    "同步中": "Syncing",
    "正在取消": "Cancelling",
    "完成": "Done",
    "失败": "Failed",
    "已取消": "Cancelled",
    "未配置": "Not configured",
    "未配置 · 点击右侧“服务器设置”": "Not configured · use “Server settings”",
    "服务器": "Server",
    "服务器设置": "Server settings",
    # ---------------------------------------------------------------- jobs
    "同步任务": "Sync jobs",
    "启用": "On",
    "本地路径": "Local path",
    "FTP 目标目录": "FTP target folder",
    "最近同步": "Last sync",
    "＋ 文件夹": "＋ Folder",
    "＋ 文件": "＋ File",
    "编辑": "Edit",
    "移除": "Remove",
    "打开本地": "Open local",
    "尚未同步": "Never synced",
    "勾选后参与本次同步": "Checked jobs take part in the next run",
    "最近一次成功运行的时间": "Time of the last successful run",
    # ---------------------------------------------------------------- detail
    "文件明细": "Files",
    "运行日志": "Log",
    "搜索路径…": "Search paths…",
    "只看变更": "Changes only",
    "清空": "Clear",
    "复制全部": "Copy all",
    "复制": "Copy",
    "—": "—",
    # ---------------------------------------------------------------- footer
    "准备就绪 · 添加任务后点击“仅预览”或“开始同步”":
        "Ready · add a job, then “Preview only” or “Start sync”",
    "仅预览": "Preview only",
    "开始同步": "Start sync",
    "取消": "Cancel",
    "允许大批量删除": "Allow bulk delete",
    "当远端需要删除的条目超过保护阈值时，勾选此项才会真正删除":
        "Bulk deletions above the safety threshold only happen when this is checked",
    "正在取消，等待当前文件传输结束…": "Cancelling, waiting for the current transfer…",
    "连接失败：": "Connection failed: ",
    "正在连接": "Connecting to",
    # ---------------------------------------------------------------- columns
    "相对路径": "Relative path",
    "大小": "Size",
    "本地修改时间": "Local modified",
    "动作": "Action",
    "状态": "Status",
    "远端大小": "Remote size",
    "上次同步": "Last synced",
    "说明": "Note",
    # ---------------------------------------------------------------- actions
    "新增上传": "Upload (new)",
    "更新上传": "Upload (changed)",
    "删除": "Delete",
    "创建目录": "Create folder",
    "已同步": "In sync",
    "错误": "Error",
    "待处理": "Pending",
    "进行中": "Running",
    "已跳过": "Skipped",
    "远端多余项（已禁用删除）": "Extra on server (delete disabled)",
    "受保护，未删除": "Protected, not deleted",
    "已删除": "Deleted",
    "目录非空，未删除": "Folder not empty, not deleted",
    "本地文件已消失": "Local file disappeared",
    # ---------------------------------------------------------------- dialogs
    "设置": "Settings",
    "保存": "Save",
    "确定": "OK",
    "协议": "Protocol",
    "端口": "Port",
    "用户名": "User name",
    "密码": "Password",
    "显示": "Show",
    "留空表示匿名登录": "Leave empty for anonymous login",
    "字符编码": "Character encoding",
    "UTF-8（推荐）": "UTF-8 (recommended)",
    "GBK（部分国产 FTP）": "GBK (some Chinese servers)",
    "超时": "Timeout",
    "并发": "Concurrency",
    "同时上传的文件数（连接数），1~8": "Parallel uploads (connections), 1~8",
    "被动模式（PASV，推荐）": "Passive mode (PASV, recommended)",
    "校验证书（自签名证书请勿勾选）": "Verify certificate (leave off for self-signed)",
    "例如 192.168.1.10 或 ftp.example.com": "e.g. 192.168.1.10 or ftp.example.com",
    "秒": "s",
    "同步选项": "Sync options",
    "排除规则": "Exclusions",
    "常规": "General",
    "界面语言": "Language",
    "语言更改将在下次启动时生效": "The language takes effect immediately",
    "删除远端多余的文件/文件夹（单向镜像，保持与本地一致）":
        "Delete files/folders on the server that no longer exist locally (one-way mirror)",
    "上传后把修改时间同步到 FTP（下次对比更快）":
        "Copy the modified time to the FTP server after upload (faster next run)",
    "大批量删除保护：单次删除超过阈值时先跳过":
        "Bulk-delete guard: skip the deletion when it exceeds the threshold",
    "删除比例超过": "Delete more than",
    "且不少于": "and at least",
    "传输失败自动重试": "Retry failed transfers",
    "次": "×",
    "跟随符号链接 / 目录联接（默认关闭，避免循环）":
        "Follow symlinks / junctions (off by default to avoid loops)",
    "跳过隐藏文件与文件夹": "Skip hidden files and folders",
    "不下载 OneDrive 未缓存的云端文件（这些文件将不会上传）":
        "Do not download OneDrive cloud-only files (they will not be uploaded)",
    "始终以 Windows 侧为准单向覆盖 FTP；首次建议先“仅预览”。":
        "Windows is always the source; “Preview only” first is recommended.",
    "每行一个通配符，匹配文件名或相对路径（不区分大小写），如 ~$*、*.tmp":
        "One wildcard per line, matched against the name or relative path "
        "(case-insensitive), e.g. ~$* or *.tmp",
    "Thumbs.db\\n~$*": "Thumbs.db\\n~$*",
    "添加文件夹": "Add folder",
    "添加文件": "Add file",
    "编辑同步任务": "Edit sync job",
    "本地文件夹": "Local folder",
    "本地文件": "Local file",
    "浏览…": "Browse…",
    "浏览远端…": "Browse remote…",
    "备注名称": "Label",
    "可选，便于识别": "Optional, for easier recognition",
    "启用此任务": "Enable this job",
    "远端目录会自动创建；本地文件夹结构会原样复制到该目录下。":
        "The remote folder is created automatically; the local folder tree is "
        "reproduced inside it.",
    "选择要同步的文件夹": "Choose the folder to sync",
    "选择要同步的文件": "Choose the file to sync",
    "选择 FTP 目标目录": "Choose the FTP target folder",
    "路径": "Path",
    "转到": "Go",
    "上级": "Up",
    "新建文件夹": "New folder",
    "选择此目录": "Use this folder",
    "文件夹名称：": "Folder name:",
    "个": "",
    # ---------------------------------------------------------------- messages
    "请填写服务器地址。": "Please enter the server address.",
    "请先填写服务器地址": "Please enter the server address first",
    "正在连接…": "Connecting…",
    "请选择本地路径。": "Please choose a local path.",
    "路径当前不存在：": "The path does not exist:\n",
    "仍然保存吗？": "\n\nSave anyway?",
    "服务器": "Server",
    "请先配置服务器。": "Please configure the server first.",
    "无法开始": "Cannot start",
    "请先配置并保存 FTP 服务器。": "Please configure and save the FTP server first.",
    "请先添加并启用至少一个同步任务。": "Please add and enable at least one sync job.",
    "源路径不存在": "Source path missing",
    "以下源路径不存在，请先修正：\n": "These source paths do not exist:\n",
    "提示": "Notice",
    "还没有配置 FTP 服务器，现在去配置吗？":
        "No FTP server configured yet. Configure one now?",
    "移除任务": "Remove job",
    "移除任务？\n": "Remove this job?\n",
    "\n\n（不会删除任何文件，FTP 上已同步的内容保持不变）":
        "\n\n(No files are deleted; what is already on the FTP server stays.)",
    "打开": "Open",
    "路径不存在。": "The path does not exist.",
    "正在同步": "Sync in progress",
    "同步正在进行，确定退出吗？": "A sync is running. Quit anyway?",
    "设置已保存。": "Settings saved.",
    "已添加任务：": "Job added: ",
    "打开数据目录": "Open data folder",
    # ------------------------------------------------------------ summaries
    "新增 {n}": "{n} new",
    "更新 {n}": "{n} updated",
    "删除文件 {n}": "{n} files deleted",
    "删除目录 {n}": "{n} folders deleted",
    "新建目录 {n}": "{n} folders created",
    "跳过 {n}": "{n} skipped",
    "失败 {n}": "{n} failed",
    "无变化": "No changes",
    "个文件": "files",
    "个目录": "folders",
    "个任务": "jobs",
    # ------------------------------------------------------------ round 2
    "FTPS（显式 TLS）": "FTPS (explicit TLS)",
    "FTPS（隐式 TLS，990）": "FTPS (implicit TLS, 990)",
    "{total} 个 · 启用 {enabled}": "{total} jobs · {enabled} enabled",
    "切换语言后界面会立即重新加载。": "The window reloads immediately after switching.",
    "OneDrive 的“按需文件”在本机只是占位符，读取时会触发下载。\n"
    "若只想同步已经下载到本地的内容，勾选此项。":
        "OneDrive “Files On-Demand” entries are only placeholders on disk; reading "
        "one downloads it.\nCheck this to sync only what is already on this PC.",
    " 秒": " s",
    " 项": " items",
    " 次": " tries",
    "配置目录：": "Config folder: ",
    "本地 Windows 文件夹 → FTP 服务器的单向镜像工具。":
        "One-way mirror from local Windows folders to an FTP server.",
    "· 只传输新增与修改的文件，未变化的文件零传输":
        "· Only new and changed files are transferred; unchanged files cost nothing",
    "· 本地删除的内容会同步删除到 FTP":
        "· Items deleted locally are deleted on the FTP server too",
    "· 保留完整目录结构，自动创建远端目录":
        "· The folder structure is preserved and remote folders are created automatically",
    "个": "",
    # ------------------------------------------------------------ engine log
    "开始{p0} · 共 {p1} 个任务": "Started ({p0}) · {p1} job(s)",
    "预览（不写入 FTP）": "preview, nothing written",
    "实际同步": "live sync",
    "[失败] {p0}：{p1}": "[FAILED] {p0}: {p1}",
    "[错误] {p0}：{p1}": "[ERROR] {p0}: {p1}",
    "[失败] {rel}：{err}": "[FAILED] delete {rel}: {err}",
    "已取消。": "Cancelled.",
    "结束 · {summary} · 用时 {secs}s": "Done · {summary} · {secs}s",
    " · 传输 {mb} MB": " · {mb} MB transferred",
    "── 任务：{p0}  →  {p1}": "-- job: {p0}  ->  {p1}",
    "[警告] {p0}": "[WARN] {p0}",
    "源为空（0 个条目）": "Source is empty (0 entries)",
    "读取远端目录 {p0} …": "Reading remote folder {p0} …",
    "[信息] 远端列举方式：{p0}": "[INFO] remote listing mode: {p0}",
    "[提示] 已通过 MDTM 补齐 {p0} 个远端时间戳":
        "Resolved {p0} remote timestamps via MDTM",
    "[提示] 远端目录不存在，将自动创建：{p0}":
        "Remote folder does not exist yet, it will be created: {p0}",
    "目标为 FTP 根目录，删除会作用在服务器根目录下":
        "Target is the FTP root: deletions apply to the server root",
    "[预览] 待上传 {up} 个文件（{mb} MB）、待删除 {d} 项、待建目录 {mk} 个":
        "[PREVIEW] {up} file(s) to upload ({mb} MB), {d} item(s) to delete, "
        "{mk} folder(s) to create",
    "创建远端目录（{p0} 个）…": "Creating remote folders ({p0}) …",
    "上传 {p0} 个文件…": "Uploading {p0} file(s) …",
    "删除远端多余项（{p0} 个）…": "Deleting {p0} extra remote item(s) …",
    "任务完成：{p0} → {p1}": "Job finished: {p0} -> {p1}",
    "对比本地与远端 …": "Comparing local and remote …",
    "[提示] 远端有 {p0} 项本地已不存在，但“删除远端多余项”未启用":
        "[INFO] {p0} remote item(s) no longer exist locally, but "
        "“delete extras” is disabled",
    "需删除 {n}/{total} 项，超过安全阈值 {pct}%，已跳过删除。"
    "请先用“仅预览”确认，再勾选“允许大批量删除”后重试。":
        "Deleting {n}/{total} items exceeds the {pct}% safety threshold - "
        "skipped. Run “Preview only” first, then tick “Allow bulk delete”.",
    "对比结果：新增 {new} · 更新 {upd} · 删除 {d} · 跳过 {skip} · 建目录 {mk}":
        "Diff: {new} new · {upd} changed · {d} delete · {skip} unchanged · "
        "{mk} folder(s) to create",
    "[提示] 条目过多（{p0}），明细仅显示 {p1} 条变更":
        "[INFO] too many entries ({p0}); showing only {p1} change(s)",
    "[错误] 无法创建目标目录 {p0}：{p1}": "[ERROR] cannot create target folder {p0}: {p1}",
    "[错误] 创建目录失败 {p0}：{p1}": "[ERROR] failed to create folder {p0}: {p1}",
    "{n} 个远端目录创建失败，其下的文件将无法上传"
    "（常见原因：名称含服务器不支持的字符、路径过长、或该目录没有写权限）":
        "{n} remote folder(s) could not be created, so files inside them cannot "
        "be uploaded (usual causes: characters the server rejects, path too long, "
        "or no write permission)",
    "[警告] 目录未删除 {p0}（可能非空）": "[WARN] folder not removed {p0} (not empty)",
    "{n} 个文件因父目录创建失败而跳过，未逐个尝试上传":
        "{n} file(s) skipped because their parent folder could not be created",
    "{n} 个文件上传失败，正在改用单连接依次重试"
    "（部分服务器不支持并发上传，或限制了同时连接数）":
        "{n} upload(s) failed - retrying one at a time on a single connection "
        "(some servers cannot handle parallel uploads)",
    "单连接重试全部成功：该服务器不支持并发上传，后续任务已自动改为单连接"
    "（建议在设置里把“同时上传的文件数”设为 1）":
        "Single-connection retry succeeded: this server does not support parallel "
        "uploads. Remaining jobs now use one connection (better: set "
        "“parallel uploads” to 1 in the settings)",
    "连续 {n} 个文件都返回同一个错误，已停止本次上传以免浪费时间：{err}":
        "{n} files in a row returned the same error - stopping this upload: {err}",
    "未知错误": "unknown error",
    "失败明细": "Failure details",
    " 等 {n} 个": " and {n} more",
    "    可能原因：": "    likely cause: ",
    "{msg}（{n} 个文件）": "{msg} ({n} file(s))",
    "上传失败": "upload failed",
    "父目录创建失败：": "parent folder could not be created: ",
    "没有启用的同步任务，请先添加源文件夹。":
        "No enabled jobs - add a source folder first.",
    "[链接]": "[link]",
    "连接": "connection",
    "摘要": "summary",
    "异常": "error",
    "警告": "WARN",
    "信息": "INFO",
    "提示": "INFO",
    "未配置 FTP 服务器地址": "No FTP server address configured",
    "无法解析主机名：": "Cannot resolve host: ",
    "连接超时：": "Connection timed out: ",
    "服务器拒绝连接：": "Server refused the connection: ",
    "登录失败：": "Login failed: ",
    "TLS 握手失败：": "TLS handshake failed: ",
    "网络错误：": "Network error: ",
    "未连接": "not connected",
    "已连接": "connected",
    "未知": "unknown",
    "该服务器要求路径加引号，已自动切换":
        "This server requires quoted paths - switched automatically",
    "服务器的 MLSD 未返回文件大小，改用 LIST 解析":
        "MLSD returned no file sizes - falling back to LIST",
    "服务器不支持 MLSD（{p0}），改用 LIST 解析":
        "Server does not support MLSD ({p0}) - falling back to LIST",
    "MLSD 临时失败，改用 LIST 解析": "MLSD failed temporarily - falling back to LIST",
    "服务器不支持 OPTS MLST，改用 MLSD 默认属性":
        "Server rejects OPTS MLST - using the default MLSD attributes",
    "服务器不支持 MFMT，远端时间戳将保持为上传时间":
        "Server does not support MFMT - remote timestamps stay at upload time",
    "，首页 {p0} 个条目": ", {p0} entries in the home folder",
    "连接成功（列举方式 {p0}）· 当前目录 {p1}":
        "Connected (listing: {p0}) · current folder {p1}",
    "已通过 MDTM 补齐 {n} 个远端时间戳": "Resolved {n} remote timestamps via MDTM",
    "远端目录不存在，将自动创建：": "Remote folder missing, will be created: ",
    # ------------------------------------------------------------ round 3
    "    可能原因：{p0}": "    likely cause: {p0}",
    "[失败] 删除 {rel}：{err}": "[FAILED] delete {rel}: {err}",
    " · 失败 {failed}": " · {failed} failed",
    " · 用时 {s}s": " · {s}s",
    "0 个": "0 jobs",
    "FTPS·隐式": "FTPS·implicit",
    "共 {total} 项 · 变更 {changed}": "{total} items · {changed} changed",
    "完成 · ": "Done · ",
    "已取消 · ": "Cancelled · ",
    "最近一次：": "Last run: ",
    "连接中…": "Connecting…",
    "任务": "Job",
    "创建失败：": "Failed: ",
    "无法读取目录：": "Cannot read the folder: ",
    "{n} 个子目录 · 双击进入，或直接选择此目录":
        "{n} sub-folder(s) · double-click to open, or use this folder",
    "\n\n（不会删除任何文件，FTP 上已同步的内容保持不变）":
        "\n\n(No files are deleted; what is already on the FTP server stays.)",
    "以下源路径不存在，请先修正：\n": "These source paths do not exist://n",
    "移除任务？\n": "Remove this job?\n",
    "\n\n仍然保存吗？": "\n\nSave anyway?",
    "路径当前不存在：\n": "The path does not exist://n",
    "OneDrive 的“按需文件”在本机只是占位符，读取时会触发下载。":
        "OneDrive “Files On-Demand” entries are placeholders only; reading one downloads it.",
    # ------------------------------------------------------------ mkdir / diagnose
    "建目录改用 {mode} 方式（该服务器不接受标准写法）":
        "Folder creation switched to “{mode}” (this server rejects the standard form)",
    "MKD 绝对路径": "MKD absolute path",
    "CWD + 相对名": "CWD + relative name",
    "MKD 引号路径": "MKD quoted path",
    "诊断": "Diagnose",
    "服务器诊断…": "Server diagnostics…",
    "诊断中…": "Diagnosing…",
    "开始服务器诊断 …": "Starting server diagnostics …",
    "诊断结束，报告可直接复制给我。":
        "Diagnostics finished - the report above can be copied as is.",
    "逐项检测服务器的列举/建目录/时间戳能力，结果写入运行日志":
        "Probe listing, folder creation and timestamp support; the result goes to the log",
    # ---- diagnostics report
    "连接与登录": "Connection and login",
    "目录列举": "Directory listing",
    "路径写法": "Path syntax",
    "创建目录": "Folder creation",
    "写入与删除文件": "Writing and deleting files",
    "时间戳命令": "Timestamp commands",
    "结论": "Summary",
    "{host}:{port} 连接成功": "Connected to {host}:{port}",
    "登录成功": "Login OK",
    "但 PWD 失败": "but PWD failed",
    "不支持": "not supported",
    "可用": "available",
    "可用（目录为空）": "available (folder is empty)",
    "可用，{n} 个条目": "available, {n} entries",
    "可用，首行：{line}": "available, first line: {line}",
    "空": "empty",
    "当前目录": "Current folder",
    "（含空格）": " (contains a space)",
    "CWD 到当前目录": "CWD to the current folder",
    "CWD 进入刚创建的目录": "CWD into the freshly created folder",
    "父目录列表可验证新建目录": "Parent listing can confirm a new folder",
    "能在父目录列表中看到": "visible in the parent listing",
    "清理测试目录": "Remove the test folder",
    "无法创建任何目录": "Cannot create any folder",
    "该 FTP 账号可能没有写权限，或服务器不允许 MKD":
        "This FTP account may have no write permission, or the server forbids MKD",
    "MFMT（写入修改时间）": "MFMT (write modified time)",
    "MDTM（读取修改时间）": "MDTM (read modified time)",
    "上传一个测试文件": "Upload a test file",
    "删除测试文件": "Delete the test file",
    "有项目失败": "Some checks failed",
    "{n} 项失败，详见上方的 ✘ 标记": "{n} check(s) failed - see the ✘ marks above",
    "关键能力全部可用": "All key capabilities are available",
    "建目录方式": "Folder creation method",
    "需要改用 {mode}（程序会自动使用）": "needs “{mode}” (used automatically)",
    "同时上传的文件数建议": "Parallel uploads advice",
    "若出现 505/421，请设为 1": "set it to 1 if you see 505/421",
    "[警告] {p0} 个文件因父目录创建失败而跳过，未逐个尝试上传":
        "[WARN] {p0} file(s) skipped because their parent folder could not be created",
    "服务器不支持并发上传，已自动改为单连接":
        "This server does not support parallel uploads - switched to one connection",
    # ------------------------------------------------------------ diagnose v2
    "登录成功 / 当前目录": "Login OK / current folder",
    "当前目录含空格，路径需要正确引用": "The current folder contains a space - paths must be quoted",
    "MLSD 不可用时，程序会自动改用 LIST 解析":
        "When MLSD is unavailable the app falls back to parsing LIST",
    "三种写法都无法创建目录":
        "None of the three MKD forms worked",
    "该 FTP 账号可能没有写权限，或服务器禁止 MKD":
        "This FTP account may have no write permission, or the server forbids MKD",
    "新建目录的可用性": "Usability of the new folder",
    "无法写入文件": "Cannot write files",
    "同步一定失败：请确认该 FTP 账号对此目录有写权限，且磁盘未满":
        "Sync would fail: make sure this FTP account can write here and the disk is not full",
    "准备测试文件": "Prepare a test file",
    "没有测试文件，跳过时间戳检测": "No test file - timestamp checks skipped",
    "清理测试文件": "Remove the test file",
    "目标目录：{path}": "Target folder: {path}",
    "目录存在": "Folder exists",
    "目录不存在": "Folder does not exist",
    "同步时会先自动创建": "it will be created automatically",
    "建子目录": "Create a sub-folder",
    "可以在该目录下建子目录": "can create sub-folders here",
    "写入文件": "Write a file",
    "可以写入文件": "can write files here",
    "该目录不可写": "This folder is not writable",
    "同步到这里的文件都会失败，请给该账号写权限或换个目录":
        "Every upload here will fail - grant write permission or pick another folder",
    "列举方式": "Listing method",
    "已自动改用 LIST 解析": "falls back to LIST parsing automatically",
    "建目录方式": "Folder creation method",
    "标准写法可用": "the standard form works",
    "该服务器要求路径加引号（已自动处理）":
        "this server needs quoted paths (handled automatically)",
    "诊断中断": "Diagnostics interrupted",
    "诊断没有产生任何结果": "Diagnostics produced no output",
    "诊断没有返回任何内容": "Diagnostics returned nothing",
    # ------------------------------------------------------------ diagnose v3
    "同步目标可用": "Sync target is usable",
    "任务的目标目录都能正常写入，同步应可正常工作":
        "every job target folder is writable, so sync should work",
    "目标目录不可写：{path}": "Target folder is not writable: {path}",
    "请给该 FTP 账号写权限，或改用其它目录":
        "grant this FTP account write permission, or choose another folder",
    "FTP 根目录只读": "The FTP root is read-only",
    "这不影响同步：程序只往目标目录写，不会用根目录":
        "this does not affect sync - the app only writes into the target folder",
    # ------------------------------------------------------------ cwd-only servers
    "不切换目录直接写绝对路径": "Write an absolute path without changing directory",
    "绝对路径可直接写入": "absolute paths work directly",
    "写入方式": "Write method",
    "该服务器要求在写入前先切换到目标目录（已自动处理）":
        "this server only accepts writes after switching into the target folder (handled automatically)",
    "该服务器只允许写入当前目录内的文件（程序已自动先切换目录）":
        "this server only writes files inside the current directory (the app switches first)",
    "程序版本 v{ver}": "App version v{ver}",
    # ------------------------------------------------------------ crash safety
    "程序遇到问题": "Something went wrong",
    "刚才的操作出错了，程序已继续运行。":
        "The last action failed, but the app is still running.",
    "详细记录": "Details",
    "查看崩溃日志": "View crash log",
    "同步进行中，语言将在下次启动时生效。":
        "A sync is running - the language will apply on the next start.",
    "崩溃日志已保存到：": "Crash log saved to: ",
    "复制": "Copy",
    "关闭": "Close",
    "界面曾短暂无响应，已自动恢复；如再次发生请打开“查看崩溃日志”。":
        "The window was briefly unresponsive and has recovered. If it happens "
        "again, open “View crash log”.",
    "开发者：": "Owner: ",
    "开发日期：": "Developed: ",
    "联系邮箱：": "Contact: ",
    "（暂无记录）": "(no entries yet)",
}

_ACTIVE: dict[str, str] = {}


def set_language(code: str) -> None:
    global LANG, _ACTIVE
    LANG = code if code in dict(LANGUAGES) else _DEFAULT_LANG
    _ACTIVE = EN if LANG == "en" else {}


def get_language() -> str:
    return LANG


def tr(text: str) -> str:
    """Translate a Chinese source string for the active language."""
    if not text or LANG == "zh":
        return text
    return _ACTIVE.get(text, text)


def trf(text: str, **kwargs) -> str:
    """Translate then format: trf("新增 {n}", n=3)."""
    try:
        return tr(text).format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return tr(text)
