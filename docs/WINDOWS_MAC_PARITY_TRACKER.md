# Mac → Windows 迁移基线与功能差异记录

记录日期：2026-09-10（Asia/Tokyo）。适用版本：Windows Preview `0.1.10+57a8b2d`，版本依据为现有安装验收记录，本次未重新运行安装版。

用途：固定 Windows 的 Mac 源码起点，记录尚未迁移的功能与验收缺口，并作为后续 Mac 更新同步的台账。**当前 Windows 仍未达到与该 Mac 基线功能一致的验收状态。**

首次建档只核对本地 Git 记录、当前源码及已有验收文档，未执行功能测试。随后用户要求独立提交并推送 Windows 版；提交检查另见 [Preview 状态](WINDOWS_PREVIEW_STATUS.md)。下文的“原 Mac”指迁移起点及本地保留的 Mac 实现，不代表 GitHub 当前最新版本；本表的功能盘点未做实机复现。

## 1. Windows 从哪个 Mac 版本开始

| 项目 | 已核实记录 |
| --- | --- |
| GitHub 仓库 | [LKong92/Gewu-Insight](https://github.com/LKong92/Gewu-Insight) |
| 下载来源分支 | `main` |
| **实际 Mac 源码基线** | **`57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`** |
| 固定源码入口 | [基线提交](https://github.com/LKong92/Gewu-Insight/commit/57a8b2dcea77e97fd6b5acdd5e076c1aee61042d) |
| 本机克隆时间 | 2026-09-08 16:04:56 +09:00；对应北京时间 15:04:56 |
| Windows 初始开发分支 | `codex/windows-migration`，从该基线创建 |
| Windows 独立提交分支 | `codex/windows-preview-0.1.10-20260910`，承接本地 Windows 改动，禁止混入远端 Mac 分支 |
| 本地工作目录 | `C:\Users\Zhengran\Desktop\gewu-insight` |
| 首次建档时的分支 HEAD | 为上述基线；当时 Windows 产品改动尚未形成新提交。该项是历史起点，不随后续 Windows 提交移动 |
| 当前 Windows 安装验收版本 | `0.1.10+57a8b2d`；`57a8b2d` 是来源标识，不表示功能已经完全对齐 |

证据链：本地 `.git/config` 记录仓库 URL；`.git/logs/HEAD` 和 `.git/logs/refs/heads/main` 记录克隆到该 SHA；`.git/refs/heads/codex/windows-migration` 记录当前 HEAD。[迁移审计](WINDOWS_MIGRATION_AUDIT.md)与 [Preview 状态](WINDOWS_PREVIEW_STATUS.md)也记录同一完整基线。

历史附件中的 `913efd97fbefd6ea7132cd8167f1b0916cdba771` 是更早的交接检查点，`PROJECT_STATE.md` 中的 `dd881985d9c6758c686272ca1e7414a0e0d8a55d` 是 Mac 历史检查点。**两者都不能替代本机实际克隆基线 `57a8b2d…`。** 本记录以提交 SHA 标识源码版本，不推测一个未核实的 Mac 发布版本号。

## 2. 如何理解状态

- **未实现**：当前 Windows 入口明确禁用，或缺少对应原生处理通道。
- **部分实现**：已具备基础能力，但原 Mac 工作流中的一部分仍缺失。
- **已接通，待验收**：有实现或局部成功记录，尚不足以确认完整 Windows 使用流程通过。
- **平台差异**：Apple 专属能力或已有 Windows 替代方式，需要单独说明，不能据此认定整个功能不可用。

表中的源码路径均相对仓库根目录。代码检查只能证明实现边界；真实拖放、登录网站、外部编辑器和故障恢复等仍需相应实机验收。旧版本文档中的“未接通”不能覆盖后续版本的完成记录。

## 3. 原 Mac 功能中，Windows 明确尚未实现或仅部分实现

| 编号 | 原 Mac 功能 | 当前 Windows 差异与状态 | 证据 / 对应实现 |
| --- | --- | --- | --- |
| M01 | Settings → Clear Monitor Cache | **未实现**。Windows 菜单明确禁用，不能通过该入口执行清理。 | `windows/Program.cs` 的菜单；Mac `scripts/PaperMonitorApp.m` 的 `clearWebCache:` |
| M02 | Library Recycle 中整篇论文、文件夹的永久移除及文件回收 | **部分实现**。整批永久删除仍被阻止；已有 Paper Files 单附件回收及恢复事务，不能据此开放整篇或文件夹删除。 | `paper_monitor/windows_recycle.py` 的批量删除拦截；Preview 0.1.8/0.1.9 记录 |
| M03 | 从 Chrome 书签源选择文件与子目录，执行单向刷新 | **未实现**。Sync from Chrome 禁用；普通书签 HTML Import/Export 已接通。 | `paper_monitor/browser_ui.js` 的 `bookmarkMenu()`；`windows/Program.cs` 缺少源同步命令处理 |
| M04 | Browser 的 Save Download 工具栏按钮和 Share 页面操作菜单 | **未实现**。这两个入口禁用。网页自身触发的普通下载和 Save to Gewu 内的 Get PDF 已另行接通。 | `paper_monitor/browser_ui.js` 的 Windows 入口门控；Mac `scripts/GewuBrowserController.m` 的 `download` / `share` |
| M05 | 地址栏可见的历史建议下拉列表 | **部分实现**。共享页面仍查询建议并处理补全，但 Windows 原生 `suggestions` 命令直接返回，未显示 Mac 对应的候选列表。 | `paper_monitor/browser_ui.js` 的 `showSuggestions()`；`windows/Program.cs` 的 `case "suggestions"` |
| M06 | 书签及 Favorites 的真实网站图标 | **未实现**对应获取通道。Windows 原生 `favicon` 命令直接返回；仍可显示默认地球图标或字母占位。 | `windows/Program.cs` 的 `case "favicon"`；共享 `browser_ui.js`；Mac `GewuBrowserController.m` 的 favicon 请求 |
| M07 | Save to Gewu 面板后方当前网页的一次性模糊快照 | **未实现**。共享面板有 `capture-backdrop` 接收逻辑，Windows capture 只回传文章元数据，未接入网页背景快照。 | `windows/BrowserCapture.cs` 的 `CaptureArticleAsync()`；Mac `GewuBrowserController.m` 的 `captureBackdropForPage:` |
| M08 | 本地服务异常退出后自动重启，恢复后自动回到工作界面 | **未实现**对应运行期恢复。Windows 有启动等待、日志、工作区锁和失败提示，但没有 Mac 的退出监听与重启/重载流程。 | `windows/Program.cs` 的 `StartServerAsync()`；Mac `PaperMonitorApp.m` 的 `terminationHandler` / `restartServerForCurrentOutageIfPossible` |
| M09 | 本地 Home 与网页共同组成的前进/后退历史，取消或下载后回到保留的 Home | **部分实现**。Home/Favorites 与多标签已接通；Windows Back/Forward 直接调用 WebView2 网页历史，未建立 Mac 的 Home 逻辑历史与完整返回状态机制。 | `windows/Program.cs` 的 `OpenPageAsync()` / `BrowserCommandAsync()`；Mac `GewuBrowserController.m` 的保留 Home 与 session 实现 |
| M10 | 网页获得焦点时，原生快捷键返回来源研究工作区、网页边界方向键交还侧栏等 | **部分实现**。共享工作区保留返回状态与 Web 键盘逻辑，但 Windows 远程 WebView2 没有 Mac 对应的原生按键转接。完整菜单、标签与输入焦点仍待逐项验收。 | `windows/Program.cs` 的远程 view 事件；`paper_monitor/browser_ui.js` 的 `workspaceReturn`；Mac `GewuBrowserController.m` 的原生 key monitor |
| M11 | 论文下载 API 返回出版商浏览器后备请求时，后台浏览器继续获取正文或补充文件 | **未实现**此独立通道。共享 `requestPaperPdfDownload()` 会调用 `publisherPdfDownload`，Windows bridge 未注册它。Browser → Save to Gewu → Get PDF 是另一条已实现流程，不能作为这项已完成的证据。 | `paper_monitor/ui_server.py` 的 `downloadPublishedPdfInBackground()`；`windows/workspace.js`；Mac `PaperMonitorApp.m` 的 `publisherPdfDownload` |
| M12 | Library 文件夹向外拖出，以及 Library 条目原生拖动的完整接力 | **部分实现**。Windows 当前提供 Paper Files 单文件 CF_HDROP，原生 `DragFile()` 只接受文件；没有接入共享页面的 `nativeFileDrag` 文件夹通道或 `libraryItemDrag` 通道。不能据此否定仍可用的普通 Web 内部拖动。 | `windows/NativeIntegration.cs`、`windows/workspace.js`；`ui_server.py` 的 `prepareNativeFolderDrag()` / `armNativeLibraryItemDrop()` |

M05–M12 中部分缺口是本次源码对照单独识别的；本次没有实机复现，不将代码分析写成已经观察到的用户操作结果。

## 4. 已有实现，但尚未完成 Windows 全流程验收

| 编号 | 功能范围 | 已有证据 | 还需要确认 |
| --- | --- | --- | --- |
| V01 | Paper Files 向 Explorer/其他应用拖出；Explorer 向 Library/Loader 拖入 | CF_HDROP 与 WebView2 文件对象通道已接；拖出仅提供 Copy | 跨应用真实拖放、目标应用图标接收、多文件及取消；既有记录明确跨应用拖放尚未验收 |
| V02 | PDF/Markdown/图片/文本阅读与键盘 | 0.1.9 连续 PDF 滚动、横向滚动、PDF 专用缩放；实际 Nature PDF 滚动通过；有快速切换、240 页、PNG、Markdown 隔离验证 | 实体触摸板捏合、更多真实长论文、持续快速切换、全部焦点返回与格式后备；不能宣称与 Mac 性能一致 |
| V03 | Get PDF 与真实文章收集 | W3C 官方公开 PDF 获取及后端暂存成功；合成 Save to Gewu 入库、重复复用、层级目标、Show in Library 闭环已有验证 | 更多出版商、用户已有权限的登录会话、跨站 cookie、取消/失败重试；只允许已核实出版社或授权仓库 |
| V04 | Browser 导航与会话 | 保留每标签 WebView2、本地 Home、书签、历史、普通下载已有实现 | POST/弹窗原始请求与 opener、后台标签、内嵌文档、停止/错误/重定向；M09/M10 的缺失须先补齐，不能仅做验收 |
| V05 | History 范围清除 | 原生时间范围与确认框已实现，核心范围删除检查通过 | 既有记录未执行原生确认提交，仍不能称实际 UI 删除已验收 |
| V06 | Library/Shortcut/Space 的多位置文件管理 | `.lnk` 复用真实文件、命名和生命周期回归；资料目录迁出 Codex 缓存并从 Explorer 正常启动已有验证 | 更完整的跨盘、大小写/重名、文件夹移动重命名、失效入口、外部编辑器原子替换与失败恢复 |
| V07 | Paper Files / Default / Annotation / Source | 共享身份、资源模型与局部回归保留；单附件系统回收、DB 失败和启动恢复有隔离测试 | 真实批注编辑、文件替换、多处关联、各种删除失败；系统回收站恢复文件后不会自动补回已删除的 Paper Files 关联 |
| V08 | Library/My Publications 与 Journal/Subject/Author Monitor 的完整工作流 | 共用 Python/SQLite/UI；已有本机资料和部分导入、显示、设置检查 | 六个工作区中的导入、筛选、日历、未读、下载/分析状态、Note、设置、在线发现及自动刷新全流程；没有证据的项目标为待验收，不直接判为未实现 |
| V09 | My Publications 报告、DOCX/TeX/Overleaf ZIP 等导出 | 保留共享导出代码和 Windows 默认应用打开方式 | Windows 下生成结果、路径、图像/LaTeX 依赖、外部打开和完整导出内容；此次未生成这些产物 |

已有检查的日期、范围与局限见 [Windows Preview 状态](WINDOWS_PREVIEW_STATUS.md) 最新对应版本。该文件后半部分仍保留 0.1.3 等历史清单，阅读时应先看 0.1.10 → 0.1.9 → 0.1.8 → 0.1.5 的后续结果。

## 5. Mac 专属能力与已有 Windows 替代

| 原 Mac 能力 | Windows 当前处理 | 追踪边界 |
| --- | --- | --- |
| macOS Quick Look 的 hybrid / native_all，以及系统格式预览器 | Windows 仅提供 builtin_all，隐藏两个 Mac 模式；PDF/Markdown/图片等用内置路线，不支持的格式通过默认应用打开 | 系统 Quick Look 格式覆盖尚无等价实现；不能因此把 Windows PDF 预览写成未实现 |
| Open Passwords、Apple AutoFill 触发 | Open Passwords 在 Windows 不创建；没有迁移 Apple 凭据功能 | Mac 本身也未证明 Safari 等价的可靠自动填充，不能把未证明能力列为 Mac 已完成功能 |
| Sync from Safari | Windows 隐藏该入口；可通过支持的书签导出文件执行普通 Import | 与 M03 的 Chrome 源刷新分别记录，不把 HTML Import 当成已实现源同步 |
| Finder、Preview、Open in Safari | 对应 Windows File Explorer、系统默认文件/PDF 应用、默认浏览器 | 已做平台替代；默认 PDF 应用遵循 Windows 文件关联，用户明确未要求新增应用选择菜单 |
| 独立 Library Loader 原生窗口 | Windows 已有 Loader 菜单、文件夹选择与页面内 Loader；未注册 Mac 的 `libraryLoaderWindow` 原生独立窗口通道 | 记录窗口形态差异，不能说 Loader 功能完全未实现 |

独立 Safari/Chrome 扩展、退出后恢复网页标签，以及已删除的分析队列/Deep Survey，都不能凭历史设想列入“原 Mac 已有、Windows 漏做”的清单。被用户否定并回退的 PDF 预览实验也不是需要恢复的目标。

## 6. 完整迁移与发布仍需完成的工作

以下是 Windows 完整交付边界，不能与“Mac 某个现成功能未移植”混为一谈。

| 编号 | 工作 | 当前边界 |
| --- | --- | --- |
| R01 | 旧 Mac Library → Windows 的完整迁移工具 | 尚未交付可正式迁入的工具。须在副本上验证 SQLite、文件 hash、路径重定位、Gewu Key、资源/位置/Default/Source/批注关系与可中断恢复。现有 Windows 资料目录搬迁不等于跨平台整库迁移。 |
| R02 | 完整备份与恢复 | 已有本机升级/搬迁时的备份与数据核对，但没有完整 Windows 备份、还原、异常中断与跨机器验收。导出报告或重新导入论文不能替代整库恢复。 |
| R03 | 安装与运行生命周期 | 同机多次安装升级、包内服务启动和数据保留已有记录；首次离线启动、全新机器、故障重启及全面卸载/恢复仍待验收。M08 是明确代码缺口。 |
| R04 | 正式发布和完整手册 | 当前为未签名 Preview；本机 Windows 11 x64 已测，Windows 10、ARM64 未验收。Windows HTML/PDF 简明指南已有；完整 Windows 实机截图与全功能手册仍待补齐。 |

## 7. Mac 后续新增修改的追踪台账

**固定起点永远保留为 `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`。尚未核对该提交之后的 Mac 源码增量。** 2026-09-10 的独立提交准备通过 `ls-remote` 只读确认远端 `main` 已到 `3e1e50aaffd0822fe9f74df70e07f282daae8adb`；这只证明远端已有更新，不代表已审查或移植这些变化。本地缓存的 `origin/main` 不能代替实时远端状态。

| 追踪字段 | 当前值 |
| --- | --- |
| Mac 原始迁移基线 | `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d` |
| 后续 Mac 增量已检查到 | 尚未检查；只确认原始基线 |
| 已完整适配并验收的 Mac 截止提交 | 尚无；基线能力仍存在上述缺项 |
| Windows 当前版本依据 | Preview `0.1.10+57a8b2d` 的已有安装验收记录 |
| 独立提交目标 | 仅 `refs/heads/codex/windows-preview-0.1.10-20260910`；不合并、推送更新或覆盖 Mac `main`，不创建合并到 Mac 的 PR |

后续每次同步，应保留当前 Windows 改动，以原始/上次对照基线、Mac 新源码和 Windows 当前源码做三方比较，逐项填写下表；仅检查过某个提交，不代表已经完成适配。

| Mac 提交 / 对照区间 | Mac 功能变化与文件 | Windows 对应修改或无需修改的理由 | 状态 | Windows 版本 / 提交及实际验证 |
| --- | --- | --- | --- | --- |
| 基线之后的增量待获取 | 尚未核对 | 尚未评估 | 待检查 | 无 |

维护规则：

1. 已推送到 GitHub 的修改按完整 SHA/提交范围追踪；Mac 上尚未推送的修改需要额外源码差异，不能假设已包含在远端。
2. 共用 Python/JS 修改评估是否可直接适配；AppKit/WKWebView 修改需映射到 WinForms/WebView2 的用户行为；Mac 专属变化记录理由。不得用整文件覆盖丢失 Windows 适配。
3. M/V/R 编号保持稳定。完成后更新状态、Windows 版本、对应源码与实际验证，保留历史边界；不要只删掉缺项。
4. 验证在隔离资料上进行；SQLite 是唯一事实来源，保留身份、Default、来源、文件关联及下载/分析状态。PDF 来源约束和 Subject Monitor 的 Zenodo 拒绝规则持续有效。
5. 只有功能已实现且相关 CLI/UI/原生流程实际通过，才标为完成；模拟输入、源码契约或 Mac 测试不能冒充 Windows 实机结果。提交与推送仍需用户明确要求。

## 8. 参考记录与本次核对范围

- [Windows Preview 状态](WINDOWS_PREVIEW_STATUS.md)：各版本实现及实际验收记录，是本表验证状态的主要来源。
- [Windows 迁移审计](WINDOWS_MIGRATION_AUDIT.md)：原始基线、产品范围、历史方案与平台边界。
- [Windows 工作目录搬迁](WINDOWS_WORKSPACE_RELOCATION.md)：已完成的本机目录搬迁及数据边界。
- [项目交接状态](../PROJECT_STATE.md)：当前项目入口；其中 Mac 段落含历史记录。
- 本次源码核对：`windows/Program.cs`、`BrowserCapture.cs`、`BrowserDialogs.cs`、`NativeIntegration.cs`、`workspace.js`；`paper_monitor/browser_ui.js`、`ui_server.py`、`desktop_files.py`、`windows_recycle.py`；本地 Mac 参考 `scripts/PaperMonitorApp.m`、`GewuBrowserController.m`。
- 首次建档仅新增记录并在项目交接中加入入口，未运行功能测试或提交。后续 Windows 独立提交的检查单独记录在 [Preview 状态](WINDOWS_PREVIEW_STATUS.md)，不能将其当作 Mac 新增功能已同步。
