# Windows 迁移审计 — 2026-09-08

状态：阶段 1 已完成，阶段 2/3/4 部分推进至 Windows Preview 0.1.3 安装包；下文保留阶段 1 历史证据。最新实现、验证及未完成项见 [Windows Preview 状态](WINDOWS_PREVIEW_STATUS.md)，不能将该开发版本视为 macOS 功能等价验收通过。
附件是历史资料；本次用户要求、当前源码与实测共同确定范围。未 commit/push。

## 1. 实际基线与环境

- 工作目录：`C:\Users\Zhengran\Desktop\gewu-insight`。
- 接手 HEAD：`57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`。
- 已通过实时 `git ls-remote origin refs/heads/main` 核对：GitHub main 与 HEAD 相同。
- 接手分支为 `main`；现为独立分支 `codex/windows-migration`。
- 接手时无 tracked 文件改动，只有用户的迁移附件未跟踪；附件保持原样。
- 历史检查点 `913efd9` 后有 `cf5fbac`、`dd88198`、`57a8b2d` 三个提交。
- PROJECT_STATE 中的 macOS 路径及 `dd88198` 描述不是本机基线；未回退代码。
- 实机：Windows 11，build 26200，x64；Python 3.13.11（已有 `.venv`）。
- .NET host 存在，但 `dotnet --list-sdks` 无输出；尚无可用 .NET SDK 构建证据。
- WebView2 Runtime 目录存在（包含 152.0.4191.66）；尚未证明宿主集成成功。
- Git 不在 PATH；已定位 Codex bundled Git，修正 `GIT_EXEC_PATH` 后可查询远端。
- 没有 macOS 执行环境；现有 macOS 测试记录不能用作本次 Windows 验证。

## 2. 历史讨论与当前产品差异

| 历史/交接点 | 当前事实与源码证据 | Windows 范围影响 |
| --- | --- | --- |
| 五月以本地 Web UI 为迁移起点 | 当前是 Library（含 My Publications）与三个 Monitor、Browser 的完整桌面工作区 | 不能将服务启动等同于六个工作区验收 |
| 八月只概括文件、Monitor、预览 | 新增原生 Browser，32 个会话内标签、本地 Favorites Home、书签/历史、单向书签同步；`browser_ui.js`、`browser_store.py`、`GewuBrowserController.m` | 独立实现标签、会话、下载和网页/本地隔离 |
| 旧外部网站入口 | `7a6f703` Website Links 默认内置；外部默认浏览器可保存；`3541955` 保留来源工作区并返回 | 保留偏好、来源返回、滚动/选择；不能强制换浏览器而隐藏差异 |
| 旧 Browser 不包含完整收集 | `d580d4b`、`885ea9b`、`8525842`：身份核对、PDF 绑定来源、Default/主文件修复、层级目标和 Show in Library | 复用 capture 后端；重做 WebView2 下载/临时票据生命周期 |
| 旧捕获面板 | `acbfbdc` Details 默认折叠、持久化起始偏好、可信面板与一次性模糊快照 | 紧凑流程及错误展开也必须迁移 |
| “混合预览为默认” | `quick_look_mode` 实际默认 `builtin_all`；支持 hybrid/native_all；PROJECT_STATE 记载后续 PDF 修复被否定并回退 | 不恢复废弃的 PDF.js readiness/snapshot 优化，不承诺快速切换性能 |
| 附件检查点 `913efd9` | 后续 Library rail 样式、焦点形状、chevron；`57a8b2d` 增加离线 Markdown worker 和向应用拖出文件 | Markdown 安全限制、焦点与原生拖放都属于新产品范围 |
| 早期文件版本概念 | `storage.py` schema 16；平级 Paper Files，Type/Annotation/Source 独立；手动 Default sticky | 不简化为单 PDF，也不让选择 Default 移动真实文件 |
| 来源只是 JSON/计数 | `6236b8d` normalized source observations 与身份冲突隔离；JSON 是兼容投影 | 不削减来源、Gewu Key、跨区域关联 |
| 旧自动分析设想 | 当前 CLI/路由无分析队列与 Deep Survey；删除契约测试存在；Note 保留读取/删除 | 不重新引入已移除能力；其删除时间不能仅凭摘要推断 |
| Mac-only 使用手册 | 78 页 PDF 与 HTML/TeX；备份章节仍明确 Move to Another Mac | Windows 文档需要独立真实截图与流程，不把旧图换标签 |
| 启动方式 | 原生不透明启动画面、慢 schema 升级等待、崩溃后服务恢复 | 安装版必须实现同等服务生命周期；CLI 入口没有这些能力 |

## 3. 完整产品范围与平台依赖

| 产品区域 | 可复用内容 | Windows 尚需实现/验收 |
| --- | --- | --- |
| Library / Shortcut / Space | canonical 身份、稳定 Key、文件夹/多位置关联、回收区模型、搜索与列 UI | Explorer 映射、文件夹移动/重命名、大小写/保留名/跨盘冲突、快捷键与拖放 |
| My Publications | 同一 paper 的作者角色、引用指标、注释报告、筛选/排序、DOCX/TeX/Overleaf ZIP 导出 | 原生文件打开/桌面 Known Folder；LaTeX 可选依赖；导出 UI 与文件关联 |
| Journal / Subject / Author | 发现源、范围设置、日期状态、Zenodo 拒绝、来源、Unread 与共享缓存 | Windows 系统时区、定时调度、网络/代理、真实下载/头像；未跑在线监控 |
| Browser | 本地书签/历史/Favorites、capture 后端、目标选择、Details 偏好、来源约束 | WebView2 原生标签/会话/PDF/下载、焦点交接、导航限制、取消/重试、Show in Library；WebKit 登录不迁移 |
| Paper Files / Default | 资源类型、批注、来源、exact hash 去重、有效 PDF 检验、手动 Default | 批注编辑的文件替换、映射修复、删除后 DB 失败恢复、跨盘；不能复制多份来充当映射 |
| 导入/导出/备份 | Inventory dry run/copy/link 语义、受管副本、完整导出 manifest 与关联恢复 | 原生文件/文件夹选择、Windows 路径识别、`.lnk` 导入政策、完整 SQLite+文件备份/恢复；导出不是整库迁移 |
| Settings / Note | SQLite 偏好、秘密按需显示、右侧 Note 独立滚动、主题/字号/源设置 | 平台能力声明、Windows 标签；无能力时不保留可点击但失效的入口 |
| 键盘/预览 | Web 选择模型、空格/Esc/上下、Default/资源同步、Markdown worker、格式后备 | 预览原生窗口、Ctrl 习惯、焦点返回、PDF 快切实测、图像/文本/媒体、Office 后备；不承诺 Quick Look 格式覆盖 |
| Guide / 发布 | HTML 为共同文档源、TeX/PDF builder、原 Product Identity 连续布局 | Windows 实机截图、HTML/PDF 同步、首次安装/升级/卸载/数据保留与签名 |

主要调用点：`ui_server.py` 的 `handle_open_pdf`、`handle_open_native_file`、
`reveal_path_in_finder`、`move_path_to_macos_trash`、`create_pdf_alias`、
`sync_all_pdf_aliases_for_paper`、`move_or_alias_library_item_pdf`、
`rename_library_item_and_sync_files`、`paper_ids_referencing_pdf_path`。
外壳位于 `scripts/PaperMonitorApp.m` 和 `scripts/GewuBrowser*.m`。

## 4. 已发现的问题，不能视为正确 Windows 规格

1. 非 macOS Trash 分支只是移动到 `~/.Trash`，不是 Windows Recycle Bin。
   `delete_paper_resource` 一类操作存在“数据库提交失败后按 Trash 目标路径移回”的恢复假设；
   不可直接换成不返回恢复标识的回收站 API。
2. `create_pdf_alias` 无条件 `os.symlink`；大量清理/重命名路径使用 `is_symlink()`。
   `.lnk` 不会被 `Path.resolve()` 解引用，需要完整 placement adapter，不能仅换一行。
3. `finder_safe_name` 不处理全部 Windows 禁用字符、设备保留名；路径引用 SQL 比较亦需审计大小写等价性。
4. `GEWU_DATA_ROOT` 覆盖 SQLite/受管文件，但 reports、subjects、缩略图缓存仍有独立根。
   启动会启动 Monitor、清理缓存，因此本轮在完整临时源码副本上启用已有 documentation mode，
   无正式数据库、文件、profiles 或个人 subjects 被复制。
5. `time_utils.system_timezone_name()` 只认识 Unix zoneinfo；实机日本时区却返回 UTC。
   Windows 新增 tzlocal 与 tzdata 条件依赖并修复；显式 TZ 仍优先，夏令时规则保留。
6. PDF 缩略图依赖 `sips`；缓存根 `/private/tmp/paper_monitor_pdf_thumbs` 在 Windows 不合适。
   网页能显示 PDF 不证明缩略图和原生预览已可用。
7. LaTeX 子进程 PATH 用冒号拼接，Windows 应使用 `os.pathsep`；本机未验证 TeX 工具链。
8. Browser 原生测试与核心 tests 混排；首轮 `xcrun` 测试在 Windows 报错。
   为已执行的 capture 原生类加入明确 macOS skip，不把它算作 Windows 通过。
9. 某些 Python 文本读取依赖系统默认编码；smoke 明确 UTF-8。安装版也要固化 UTF-8 环境并继续逐处审计。
10. `inventory.copy_record` 原先接受绝对 relative_path，拼接时会绕过 target_root；
    已拒绝 Unix/Windows 根路径、UNC、盘符相对路径及 parent traversal，并检查解析后目录边界。
    这属于现有导入代码缺陷，不是 macOS 数据迁移能力；正常中文/空格路径与同名自动编号保留。

## 5. 已确认首版边界与候选方案

用户已确认：先验收全新 Windows Library；旧 macOS Library 工具须在副本上设计/验证，
但首版暂不开放正式迁入。Explorer 必须在每个 Library/Space 位置显示可双击文件入口。

- 建议 Windows 11 x64 Preview；Windows 10/ARM64 支持暂不宣称。
- 保留 Python+SQLite+Web UI，C# WinForms + WebView2 为外壳候选；未冻结。
  原型应验证可信本地 view 与远程 views 分离、来源核对、禁用远程 host objects/messages，
  持久 profile、tabs、PDF 下载及取消，再决定是否适用。
- 发布倾向用户级安装、Python 独立打包（PyInstaller 候选）、Evergreen WebView2 检测，
  安装目录与用户数据目录分离。SDK、安装格式、签名和升级机制待原型后定案。
- Explorer 映射优先评估 `.lnk` → 同一真实文件。`.lnk` 只作入口，不是论文资源，
  不改变 Default。需跟踪由 App 管理的入口，移动后重建并核对所有位置，失效入口可诊断/修复。
  普通用户权限、中文/空格/逗号、重名、跨盘、外部编辑器原子替换都必须验证。
- 不推荐硬链接为默认：跨卷不可用，而且编辑器以 rename/replace 保存时可能分裂为不同内容。
  受控副本增加同步/批注冲突，未经决策不采用。不能依赖 Explorer 自行追踪旧快捷方式。
- Browser/Save to Gewu 仍在目标范围；阶段 1 的 CLI UI 不属于可发布的完整桌面预览版。
- 暂不承诺 Windows 原生 Office/iWork 预览、WebKit 登录迁移、Apple Passwords/AutoFill、
  Safari 专属动作、独立 Safari/Chrome 扩展。应显示明确后备/不可用状态；支持格式优先内置预览。
- 手册等有真实 Windows 操作后同步修改 HTML/PDF；保留 macOS 手册和截图的真实平台身份。

候选技术的官方依据（2026-09-08 核对）：
[WebView2 安全边界](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security)、
[Runtime 分发](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)、
[WinForms 起步](https://learn.microsoft.com/en-us/microsoft-edge/webview2/get-started/winforms)、
[Python Windows 时区数据](https://docs.python.org/3/library/zoneinfo.html)、
[tzlocal Windows 系统时区](https://github.com/regebro/tzlocal)。选型建议是本次工程判断，不是官方推荐的 Gewu 架构。

## 6. 验证记录与接续顺序

`scripts/windows_smoke.py --output tmp/windows-stage1 --tests` 会复制产品源码/静态资源、
仅 journal 默认配置与选定测试到临时工作目录；隔离 SQLite、受管文件、报告、临时下载，
清除子进程 API key 环境引用，关闭自动 Monitor，结束时停止子服务并清理临时目录。
日志只保留在 ignored `tmp/`。这不是 benchmark，也不是安装器。

- 首轮：健康端点正常、HTML 七个区域标记齐全；113 检查，111 通过、2 错误。
  一项为 macOS xcrun 测试误运行，另一项为新 smoke 脚本漏拷 README；两者已定向修正。
- 覆盖：Inventory 导入/去重、版本与手动 Default、来源与冲突、PDF ingress、指纹、
  Browser 后端 review/upload/save/retry/隔离和书签、时区。真实 Browser 网页会话未验收。
- 后续结果记录在本文件末尾；不把 source-contract 或模拟 native 测试算作原生 Windows 成功。

下一步：完成 `.lnk`/回收站恢复机制的普通用户原型 → 文件平台接口和完整映射生命周期 →
Windows 外壳/预览/Browser 原型 → 安装/重启/升级/离线/异常恢复 → 实机手册与发布验收。
旧库迁移单独实现可恢复的副本清单，检查 SQLite 备份、所有资源 hash/关联/Default/来源，
先 dry run 和逐项重定位；不重建数据库、不重新导入整库、不批量字符串替换。

### 阶段 1 最终实测

- 修复后 smoke 主组 115 项：114 通过，1 项 macOS Cocoa/WebKit 原生测试显式跳过。
- 文件生命周期追加组 37 项：29 通过，8 项报 WinError 1314（无 symlink 特权）。
  涉及多位置、快捷方式重名、主路径重命名与 Space 映射；保留失败，不改成 skip。
- Paper Resources 54 项首次 10 失败均来自测试写死 Unix 分隔符；仅将断言路径转换为
  `Path.as_posix()`，没有变更资源行为，重跑 54 项全部通过。
- 路径边界新测试 2 项通过；原 Inventory importer 25 项重跑全部通过。
- 上述去重后共 208 项选定回归：199 通过、8 报错、1 跳过。不是全部产品测试。
  其中 macOS 命令 mock/source 契约检查不等于 macOS 或 Windows 原生执行。
- Windows Shell `.lnk` 原型：`scripts/windows_mapping_probe.ps1 -OutputRoot tmp/windows-link-probe`，
  6 项成功（共同目标、Unicode/空格/逗号/#、外部原子替换、失效检测、显式重定位、删除入口保留目标）。
  未测 Explorer 双击、跨盘、冲突政策、数据库映射生命周期或回收站恢复；不是已接入产品的适配器。
- Windows 本机系统时区现为 `Asia/Tokyo`；冬夏 New York 偏移与显式 TZ 优先也通过。
- 实际浏览器加载隔离服务 `127.0.0.1:18765`：Library 空库完整渲染，Browser 往返切换成功。
  Browser 显示 “Open Gewu Insight.app to use the embedded browser”，Save to Gewu 禁用；
  Open Passwords/Open in Safari 仍露出，记录为 Windows 能力门控缺口。
  这次是 Windows 上的浏览器 UI 核查，不是 Gewu 原生 Windows 外壳或手册截图。
  临时 UI 服务和检查标签已关闭；没有在线 Monitor 刷新。
- Python 31 文件 py_compile 与 git diff --check 通过；ui_server 的既有 `\s` escape SyntaxWarning
  仍存在（未把此警告描述为此次引入或编译失败）。没有运行安装、升级、真实拖放、快速连续 PDF 预览。
- 诊断：`tmp/windows-baseline`、`tmp/windows-stage1`、`tmp/windows-file-baseline`、
  `tmp/windows-resource-check`、`tmp/windows-link-probe`，均被 Git 忽略，不纳入提交。

阶段 2 的首要进入条件是将可行的 `.lnk` 原型扩展为受 SQLite 关联约束的 placement adapter，
明确碰撞、移动失败/重试、失效入口与删除恢复，再替换现有 `is_symlink` 假设。
上述为阶段 1 结论；随后已产生 Preview 安装包，具体见最新状态文档。真实研究库仍未开放验收。
