# 版本更新：检查 · 下载 · 覆盖

> 状态：检查 · 下载 · 覆盖安装均已实现并接入 UI · 2026-08-14

---

## 1. 渠道划分（容易搞混，先说清）

| 用途 | 平台 | 地址 |
|---|---|---|
| **代码托管 / 提交 PR** | Gitee | `VioletFizz/rei-per`（即 Fizz/ReiPer） |
| **发布安装包** | GitHub | `SingularDance/kira-remy-official` 的 Releases |

更新检查读的是 **GitHub**，代码提交去的是 **Gitee**。两边不是一个地方。

---

## 2. 实测确认的接口形状

以下全部在 2026-08-13 对真实接口验证过，不是照文档抄的。

**GitHub API（首选路径）**

```
GET https://api.github.com/repos/SingularDance/kira-remy-official/releases/latest
```

一次请求拿到全部所需信息：

```
tag_name  = v1.1.1
body      = ## What's Changed …          ← 直接当 changelog 显示
assets[0] = { name: "Remy_v1.1.1.zip",
              size: 48821272,            ← 下载后核对字节数
              browser_download_url: "https://github.com/…/download/v1.1.1/Remy_v1.1.1.zip" }
```

**302 跳转（兜底路径）**

```
GET https://github.com/SingularDance/kira-remy-official/releases/latest
→ 302  Location: https://github.com/…/releases/tag/v1.1.1
```

从 `Location` 里正则取 tag，一个字节正文都不用下，也不受 API 限流影响。

**下载直链**

```
HEAD https://github.com/…/releases/download/v1.1.1/Remy_v1.1.1.zip
→ 200   Content-Length: 48821272   ← 与 API 的 asset.size 完全一致
```

两者一致这点很重要：说明「下载后核对字节数」这条保护有效，不会误报。

---

## 3. 三个设计选择及理由

### 3.1 用 API，不抓 releases 页面的 HTML

抓 HTML 的话，GitHub 改一次页面结构就废。API 还顺带给了 changelog 和资产大小——这两样抓 HTML 都拿不到，而它们分别用于「更新说明」和「完整性校验」。

### 3.2 下载地址优先用 `browser_download_url`，模板只作兜底

命名模板 `Remy_{tag}.zip` 目前恰好正确（已验证与 API 给的直链完全相同）。但模板是脆的：哪天 release 里的 zip 改名（加平台后缀、换分隔符），拼出来的链接会**静默 404**，用户只看到「下载失败」，排查起来毫无线索。

所以顺序是：API 的 `browser_download_url` → 拿不到资产时才用模板拼。代码里两条路都覆盖了测试。

### 3.3 必须有 302 兜底

未认证的 GitHub API 限流是 **60 次/小时/IP**。每天查一次远远够用，但学校、公司、宿舍这类共用出口 IP（NAT 后面几百人）有可能撞上，那时 API 返回 403。有 302 兜底，功能不中断——代价是这条路拿不到 changelog 和资产大小。

---

## 4. 已实现的模块

### 4.1 `version.py`

```python
VERSION = "1.1.1"
GITHUB_OWNER = "SingularDance"
GITHUB_REPO = "kira-remy-official"
```

单独成文件而不是塞进 `config.py`：打包脚本发版时改这一个文件即可，不用正则替换 `config.py` 里的某一行；且零依赖，任何模块都能安全 import。

**发版三件套必须一致**：`version.py` 的 VERSION、打包产物名、GitHub 上的 tag。不一致会导致用户被反复提示更新一个已装上的版本。

### 4.2 `updater.py` —— 有没有新版本

| 函数 | 职责 |
|---|---|
| `fetch_via_api` | 调 GitHub API，403 限流时返回 None 交给兜底 |
| `fetch_via_redirect` | 从 302 的 Location 解析 tag |
| `fetch_latest_release` | 两条路串起来，API 优先 |
| `parse_api_release` | 把响应当**不可信输入**校验：非 dict、缺 tag_name、限流的 `{"message":…}`、非 https 的下载地址，一律拒绝 |
| `check_for_update` | 节流 / 跳过 / 总开关 / 强制触发的判定 |
| `bubble_phrase` `tray_message` | 提示文案 |

**硬约束**

- 检查更新超时 **5 秒**，任何失败静默降级。GitHub 在国内连不上是常态而非异常
- 版本比较用整数元组。`"1.10.0" < "1.9.0"` 在字符串比较下为真，这是最经典的版本 bug
- 每天最多查一次（`last_check_date`）；支持「跳过此版本」与总开关；**手动触发时全部忽略**
- `attempted_network` 字段告诉调用方是否真发过请求——**只有发过才应写回 `last_check_date`**，否则日期被反复刷新，永远查不到更新

### 4.3 `downloader.py` —— 拿下来并确认完整

| 函数 | 职责 |
|---|---|
| `download` | 分块下载、进度回调、可取消、大小核对 |
| `verify_zip` | `is_zipfile` + `testzip()` 逐条校验 CRC |
| `safe_extract` | 跳过用户数据、拒绝路径穿越、自动剥顶层目录 |

**四条硬约束**

1. **超时与检查更新是两套**。安装包 47MB，整体不能设死超时；用的是「每次读取超时」，只要还在收数据就不放弃
2. **先写 `.part` 再改名**。中途失败或取消时，目标路径上不会留下一个看起来完整的坏包。改名是原子操作
3. **解压前必须校验**。断掉的 zip 解压会写入半个文件，而用户此时已关掉旧程序——等于**变砖**。所以先核对字节数，再 `testzip()`
4. **绝不覆盖用户数据**。受保护清单：`config.json`（含 API Key）、`chat_log.txt`、`notes.txt`、`stats.json`、`shortcuts.json`、`music_history.jsonl`。仅在目标已存在时跳过——全新安装应拿到包里的默认配置

**为什么不用 `ZipFile.extractall()`**：安装包来自网络，属于不可信输入。压缩包条目名可以是 `../../x` 或绝对路径（zip slip），`extractall` 在旧版 Python 上会照写。另外还需要逐条决定跳过与否。

**自动剥顶层目录**：发布包通常有一层 `Remy_v1.1.1/`。不剥会解出嵌套目录，更新等于没生效。所有条目共享同一顶层目录时自动剥掉，否则保留。

### 4.4 `self_update.py` —— 覆盖安装 + 重启

| 函数 | 职责 |
|---|---|
| `is_frozen` / `install_dir` / `exe_path` | 判断打包态、定位安装目录与 exe（`sys.executable`） |
| `prepare_update` | `safe_extract` 解压到 staging，再剔除受保护文件 |
| `write_apply_script` | 生成覆盖安装的 `.bat` 脚本 |
| `launch_apply_script` | 分离启动 `.bat`，父进程退出后继续跑完 |
| `apply_update` | 串联以上三步，仅打包态可用 |

**为什么用 `.bat`**：Windows 上运行中的 exe 被锁，必须由独立进程替换。`.bat` 零依赖、不改打包流程（对比独立 updater.exe 要多产出一个 `--windowed` 产物）。流程：等旧程序退出 → `robocopy` 覆盖（自带锁文件重试）→ 清理 → `start /D` 以安装目录为工作目录重启 → 自删。

**关键点**：`start /D "{install}"` 必须带 `/D`——`config.json` 等数据按当前工作目录读写，不带会让新版跑到临时目录去新建配置。

### 4.5 `make_release.py` —— 生成发布 zip

`pack.bat` 只产出 exe，上传到 GitHub Releases 的 `Remy_v{版本}.zip` 由本脚本生成：

```
python make_release.py
```

- 读 `version.py` 的 VERSION，把 `dist\星夜颂歌-蕾咪！.exe` 压成
  `dist\Remy_v{版本}.zip`，顶层目录 `Remy_v{版本}/`（safe_extract 会自动剥掉）
- 用 Python 的 `zipfile` 写，非 ASCII 名自动带 UTF-8 标志——从源头杜绝
  §4.3 里那个「GBK 无标志 → 乱码 exe」的 bug。**不要再用 Windows
  「发送到压缩文件夹」手打发布包**
- 打包后回读校验：确认 exe 名带 UTF-8 标志、读回后与源名一致，否则报错

发版三件套（VERSION / exe 名 / GitHub tag）的一致性问题见 §4.1。

---

## 5. 测试

```bash
python -m unittest discover -s tests -t .
```

83 个用例。网络与时间全部注入，以下场景无需联网即可覆盖：

| 场景 | 为什么必须测 |
|---|---|
| `1.10.0` vs `1.9.0` | 字符串比较会判错的经典案例 |
| 位数不同（`1.2` 与 `1.2.0`） | 必须相等，不能算新版 |
| GitHub API 返回 403 | 验证自动切到 302 兜底 |
| 响应是 HTML / 非 dict / 缺 tag_name | 远端返回垃圾时不能误报更新 |
| release 没挂附件 | 验证退回命名模板 |
| 资产列表里混着源码包和 checksums.txt | 验证挑包逻辑不取「第一个」 |
| 下载中途断流 / 被取消 | 不留 dest，也不留 `.part` |
| 大小不符 | 拒绝并清理 |
| **zip 被截断** | 下载中断最常见的表现，解压会毁掉安装目录 |
| **压缩包含 `../evil.txt`、`/etc/passwd`、`C:/…`** | 路径穿越必须被拒 |
| **`config.json` 已存在** | 用户的 API Key 绝不能被冲掉 |
| 老 config.json 没有 `update` 段 | 不补齐则「跳过此版本」「每天只查一次」静默失效 |
| `update.enabled` 被写成字符串 | `if not cfg.enabled` 会判错 |

---

## 6. UI 接入（已完成）

形式：启动后蕾咪先用气泡说一句人格化的话，同时发一条 Windows 托盘通知兜底；点托盘通知或走右键菜单才弹详情对话框。既不打断，也不会因为气泡淡出而错过。

| 位置 | 改动 |
|---|---|
| `desktop_pet.py::start_update_check` | 启动后延迟 3 秒在后台线程查（避开欢迎语抢气泡位），结果经 `QMetaObject.invokeMethod` 回主线程，沿用 `call_api` 的既有套路 |
| `desktop_pet.py::_on_update_checked` | 气泡（`bubble_phrase()`）+ 托盘通知（`tray_message()`）双路提示 |
| `desktop_pet.py::on_tray_message_clicked` | 点托盘通知打开详情。`messageClicked` 对所有托盘通知都会触发，用 `_tray_msg_is_update` 区分来源 |
| `desktop_pet.py::show_context_menu` | 新增「🔄 检查更新」（`force=True` 忽略节流与跳过）与「ℹ️ 关于」。**更新入口不再用红点标记**——红点以内存里的 `_latest_release` 为判据，更新后若版本号没变会常亮误导用户，故移除 |
| `dialogs/update_dialog.py` | 版本对比（`vA → vB`）+ changelog（Markdown 渲染）+ 大小 + 进度条 + [立即下载][打开下载页][跳过此版本][稍后]；下载完成后打包态变 [🔄 立即安装并重启] |
| `dialogs/about_dialog.py` | 「关于」弹窗：显示当前版本号（实时读 `version.VERSION`）+ 发布页入口，让用户随时能确认自己跑在哪一版 |
| `config.py` | `default_config` 加 `update` 段；`sanitize_config` 逐键补齐，老用户的 config.json 里没这个键时不补齐会让「跳过此版本」和「每天只查一次」静默失效 |

**样式**沿用项目其余对话框：白底 `rgba(255,255,255,240)` + `#DAAD69` 金边 + 圆角 15，按钮金底黑字，取消类按钮走 `objectName="cancel"` 变灰。

### 几个刻意的处理

- **气泡和托盘都发**：气泡会淡出，用户切走窗口就看不到；托盘通知是兜底
- **手动触发时即便已是最新也给反馈**，否则用户以为点了没反应
- **大小未知时（302 兜底路径）不显示「0 MB」**，进度条转忙碌态
- **下载中「稍后」变成「取消下载」**，取消会清掉临时文件
- **不劫持气泡点击**：`on_bubble_click`（`desktop_pet.py:724`）已被占满——跳过打字机、结束等待。下载入口放托盘通知和右键菜单
- **气泡台词的表情是设计好的**：`UPDATE_PHRASES` 刻意含「哼」「笨蛋」，经 `detect_emotion` 命中 `angry`，蕾咪切生气表情。改台词删掉这些词会让表情变默认开口——不报错但观感不对，`tests/test_updater.py::TestBubbleEmotionAlignment` 钉住了这条链路
- **不再用红点标记更新**：红点以内存里的 `_latest_release` 为判据，属于启动时的一次性缓存；更新后若版本号没跟着变，红点会一直亮、反复提示「需要更新」，反而误导用户。改为在「关于」里实时显示当前版本号，让用户自己对照
- **开发态不触发自动安装**：`self_update.is_frozen()` 为假时没有可替换的 exe，下载完成后退回「打开所在文件夹」手动安装，保证 `python Remy.py` 调试流程不受影响

### 版本号如何在更新后变化

「关于」弹窗实时读 `version.VERSION`。`version.py` **不在** `downloader.PROTECTED_FILES` 里，覆盖安装时会被新包一起替换，所以重启后版本号自然更新。**前提是发版三件套一致**：`version.py` 的 VERSION、打包产物名、GitHub tag（见 §4.1）。若发版时忘了改 `version.py` 就打包，新 exe 仍报旧版本号，就会退化成「明明更新了却一直提示更新」——这是发版流程问题，不是运行时代码能兜住的。

---

## 7. 待做

### 7.1 覆盖安装（已实现，用 `.bat` 更新器）

正在运行的 exe 无法覆盖自己（Windows 文件锁），所以必须分离出一个更新器。已用
`self_update.py` 生成的 `.bat` 实现：

```
主程序：下载 zip → verify_zip → 解压到 staging（safe_extract + 剔除用户数据）
        → 生成 .bat → 分离启动 .bat → 自己退出
.bat：等旧程序退出（timeout 3s）→ robocopy 覆盖（自带重试）
        → 清理 staging 与 zip → start /D 重启新版 → 自删
```

触发方式：下载完成后，对话框按钮变「🔄 立即安装并重启」，用户点一下才执行——避免误关正在做的事。**必须在 Windows 上验证**，开发态（`sys.frozen` 为假）自动退回到手动「打开所在文件夹」。

**已实现 / 未实现的保护**：
- 解压前校验（已实现，`verify_zip` + `safe_extract`）
- 跳过用户数据（已实现，`safe_extract` + `_strip_protected`）
- **覆盖前备份、失败能回滚**（**未实现**）——`robocopy` 若因杀软锁文件等失败，当前行为是照常重启旧版（不比现状更差），但没有「先备份、失败自动还原」的兜底，这是唯一剩余的缺口

### 7.2 已知风险：GitHub 在国内的可达性

47MB 的包从 GitHub 下载，国内可能极慢或直接连不上。这是最现实的问题——用户是中文用户。

现有缓解：检查更新 5 秒超时不影响启动；下载有进度回调和取消。

**尚未决定**：要不要配镜像地址，或在下载失败后引导用户手动下载（`Release.page_url` 字段已经准备好了，就是为这个兜底留的）。这个要产品上拍板。
