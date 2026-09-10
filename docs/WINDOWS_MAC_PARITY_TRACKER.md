# Mac → Windows 迁移基线与功能差异记录

记录日期：2026-09-10（Asia/Tokyo）。当前实际安装和运行是 **Windows Preview 0.1.13**，18:40 JST 安装成功，18:47 JST 正式原库正常关闭/重开、可见窗口与认证服务核验通过。原库保持 schema 18、44 篇 papers，受保护论文/资料行和研究文件保留。Smart App Control 仍开启，未修改保护/信任或提交外部复核，仍是本机未签名 Preview。0.1.11 源码同步 Mac 至 `2a12320`，0.1.12–0.1.13 增补下述 Windows 功能；用户要求免费使用、保留专有许可。第 3–6 节保留差异和验收清单，第 7–9 节记录增量与验证边界。

用途：固定 Windows 的 Mac 源码起点，记录尚未迁移的功能与验收缺口，并作为后续 Mac 更新同步的台账。**当前 Windows 仍未达到与该 Mac 基线功能一致的验收状态。**

前一轮更新：**0.1.12 已安装**，接通 M03/M05/M06/M07/M08。35 项隔离原生检查通过；包内服务/MCP 与开发 EXE 各两次启动通过，实际安装目录 EXE 再两次通过，原库正常关闭/重开与数据完整性通过。首次安装器阻断（3077/3033）记录保留；用户要求重试后同一安装器退出 0。仍是未签名本机 Preview，第 3 节的隔离功能检查不等于全部用户场景验收；详细边界见第 8 节。

最新更新：**0.1.13 已安装并正常重开**，补齐 M04/M09/M10 的实现；80 项隔离原生检查通过，实际安装目录双启动及原库重开/数据核验通过，详见第 9 节。M01/M02/M11/M12 继续未完成，平台专属差异与 V/R 验收清单仍保留。

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
| 首个 Windows 源码提交 | [`59fa205c3037db0c387d9456cb8d0cc3a4370b51`](https://github.com/LKong92/Gewu-Insight/commit/59fa205c3037db0c387d9456cb8d0cc3a4370b51)，已于 2026-09-10 推送至全新的 Windows 分支 |
| 本地工作目录 | `C:\Users\Zhengran\Desktop\gewu-insight` |
| 首次建档时的分支 HEAD | 为上述基线；当时 Windows 产品改动尚未形成新提交。该项是历史起点，不随后续 Windows 提交移动 |
| 当前安装 / 原生验收版本 | `0.1.13` 已安装；安装目录两次隔离启动、正式原库启动/重开和 API/资料核验通过，仍未完整验收所有原生功能 |

证据链：本地 `.git/config` 记录仓库 URL；`.git/logs/HEAD` 和 `.git/logs/refs/heads/main` 记录克隆到该 SHA；`.git/refs/heads/codex/windows-migration` 记录当前 HEAD。[迁移审计](WINDOWS_MIGRATION_AUDIT.md)与 [Preview 状态](WINDOWS_PREVIEW_STATUS.md)也记录同一完整基线。

历史附件中的 `913efd97fbefd6ea7132cd8167f1b0916cdba771` 是更早的交接检查点，`PROJECT_STATE.md` 中的 `dd881985d9c6758c686272ca1e7414a0e0d8a55d` 是 Mac 历史检查点。**两者都不能替代本机实际克隆基线 `57a8b2d…`。** 本记录以提交 SHA 标识源码版本，不推测一个未核实的 Mac 发布版本号。

## 2. 如何理解状态

- **未实现**：当前 Windows 入口明确禁用，或缺少对应原生处理通道。
- **部分实现**：已具备基础能力，但原 Mac 工作流中的一部分仍缺失。
- **已接通，待验收**：有实现或局部成功记录，尚不足以确认完整 Windows 使用流程通过。
- **平台差异**：Apple 专属能力或已有 Windows 替代方式，需要单独说明，不能据此认定整个功能不可用。

表中的源码路径均相对仓库根目录。代码检查只能证明实现边界；真实拖放、登录网站、外部编辑器和故障恢复等仍需相应实机验收。旧版本文档中的“未接通”不能覆盖后续版本的完成记录。

## 3. 原 Mac 功能对齐状态（安装版与开发源码分开记录）

| 编号 | 原 Mac 功能 | 当前 Windows 差异与状态 | 证据 / 对应实现 |
| --- | --- | --- | --- |
| M01 | Settings → Clear Monitor Cache | **未实现 Windows 对应维护操作**。Mac 清的是 `~/Library/Caches/local.paper-monitor/WebKit/NetworkCache`；Windows 没有该 WebKit 缓存，直接调用共享 API 只会空清理。Windows 菜单仍禁用，不能把 Browser profile 清理冒充原 Monitor 缓存清理。 | `windows/Program.cs`；Mac `clearWebCache:`；`ui_server.py` 的 `clear_webkit_network_cache()` |
| M02 | Library Recycle 中整篇论文、文件夹的永久移除及文件回收 | **部分实现**。整批永久删除仍被阻止；已有 Paper Files 单附件回收及恢复事务，不能据此开放整篇或文件夹删除。 | `paper_monitor/windows_recycle.py` 的批量删除拦截；Preview 0.1.8/0.1.9 记录 |
| M03 | 从 Chrome 书签源选择文件与子目录，执行单向刷新 | **0.1.12 已安装，待完整验收**。明确选择一个 Bookmarks 文件和子目录；沿用共享 SQLite 同步、去重和保留本地修改逻辑。隔离原生目录选择/重复同步/源文件不变通过；真实个人 Chrome 文件选择仍待验收。已随本机 0.1.12 安装。 | `windows/BrowserDialogs.cs`；`paper_monitor/browser_ui.js`；`tests/windows_browser_parity/` |
| M04 | Browser 的 Save Download 工具栏按钮和 Share 页面操作菜单 | **0.1.13 已安装，待完整验收**。原生四项页面菜单、独立同 profile 下载、64 MB 限制、原始响应字节及 PDF/重定向来源检查已验证；不写 Library。最终 Save 对话框操作、更多真实网站和登录流程待验收。已随本机 0.1.13 安装。 | `windows/BrowserPageActions.cs`；共享 `browser_ui.js`；第 9 节 |
| M05 | 地址栏可见的历史建议下拉列表 | **0.1.12 已安装，待完整验收**。原生候选层位于网页之上，保留输入焦点，复用本地历史与补全；鼠标选取、方向键、Esc 的隔离流程通过。实体 IME/更多 DPI/无障碍仍待验收。已随本机 0.1.12 安装。 | `windows/BrowserSuggestions.cs`；`windows/Program.cs`；共享 `showSuggestions()` |
| M06 | 书签及 Favorites 的真实网站图标 | **0.1.12 已安装，待完整验收**。独立匿名 HTTPS 客户端、同站图标提示、2 并发、限量/重定向检查，归一成 64px PNG；使用会话内缓存，没有移植 Mac 磁盘缓存。隔离传输与图像检查通过，更多真实网站图标仍待验收。已随本机 0.1.12 安装。 | `windows/BrowserFavicons.cs`；WebView2 `FaviconChanged`；`tests/windows_browser_parity/` |
| M07 | Save to Gewu 面板后方当前网页的一次性模糊快照 | **0.1.12 已安装，待完整验收**。单次当前视口 JPEG、原有 blur、纯内存与过期/取消保护；截图前保留原生表面，1.5 秒后即使缺图也显示面板。真实 WebView2 生成页截图、取消和缺图回退通过。已随本机 0.1.12 安装。 | `windows/BrowserCapture.cs`；共享 capture/layout；`tests/windows_browser_parity/` |
| M08 | 本地服务异常退出后自动重启，恢复后自动回到工作界面 | **0.1.12 已安装，待完整验收**。退出监听、认证会话重载、每分钟最多 3 次重启；保留远程页面及未提交表单。临时服务连续 3 次崩溃后恢复、第 4 次停止重试、书签和草稿保留通过。已随本机 0.1.12 安装；不覆盖 OS/App 崩溃或未保存的 Library 表单。 | `windows/ServiceRecovery.cs`；`windows/Program.cs`；共享 tabs 恢复 |
| M09 | 本地 Home 与网页共同组成的前进/后退历史，取消或下载后回到保留的 Home | **0.1.13 已安装，待完整验收**。每标签本地 Home 与 Chromium 原生 history ID 组合，保留文档/草稿、页内历史和前进分支，取消及迟到响应不能显示旧网页。弹窗直接接收原始请求，POST/opener 已验证；真实复杂网站、普通下载离开 Home 等仍待完整验收。 | `windows/BrowserNavigation.cs`、`Program.cs`；第 9 节 |
| M10 | 网页获得焦点时，原生快捷键返回来源研究工作区、网页边界方向键交还侧栏等 | **0.1.13 已安装，待完整验收**。WinForms 原生键盘事件、当前 Win32 活动窗口/焦点/菜单边界、Ctrl+[ 返回来源工作区，以及一次性隔离方向键几何检查。向隐藏测试窗口发送的 Ctrl+L/F/[ 消息及完整返回流程通过；实体键盘、IME、全部快捷键/DPI/无障碍待验收。 | `windows/BrowserKeyboard.cs`；共享 `GewuBrowserNavigationProbe.js` 与 `workspaceReturn`；第 9 节 |
| M11 | 论文下载 API 返回出版商浏览器后备请求时，后台浏览器继续获取正文或补充文件 | **未实现**此独立通道。共享 `requestPaperPdfDownload()` 会调用 `publisherPdfDownload`，Windows bridge 未注册它。Browser → Save to Gewu → Get PDF 是另一条已实现流程，不能作为这项已完成的证据。 | `paper_monitor/ui_server.py` 的 `downloadPublishedPdfInBackground()`；`windows/workspace.js`；Mac `PaperMonitorApp.m` 的 `publisherPdfDownload` |
| M12 | Library 文件夹向外拖出，以及 Library 条目原生拖动的完整接力 | **部分实现**。Windows 当前提供 Paper Files 单文件 CF_HDROP，原生 `DragFile()` 只接受文件；没有接入共享页面的 `nativeFileDrag` 文件夹通道或 `libraryItemDrag` 通道。不能据此否定仍可用的普通 Web 内部拖动。 | `windows/NativeIntegration.cs`、`windows/workspace.js`；`ui_server.py` 的 `prepareNativeFolderDrag()` / `armNativeLibraryItemDrop()` |

M05–M12 最初由源码对照识别。0.1.12 对 M05–M08 的新检查见第 8 节；其余未完成项仍不能把源码分析写成实际用户操作结果。

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
| R03 | 安装与运行生命周期 | 同机多次安装升级、包内服务启动和数据保留已有记录；M08 已在 0.1.12 开发源码补齐并隔离验证。首次离线启动、全新机器、完整安装/卸载/恢复仍待验收。 |
| R04 | 正式发布和完整手册 | 当前为未签名 Preview；本机 Windows 11 x64 已测，Windows 10、ARM64 未验收。Windows HTML/PDF 简明指南已有；完整 Windows 实机截图与全功能手册仍待补齐。 |

## 7. Mac 后续新增修改的追踪台账

**固定起点永远保留为 `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`。本次已核对并三方合入其后至 `2a123205ad0c13a8a1fdec4cdb4157d6bb0b5b42` 的 8 个提交。** 此前 Windows 分支首次推送没有移植这些变化，也没有改变任何既有远端分支；那是历史操作。本次用户明确要求同步，已获取并检查远端，但仅修改本地 Windows 工作树，没有新的 commit/push。0.1.11 的后端、MCP、headless UI、升级副本及本机正式安装/启动/重开已验证；原包放行后的恢复与仍待完成的签名工作详见 [Windows Preview 状态](WINDOWS_PREVIEW_STATUS.md)。

| 追踪字段 | 当前值 |
| --- | --- |
| Mac 原始迁移基线 | `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d` |
| 后续 Mac 增量已检查到 | `2a123205ad0c13a8a1fdec4cdb4157d6bb0b5b42`；8 个提交已合入，Windows 0.1.11 已安装并正常启动/重开 |
| 已完整适配并验收的 Mac 截止提交 | 尚无；基线缺项保留。0.1.11 本机安装/启动和 AI Access 首屏已验证，不能替代完整功能验收 |
| Windows 当前版本依据 | 已安装并运行 `0.1.13`，文件/卸载登记版本一致，2109 个 payload 文件匹配；仍未签名 |
| 独立提交目标 | 仅 `refs/heads/codex/windows-preview-0.1.10-20260910`；不合并、推送更新或覆盖 Mac `main`，不创建合并到 Mac 的 PR |
| 已发布 Windows 源码快照 | `59fa205c3037db0c387d9456cb8d0cc3a4370b51`；后续仅记录发布结果的文档提交不代表新安装版本 |

后续每次同步，应保留当前 Windows 改动，以原始/上次对照基线、Mac 新源码和 Windows 当前源码做三方比较，逐项填写下表；仅检查过某个提交，不代表已经完成适配。

| Mac 提交 / 对照区间 | Mac 功能变化与文件 | Windows 对应修改或无需修改的理由 | 状态 | Windows 版本 / 提交及实际验证 |
| --- | --- | --- | --- | --- |
| `af4fcf3` | Subject 历史、Add All Publications、标识补全、引用感知删除 | 共享模块合入；删除增加 Windows Shell/SQLite 恢复事务 | 源码及隔离流程通过；0.1.11 已恢复安装/运行，正式库 schema 18 | 0.1.11；335 项通过/18 跳过中的对应测试及 headless UI |
| `f961a49` | Subject 纯数字日历，移除星号与说明 | 共享 UI、测试及 AGENTS 规则同步；内部状态保留 | 同上 | Subject 历史/日历检查通过 |
| `d5cacfc` | Default PDF 主路径、Unknown 首份 PDF、PDF 按钮拖入 | 保留 Windows 预览和 .lnk 实现；共享身份/位置/拖入逻辑三方合入 | 共享流程通过，真实手势待验收 | 合成上传/保存/重复/回滚及 DOM 拖入检查通过 |
| `ac290ca` | AI Access/API/MCP、私有 UI 会话、schema 18 | Settings/原生请求适配，Windows 私有 DACL，包内脚本、UTF-8、重启端口跟随 | 服务/MCP/headless UI 通过；0.1.11 真实 AI Access 首屏与重开后认证服务通过 | 两次包内服务启动、PDF 读取、中文分析与幂等重试通过 |
| `520bc56`、`5151c04`、`3e1e50a` | AI 说明、32 张截图/102 页指南、Loader/Settings 布局 | Mac 参考指南及共享 CSS 更新；独立 Windows HTML/PDF 补充新功能与安装版配置 | Windows 指南与 headless 布局通过 | 3 页 Windows PDF 渲染检查；原生窗口待验收 |
| `2a12320` | Browser 标签禁止选字 | 共享 CSS 合入 | CSS 与目标提交一致，原生实际双击待验收 | 未恢复或改变正文/地址栏选字规则 |

维护规则：

1. 已推送到 GitHub 的修改按完整 SHA/提交范围追踪；Mac 上尚未推送的修改需要额外源码差异，不能假设已包含在远端。
2. 共用 Python/JS 修改评估是否可直接适配；AppKit/WKWebView 修改需映射到 WinForms/WebView2 的用户行为；Mac 专属变化记录理由。不得用整文件覆盖丢失 Windows 适配。
3. M/V/R 编号保持稳定。完成后更新状态、Windows 版本、对应源码与实际验证，保留历史边界；不要只删掉缺项。
4. 验证在隔离资料上进行；SQLite 是唯一事实来源，保留身份、Default、来源、文件关联及下载/分析状态。PDF 来源约束和 Subject Monitor 的 Zenodo 拒绝规则持续有效。
5. 只有功能已实现且相关 CLI/UI/原生流程实际通过，才标为完成；模拟输入、源码契约或 Mac 测试不能冒充 Windows 实机结果。提交与推送仍需用户明确要求。

## 8. 2026-09-10：0.1.12 本地开发对齐

- 开发阶段范围：M03/M05/M06/M07/M08。仍在独立 Windows 分支；该开发阶段没有 commit/push、Mac 分支更新、正式资料库写入、用户 App 关闭或覆盖安装。随后本机安装结果见下方重试记录。
- `tests/windows_browser_parity/` 编译真实 Windows 源码；独立隐藏桌面、虚构网页与临时 SQLite 的 **35 项检查通过**。包括实际原生候选控件、共享键盘路径、真实视口截图/blur、取消/缺图回退、原生子目录选择及重复同步，以及三次服务崩溃恢复和重试上限。虚构图标使用隔离 HTTP transport，未使用真实登录会话；不代替全部网站、实体输入法/DPI和用户安装验收。
- 共享后端 **84 项：78 通过、6 项平台跳过**；JS 语法、变更 Python 编译和 diff 检查通过。Windows 指南更新为 3 页并经 Poppler 渲染检查；没有使用生成页截图冒充原 App 指南截图。
- `dist/windows-preview-0.1.12/` 是未签名开发产物，包内 Python/UI/API/MCP 两次启动通过；独立 EXE 在隐藏桌面使用临时库、无开发运行时路径启动两次通过。该项只验证开发目录中的本机启动，不能承诺安装目录或其他电脑放行。
- 首次 sandbox 原生启动停在 WebView2 初始化，正常桌面权限复验通过；开发打包首次因网络限制失败，半成品保留在 `tmp/windows-parity-0.1.12/partial-network-build/`，正常网络权限重建成功。NuGet `NU1900` 漏洞索引不可达仍存在，不声称依赖安全审计通过。标准发布脚本的签名要求保留；随后按用户要求用临时本机未签名配方生成安装器，Windows 在执行前阻断该 EXE（3077/3033）。旧安装逐文件不变，0.1.11 已重开；无安全设置/外部审核变化。备份与恢复核对见 `tmp/install-0.1.12-20260910/` 和 Preview 状态顶部。
- 后续用户要求重试安装：同一个未签名安装器本次允许执行，退出 0。2109 个实际安装文件匹配，安装目录 EXE 在临时 Library 连续两次启动通过，原库正常关闭/重开通过，窗口可见且四项 API 与 Browser JS 哈希通过。44 篇 papers 和受保护研究/书签/历史行不变，17 个持久研究/缓存文件不变，schema 18 integrity/FK 通过；仅两项自动监控状态设置随启动更新。新备份/安装/重开证据：ignored `tmp/install-0.1.12-retry-20260910/`。Smart App Control 仍 ON（1），没有保护/信任/外部复核变更、重新构建、commit/push；放行变化原因未知。
- 开发证据：ignored `tmp/windows-parity-0.1.12/latest-native-result.json`、`payload-native-result.json`、`package-check/`、指南渲染；原生截图只含生成的测试页面。完整未对齐项 M01/M02/M04/M09/M10/M11/M12 继续保留。
- 快照 API 依据：[Chromium Page.captureScreenshot](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)。实际输出和交互以本机检查为准。

## 9. 2026-09-10：0.1.13 Browser 导航、快捷键及页面操作

- 在独立 Windows 分支完成开发和本机安装，未 commit/push 或改变 Mac 分支。本轮对齐本地已保留的 Mac 实现（增量此前核对至 `2a12320`），没有宣称拉取了新的远端 Mac 更新。用户原有工作树修改保留。
- M09：Home 是内存逻辑记录，网页条目引用 Chromium history ID；Back/Forward 调用原生历史，不重建 GET。显示 Favorites 直到新正文提交，取消/失败保留 Home；页内导航、历史分支、旧条目淘汰、迟到回调和关闭标签有边界保护。NewWindowRequested 直接提供目的 WebView，保留原始 POST 与 opener。
- M10：页面焦点下 Ctrl+L/F/D/T/W/R 与 Ctrl+[ 接通。只有本窗口、选中且可见的网页、无模态窗口/菜单时接管；不接管额外修饰键。Up/Left 原事件照常交给网页，隔离世界只读边界几何，输入/iframe/PDF/自定义控件拒绝交还；最多一个在途探针，迟到结果不改变焦点。
- M04：Share 菜单含 Add Bookmark、Copy Link、Save Download、Open in Default Browser；工具栏 Save Download 使用同 Browser profile 的独立视图，流式暂存原始 HTTP 响应（64 MB/2 分钟限制），然后系统 Save 对话框选择位置。先完成同目录临时写入再替换目标；取消/异常清理自身暂存，不改变源标签或 Library。PDF/二进制与伪装 PDF 必须来自核实来源，重定向/public URL 限制和独立 workspace token 边界保留。
- 最终 **80 项隐藏原生检查通过**：实际 WebView2 历史与草稿、取消/迟到、页内分支、popup opener/POST、Win32 消息 Ctrl+L/F/[ 与 Library 返回、四项原生菜单、HTML/PDF 原始字节/允许重定向、未核实/本地重定向/伪装/超限拒绝；并回归 0.1.12 的书签、建议、快照、三次服务恢复及重试上限。所有页面、资料库及下载响应为隔离测试数据；不是实体按键、用户网站登录或完整 Save 对话框验收。
- 共享 **134 项：125 通过、9 项跳过**；最初未开启 UTF-8 的运行出现 GBK 解码错误，修正运行环境后通过。最终 .NET 编译、JS 语法、Python 编译和 diff 检查通过。Windows HTML/PDF 同源指南为 4 页，全部 Poppler 渲染并检查；未新增或伪造原 App 截图。
- `dist/windows-preview-0.1.13/` 为标准脚本生成的未签名开发包；开发阶段先验证包内服务/API/MCP 两次启动、中文分析幂等和数据库重启完整性，以及独立原生 EXE 双启动。随后使用临时本机安装配方生成安装器并安装，正式 SQLite、文件与 Browser profile 未用于功能测试。
- 早期测试遇到 sandbox WebView2 初始化阻塞、WinForms/Win32 焦点差异、测试初始 Library 载入竞争，以及虚拟文件映射不支持 POST；分别在隔离正常权限环境或修正测试/实现后复验。一次中间测试 DLL 被应用控制拦截，原文件重试仍阻断；随后实际功能修订的最终源码检查获准运行。没有修改系统防护、信任或外部复核，不推断放行原因。
- 安装结果（18:47 JST）：2317 个备份文件已校验，安装退出 0、无需 Windows 重启；2109 个清单内 payload 文件匹配，实际安装目录 EXE 在临时 Library 连续两次启动通过。原库正常关闭/重开后窗口可见，版本登记 0.1.13，四项 API/Browser JS 哈希通过；44 篇 papers 与所有受保护资料/书签/历史行及 17 个持久研究文件不变，schema 18 integrity/FK 通过。仅两项自动监控状态设置随重启更新。证据：ignored `tmp/install-0.1.13-20260910/`；本机仍未签名、Smart App Control ON（1），标准签名门槛不变，没有防护/信任/外部复核或 commit/push 变更。
- 证据：ignored `tmp/windows-parity-0.1.13/`；API 依据：[Chromium 原生历史](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-getNavigationHistory)、[响应流读取](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#method-takeResponseBodyAsStream)。M01/M02/M11/M12 和第 4–6 节的真实环境验收仍待完成。

## 10. 参考记录与本次核对范围

- [Windows Preview 状态](WINDOWS_PREVIEW_STATUS.md)：各版本实现及实际验收记录，是本表验证状态的主要来源。
- [Windows 迁移审计](WINDOWS_MIGRATION_AUDIT.md)：原始基线、产品范围、历史方案与平台边界。
- [Windows 工作目录搬迁](WINDOWS_WORKSPACE_RELOCATION.md)：已完成的本机目录搬迁及数据边界。
- [项目交接状态](../PROJECT_STATE.md)：当前项目入口；其中 Mac 段落含历史记录。
- 本次源码核对：`windows/Program.cs`、`BrowserCapture.cs`、`BrowserDialogs.cs`、`NativeIntegration.cs`、`workspace.js`；`paper_monitor/browser_ui.js`、`ui_server.py`、`desktop_files.py`、`windows_recycle.py`；本地 Mac 参考 `scripts/PaperMonitorApp.m`、`GewuBrowserController.m`。
- 首次建档仅新增记录并在项目交接中加入入口，未运行功能测试或提交。后续 Windows 独立提交的检查单独记录在 [Preview 状态](WINDOWS_PREVIEW_STATUS.md)，不能将其当作 Mac 新增功能已同步。
