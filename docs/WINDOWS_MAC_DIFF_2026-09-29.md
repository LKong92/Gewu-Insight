# Windows 0.1.20 与最新 macOS 源码差异核对

后续更新：用户已要求实施对齐，当前 **0.1.21 已交付并重开原 App**。见 [实施与验收记录](WINDOWS_MAC_PARITY_0.1.21.md)。下文保留更新前 0.1.20 的审计依据。

核对日期：2026-09-29（Asia/Tokyo）。这是源码与既有交付记录审计，不是新的双平台实机验收。

## 1. 结论与版本依据

**Windows 0.1.20 尚未包含 macOS 9 月 10 日后这一轮主要产品更新。差异已经涉及数据模型、文件管理、后台任务与 MCP，不能仅同步界面文件。** Windows 既有的功能与独立修复仍需保留；不能把所有 Git 差异都视为缺失功能。

| 对照项 | 本次核实值 |
| --- | --- |
| Windows 分支 | `codex/windows-preview-0.1.10-20260910` |
| Windows 源码 HEAD | `70fa8a0b86431e26b2a63c0dc02db71fe583f020` |
| 当前运行路线 | `Start Gewu Insight.cmd` → `dist/windows-preview-0.1.20` 外壳 + `.venv` + 本地源码；0.1.19 已卸载 |
| 外壳版本文件检查 | EXE 与 DLL 的 FileVersion 均为 `0.1.20.0`；ProductVersion 为 `0.1.20+1b0ceba795c799ce2986f6dda23ab51ef6afa22e`。该构建标记不能替代当前加载的源码 HEAD |
| Windows 上次已适配的 macOS 检查点 | `9ea2bb3b8160aa931667afc1c412608627f2f473`；AI/MCP 更新在 Windows 0.1.17 同步，之后有 Windows 独立修复 |
| 本次获取的最新远端 macOS | `8a2789512164a42ac066a3cee67548b1328d5056`；提交时间 2026-09-28 17:44:29 +08:00 |
| macOS 产品版本 | `paper_monitor/__init__.py` 标为 `1.0.0` / Build `1`；后续更新需按 SHA 识别，不能只看版本号 |
| macOS 增量范围 | `9ea2bb3..8a27895` 共 **53 个提交**、**255 个变更文件**，含文档、测试、截图和 App 二进制；不是 53 个独立新功能 |
| Python 范围 | 上述增量涉及 `paper_monitor` 下 47 个 Python 文件，新增 32 个 Python 模块；这 32 个新模块目前均不在 Windows 工作树 |
| SQLite 结构声明 | Windows **18** → macOS **22** |
| MCP 适配器与工具定义 | Windows **1.1.0 / 5 项** → macOS **1.5.0 / 24 项**；实际可发现和可调用的工具仍受连接权限限制 |
| Paper Files 类型枚举 | Windows **10 种** → macOS **20 种** |

`git fetch origin main` 只更新了本地远端引用，没有切换、合并或推送分支。审计开始时已有的本地文档改动均保留；`paper_monitor/`、`windows/`、`scripts/` 没有未提交的运行代码改动。

范围限于已推送的 macOS `main`；无法据此判断另一台 Mac 上尚未提交或推送的内容。没有比较两台机器的论文数量、个人设置或 Library 内容，也未读取论文文件。

## 2. 主要差异

下列“未同步”指当前 Windows 源码没有 macOS 的新增实现；“部分已有”指 Windows 已有旧流程或平台替代，但缺少这轮行为。优先级是后续迁移建议，不表示本次发现用户资料已损坏。

| 编号 / 建议顺序 | macOS 当前行为 | Windows 0.1.20 差异 | 主要证据 |
| --- | --- | --- | --- |
| D01 / 优先 | 统一 DOI、arXiv 和稳定 Scholar 身份；并发写入重查；有证据的同作合并保留旧 paper ID / Gewu Key 别名、文件和关联 | **旧身份保护已有，新统一层未同步**。缺少 `paper_identity.py`、标识所有权注册、别名及身份历史；Author Monitor 重复身份与后续标识补全修复尚缺 | `cb16eb6`、`ad7632b`；macOS `docs/PAPER_IDENTITY.md`；Windows `storage.py:27,1813–1981` |
| D02 / 优先 | 更正、撤稿、关注声明、撤回、增补等公告关联原论文；公告 DOI 独立保存，不覆盖论文身份，也不自动成为 Default | **未同步公告关系模型**。Windows 有旧 `correction_notice` 文件分类，但没有公告表、关系证据、Browser/Loader/MCP 共用公告入口 | `8a27895`；`publication_notices.py`、`docs/PUBLICATION_NOTICES.md` |
| D03 / 优先 | 冲突导入保留文件并报告归属；相同论文的完全相同字节跨路径去重，保留多个导入来源；不同版本及批注保留 | **部分旧去重已有，新导入与资源去重未同步**。当前导入器仍可抛出 identity conflict 并中断；缺少完整实时 SHA-256 去重、来源表及串行注册 | `5ac4368`、`bfb55d1`、`263057e`；Windows `importers/inventory.py:1114,1205`；macOS `resource_dedup.py` |
| D04 / 优先 | Paper Files 可 Move to Another Paper / Create Paper from File；所有权、Default、主文件、Associated Files、关联位置一起更新并回滚；空原记录按规则退役 | **未同步新版所有权事务和两个显式命令**。旧内部拖放/添加文件通道不能等同这一模型 | `5ac4368`、`36a8cef`、`93810d4`；`file_reassignment.py`、`file_layout.py`、`file_organize.py` |
| D05 / 优先 | Recycle 操作保护其他 Library/Space/My Publications 的活跃引用；重新收藏可恢复原件位置；目录更名有磁盘 journal 与事务恢复；降低导入、删除和更名开销 | **Windows 回收事务已有，后续跨位置保护、布局和性能更新未同步**。须适配现有 `.lnk`、Shell 回收、跨盘与中断恢复，不能覆盖成 Mac 实现 | `43681d2`、`5701bdd`、`263057e`；`file_placement.py`、`folder_rename.py`、`recycle.py`；Windows `windows_library_recycle.py` |
| D06 / 优先 | 所有 Details / 文件夹 / 整库 / 导入共用 Refresh Info；Quick/Full、持久进度、Pause/Continue/终止 Stop、历史与来源限流；手动 DOI/arXiv 修正以新标识刷新并保留纠正历史 | **旧刷新和 Stop Import 已有，新统一工作流未同步**。缺少四个独立 refresh/job/network/correction 模块和新 UI；不可把已有停止文案误认成持久队列 Stop | `574b2e6`、`94e16fe`、`b1bdd9f`；`metadata_refresh.py`、`metadata_jobs.py`、`metadata_network.py`、`identifier_correction.py` |
| D07 / 优先 | Author Monitor 缓存立即展示、后台更新保留阅读位置；补全按作者范围限量轮转；网络失败自动退避恢复；异常 Scholar 页面不是空结果；持久显示身份冲突、休息和暂停原因 | **未同步这轮后台与恢复改进**。缺少 `author_metadata_work.py`、`author_profile_retry.py`、`scholar_access.py` 及相关 UI；旧 Author Monitor 和冷却机制仍在 | `6a1e1a8`、`fca6f0c`、`6110a80`、`ad7632b`、`b9364b5` |
| D08 / 优先 | MCP 可按授权浏览目录/成员；文件副本有 delivery ID、准确配额、显式释放，可连续读取多个批次 | **未同步**。Windows 有 `get_paper_file`，但无目录枚举、`get_file_delivery_status`、`release_paper_file`；不能把原文件读取整体算成缺失 | `52ec572`、`1888608`；macOS `ai_folders.py`、`mcp_server.py` |
| D09 / 优先 | MCP 可单独授权创建 Space/文件夹、上传与导入、添加附件、补充元数据、独立 Resolve、移动/重命名；持久保存可写范围；精确身份导入复用未收藏 Monitor 记录与合规缓存文件 | **未同步**。Windows 仅有读取与追加分析的三个 scope；缺少写权限 UI、上传暂存、幂等写入、整理接口及最新 Default/身份复用修复 | `2392a9f`、`0c32a5e`、`251a9d9`、`8a27895`；`ai_contract.py`、`ai_uploads.py`、`ai_writes.py`、`ai_organize.py`、`ai_import_identity.py` |
| D10 / 随 MCP | 外部 MCP 写入后，当前 Library/Space/Shortcut 的文件夹、条目和 Paper Files 自动刷新；编辑、选择、滚动和预览保留 | **未同步外部写入感知**。Windows 0.1.19 的下载响应快照刷新已在 0.1.20 保留，但不等于监听外部 MCP 变更 | `6ffb2ec`；`library_live.py`、`ui_server.py` |
| D11 / 优先 | 同一论文下载合并在途请求，独立临时目录避免并发文件覆盖；Science 主文/补充验证、合并组件去重、原始文件名和 First Release 分类正确 | **旧下载/合并和 Nature 修复已有，新并发与 Science 逻辑未同步**。Windows 下载仍使用目标目录下固定 `main.pdf` 等中间名；缺少 `science_pdf.py`、`science_version.py` | `5ac4368`、`dc42c3a`、`3eba6d0`；macOS `docs/MONITOR_DOWNLOADS.md`；Windows `download.py:80` |
| D12 / 原生适配 | 下载型 PDF 在 Browser 原标签预览；保留原 POST/会话；已加载主 PDF/嵌入 PDF 可 Use Loaded PDF；以当前文档绑定原始字节，不静默重发请求；可明确选择现有 Gewu Key | **旧内联 PDF、Get PDF 和原生 POST 弹窗已有，新字节复用/预览/身份审阅未同步**。Windows 普通下载仍弹 Save 对话框；捕获用隐藏 WebView 重新获取，64 MiB / 90 秒；Mac 捕获上限为 128 MiB，下载与解析超时分开 | `6a1e1a8`、`c578d63`；Windows `Program.cs:311–321`、`BrowserCapture.cs:112–122`；macOS `docs/BROWSER_PDF_PREVIEW.md` |
| D13 / 界面 | Markdown YAML/分析来源折叠属性、宽表与代码横向滚动、读文件与 worker 并行、经文件版本复核的缓存；离线 TeX 数学公式 | **基础 Markdown 预览已有，上述增强未同步**。Windows worker 无 js-yaml / KaTeX 与数学解析 | `789728a`、`6ffb2ec`；`markdown_preview_worker.js`、新增 vendor 文件 |
| D14 / 界面 | Library/Space/Shortcut 表头可按 Title/Authors/Year/Journal/Time added 双向排序；设置默认 Add to Library 目标；服务端与前端模糊匹配一致；精简导航与面包屑 | **旧 Table View、搜索和排序已有，新列排序、默认目标及匹配改进未同步**。Windows 当前排序仍为 Name / Modified Time，无 Time added | `b5555dc`、`43681d2`、`a39ce58`、`51e8415`；`search_matching.py`、`library_destination.py`；Windows `ui_server.py:37621–37626` |
| D15 / 界面与原生 | Paper Files 整列含滚动区/空白/控件支持投递；所有权移动与普通导入区分；拖放手势去重；Author Monitor/My Publications 排序反馈修正 | **Windows 原生拖入拖出已有，新整列路由与所有权手势修复未同步**。AppKit 专用 destination 需用 Windows 等价机制实现，不能直接移植 | `f4ff5a4`、`8e3b6f1`、`36a8cef`、`b1bdd9f`、`b57aebc`、`b9364b5` |
| D16 / 界面与原生 | Loader/刷新日志 Show in Library；点击后主窗口定位、任务继续；导入/刷新/下载状态独立；Default 排首且键盘顺序一致；Browser favicon 与标题居中 | **独立 Loader 与 Browser 保存后的 Show in Library 已有，新增日志导航与状态/UI 细节未同步** | `5ac4368`、`b328725`、`7825b41`、`e833ce2`；需扩展 Windows `LoaderWindow.cs` 桥接 |
| D17 / 原生验收 | workspace 渲染进程异常退出时，用原私有会话有限重试恢复，不重放资料操作 | **Windows 后端服务崩溃恢复已有，不能等同 workspace 渲染进程恢复**。当前 Windows C# 未见对应 `ProcessFailed` 处理；需单独设计与验收 | `b5555dc`；Windows `ServiceRecovery.cs` 与 `Program.cs` |
| D18 / 随功能更新 | Literature Data Source 设置命名、Help 联系方式/官网、1.0.0 指南、新分类与授权文案、第三方声明和引用信息 | **未同步本轮内容**。本地 Windows 指南仍是其既有 Preview/源码路线，不能直接替换成 Mac 截图手册；新许可证和 notices 也有文件差异 | `1a254a6`、`d925cc0`、`b6d205d`、`ca3cd11`、`8153188`、`ad38f86` 等 |

新增十种文件分类：`perspective`、`news_and_views`、`summary`、`analysis`、`source_data`、`source_code`，以及 `retraction_notice`、`expression_of_concern`、`withdrawal_notice`、`addendum`。Windows 已能写入带分类说明的分析 Markdown；这里的差异是完整 Paper Files 类型模型及相关选择界面。

## 3. 数据与 MCP 的具体迁移边界

| schema | macOS 增量 | 对后续 Windows 适配的含义 |
| --- | --- | --- |
| 19 | 标识所有权、paper ID / Gewu Key 别名、身份历史 | 所有读写入口要使用规范身份；保留旧 Key、授权与分析幂等收据 |
| 20 | `resource_import_sources`、`resource_duplicate_archive` | 多次导入的来源记录与资源身份分离；相同字节去重不能删除批注或不同版本 |
| 21 | `ai_write_requests`、`ai_uploads`、`write_roots_json` | 新写入能力需单独授权；升级不扩大已有连接权限 |
| 22 | `publication_notices`、`publication_notice_files` | 公告信息和研究论文身份分离；保留原论文与其文件 |

Mac 当前最终实现**不在普通启动时扫描、合并或整理整个历史 Library**。`93810d4` / `bfb55d1` 后，`ab78638` 撤销了自动维护，`4000d98` 只恢复有 journal 的中断移动恢复。后续移植应采用最终状态，不能把中途被撤销的自动维护重新带入 Windows。结构升级与历史资料修复是不同操作。

Windows 当前五个 MCP 工具为：`search_papers`、`get_paper`、`read_paper`、`save_analysis`、`get_paper_file`。Mac 新增十九项：

- 目录：`list_folders`、`list_folder_papers`。
- 读取副本：`get_file_delivery_status`、`release_paper_file`。
- 上传暂存：`upload_file`、`get_upload_status`、`release_upload`。
- 创建与导入：`create_space`、`create_folder`、`import_paper`、`import_file`、`add_paper_file`。
- 元数据：`update_paper_metadata`、`resolve_paper`、`get_resolve_status`。
- 整理：`move_folder`、`rename_folder`、`move_file`、`rename_file`。

Mac 的导入要求 AI 提供元数据，导入本身不触发 Resolve；已有 Default 的手动选择保留。写权限按操作和 Library/Space 范围分别控制，不包含 My Publications 写入，也不授权覆盖文件内容。Windows 的只读副本 DACL、UTF-8 STDIO 与重启端口跟随需要在升级中保留。

## 4. 已有能力，不重复列为缺失

依据当前源代码与 0.1.12–0.1.20 交付记录，以下基础功能已在 Windows 提供；既有测试记录不代表本次重新验收：

- WebView2 多标签、本地 Favorites、原生前进/后退、原始 popup POST/opener、Ctrl+[ 返回来源工作区；Chrome 书签选择同步、历史建议、图标、模糊捕获背景、Save Download。
- 后台服务恢复、Clear Monitor Cache、独立 Loader。
- Copy-only 原生文件/目录拖放通道、Windows Shell 回收与 SQLite 恢复事务、Word 补充材料转换。
- AI Access 撤销/活动界面、MCP 原始文件只读交付与追加分析。
- 0.1.18 的 arXiv 官方日期批次补抓与时间保留修复。
- 0.1.19 的下载完成后 Paper Files 快照刷新，0.1.20 的 Nature Browser 会话后备及原生来源范围修复。

上述 Windows 独立改动分布在共享 Python/JS 与 C# 中。整文件覆盖或直接采用 macOS 文件系统实现会丢失 `.lnk`、DACL、Shell 回收、已核实 PDF 来源限制及源码桌面启动适配。

Apple Passwords/AutoFill、Safari 同步和 macOS 系统 Quick Look 按用户既定范围排除。Mac 红绿灯位置与 AppKit 屏幕边缘拖窗修复是原生平台差异；无需照搬。Finder alias 的具体格式同样是平台实现差异，但它背后的主文件/附件单一存储与位置同步行为属于 D04/D05，需要 Windows 等价实现。

原台账中的跨应用实体拖放、复杂登录出版商路线、跨盘和外部编辑恢复等仍属**验收缺口**，不能仅凭存在代码改写为“已与 Mac 一致”。Mac→Windows 整库迁移也未因本次源码核对而完成。当前按用户选择继续源码桌面路线，不将签名安装包作为本次差异检查或后续源码更新的前置条件。

许可证文件也有明确差异：Windows 仍是旧 `Gewu Insight Proprietary License`；macOS 为 `Gewu Insight Academic and Non-Commercial Research License` 1.1，并更新了分发、第三方声明和贡献文档。本报告只记录文件差异，不更改当前 Windows 授权文件。

## 5. 后续对齐建议

1. **先适配共享数据与文件基础**：D01–D05、D11。先在隔离副本核验 schema 18→22、Key/别名、Default、文件哈希、跨位置引用、并发与回滚；移植最终状态，保留 Windows 回收和快捷方式实现。
2. **接入统一刷新与 Author 后台**：D06–D07，连同持久任务、显式终止和限流恢复；不继承 Mac 私有修复结果或历史数据。
3. **更新 MCP 与实时界面反馈**：D08–D10，分别验收权限、配额、精确重试、自动 Default 和导入身份复用。既有连接不默认获得新写权限。
4. **适配 Browser/Loader 原生增量及共享界面**：D12–D17；PDF 字节复用、下载型 PDF 预览、进程恢复与日志定位需要对应的 C# 外壳，不只改 Python/JS。
5. **同步文档和交付**：D18；Windows 自己的截图、快捷键、系统文件处理和源码入口保持准确。交付仍走 0.1.20 既定源码桌面方式及必要的新版外壳，提交和推送另需用户明确要求。

这一范围是一次较大的功能追平，不宜当成仅更新版本号或直接覆盖共享目录的小补丁。

## 6. 核对方法与限制

- 读取 `PROJECT_STATE.md`、`AGENTS.md` 和既有 Windows 对齐/交付文档后，获取远端 `main`；用上次 macOS 检查点、最新 macOS 和当前 Windows 做三方对照。
- 核对提交日志、变更文件、关键 Python/JS/C# 入口、schema 升级分支、MCP 静态工具定义与文件类型枚举，检查现有 EXE/DLL 的版本信息。
- Windows 硬证据包括：`storage.py:27` 的 schema 18，`mcp_server.py:272` 的 1.1.0，`BrowserCapture.cs:112–122` 的 90 秒/64 MiB 独立下载，`Program.cs:311–321` 的原生 Save Download，`ui_server.py:37621–37626` 的旧排序模式，以及新模块缺失。
- 本次没有启动 macOS 程序、操作 Windows App、运行产品功能测试、升级原库、修复历史资料、下载论文或执行安装。文档审计不新增功能测试，也不把历史 Mac 测试结果当成 Windows 验收。
- 只新增此报告；没有修改运行代码、用户已有文档改动或原始资料。固定远端 SHA 保证后续可复核。

## 7. 固定源码参考

- [本次 macOS 截止提交](https://github.com/LKong92/Gewu-Insight/commit/8a2789512164a42ac066a3cee67548b1328d5056)
- [macOS 增量提交范围](https://github.com/LKong92/Gewu-Insight/compare/9ea2bb3b8160aa931667afc1c412608627f2f473...8a2789512164a42ac066a3cee67548b1328d5056)
- [macOS 数据结构与升级代码](https://github.com/LKong92/Gewu-Insight/blob/8a2789512164a42ac066a3cee67548b1328d5056/paper_monitor/storage.py#L765)
- [macOS MCP 工具定义](https://github.com/LKong92/Gewu-Insight/blob/8a2789512164a42ac066a3cee67548b1328d5056/paper_monitor/mcp_server.py#L69)
- [macOS PDF 捕获与复用](https://github.com/LKong92/Gewu-Insight/blob/8a2789512164a42ac066a3cee67548b1328d5056/docs/BROWSER_PDF_PREVIEW.md)
- [macOS 公告关系与身份](https://github.com/LKong92/Gewu-Insight/blob/8a2789512164a42ac066a3cee67548b1328d5056/docs/PUBLICATION_NOTICES.md)
- [macOS 统一刷新](https://github.com/LKong92/Gewu-Insight/blob/8a2789512164a42ac066a3cee67548b1328d5056/docs/METADATA_REFRESH.md)
- [Windows 当前源码桌面说明](WINDOWS_SOURCE_DESKTOP.md)
- [Windows 既有交付记录](WINDOWS_PREVIEW_STATUS.md)
- [历史差异台账（首部仍为 0.1.17 历史状态）](WINDOWS_MAC_PARITY_TRACKER.md)

## 8. 本次新增 macOS 提交索引

以下由固定 Git 范围生成；需结合上文最终状态，不能逐个标题机械移植。

| 提交 | 日期 | 原始提交主题 |
| --- | --- | --- |
| `0544573` | 2026-09-10 | Preserve the import progress UI draft before revising conflict handling |
| `5ac4368` | 2026-09-10 | Preserve imported files and stabilize Library and Monitor interactions |
| `6a1e1a8` | 2026-09-11 | Keep Author Monitor responsive and preview publisher PDF downloads |
| `574b2e6` | 2026-09-11 | Unify metadata refresh across papers, folders and imports |
| `cb16eb6` | 2026-09-11 | Unify paper identities and deduplicate Author Monitor records |
| `d6adc89` | 2026-09-11 | Show metadata refresh completion as a concise green footer notice |
| `94e16fe` | 2026-09-11 | Fix manual identifier correction and show save confirmation |
| `b5555dc` | 2026-09-13 | Fix fuzzy Library search and recover interrupted workspace previews |
| `43681d2` | 2026-09-13 | Configure Library destinations and protect active files from Recycle |
| `1a254a6` | 2026-09-13 | Release Gewu Insight 1.0.0 with an audited and illustrated User Guide |
| `fca6f0c` | 2026-09-15 | Recover Author Monitor after transient network failures |
| `f4ff5a4` | 2026-09-16 | Accept file drops across the entire Paper Files column |
| `b328725` | 2026-09-16 | Center Browser tab favicons beside their titles |
| `c578d63` | 2026-09-16 | Reuse loaded browser PDFs and preserve capture paper identity |
| `a39ce58` | 2026-09-16 | Add Library table sorting and compact Space navigation |
| `d925cc0` | 2026-09-16 | Synchronize User Guide with current Library and Browser workflows |
| `52ec572` | 2026-09-16 | Add scoped MCP directory browsing and synchronize the User Guide |
| `98a2c02` | 2026-09-16 | Clarify the Gewu Insight name and research mission |
| `1888608` | 2026-09-17 | Add MCP temporary file release and remaining quota reporting |
| `8e3b6f1` | 2026-09-17 | Restore Paper Files drops across the scrolling column |
| `36a8cef` | 2026-09-17 | Fix Paper Files ownership moves and restore APS journal text labels |
| `b1bdd9f` | 2026-09-17 | Fix Library row drops and add terminal Stop for metadata jobs |
| `7825b41` | 2026-09-18 | Add Show in Library navigation to Loader and refresh logs |
| `e833ce2` | 2026-09-18 | Separate Library activity indicators and add Help contact email |
| `93810d4` | 2026-09-18 | Normalize managed Paper Files and add native Finder aliases |
| `bfb55d1` | 2026-09-18 | Prevent duplicate Paper Files during reimport and repair legacy records |
| `ab78638` | 2026-09-18 | Restore direct startup without automatic Library maintenance |
| `4000d98` | 2026-09-18 | Restore targeted interrupted-move recovery without Library maintenance |
| `6110a80` | 2026-09-18 | Fix Author Monitor completion scope and Scholar profile recovery |
| `b6d205d` | 2026-09-18 | Align the User Guide with current background and file workflows |
| `b57aebc` | 2026-09-19 | Fix drag-sort feedback in Author Monitor and My Publications |
| `dc42c3a` | 2026-09-22 | Fix Science main PDF validation, supplement merging and file names |
| `2392a9f` | 2026-09-22 | Add scoped MCP imports and persistent write-permission controls |
| `789728a` | 2026-09-22 | Fix Markdown Quick Look properties, sizing and repeated loading |
| `5701bdd` | 2026-09-22 | Speed up folder renaming with transactional file recovery |
| `3eba6d0` | 2026-09-22 | Fix Science First Release labels and Save to Gewu module loading |
| `0c32a5e` | 2026-09-23 | Add scoped MCP file and folder move and rename tools |
| `94a1299` | 2026-09-23 | Keep macOS window controls aligned after titlebar updates |
| `ad7632b` | 2026-09-23 | Fix Author Monitor identity review, idle status and first-open delays |
| `51e8415` | 2026-09-23 | Add sortable Time added column to Library tables |
| `b9364b5` | 2026-09-24 | Restore Finder drops across the workspace and record Scholar pause causes |
| `263057e` | 2026-09-24 | Reduce Library import and Recycle deletion overhead |
| `e3e0a81` | 2026-09-24 | Use native macOS window dragging for desktop edge transitions |
| `ca3cd11` | 2026-09-24 | Update the User Guide for current Library, preview and MCP workflows |
| `8dee04e` | 2026-09-24 | Grant non-commercial research use while reserving commercial rights |
| `64fad33` | 2026-09-24 | Permit non-commercial sharing of modified research software |
| `8153188` | 2026-09-25 | Rename literature data settings and refresh the project overview |
| `18c88af` | 2026-09-25 | Align README positioning with research information continuity |
| `c8725b6` | 2026-09-25 | Refresh the AI Access guide overview and keep its PDF opening together |
| `ad38f86` | 2026-09-25 | Unify project contact details and add the official website |
| `6ffb2ec` | 2026-09-27 | Render Markdown math and refresh Library after external MCP writes |
| `251a9d9` | 2026-09-27 | Fix MCP automatic Default selection and add manuscript citation |
| `8a27895` | 2026-09-28 | Preserve article identity across notices and MCP imports |
