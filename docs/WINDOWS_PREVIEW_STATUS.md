# Windows Preview — 实现与验收状态

## 2026-09-10：0.1.11 Windows 分支提交验证

- 用户明确授权 commit/push，目标仅为 `codex/windows-preview-0.1.10-20260910`；不向 `main` 或其他 macOS 分支推送。本次提交包含现有 0.1.11 产品源码、指南、签名防护和测试，资料库、研究文件、安装器、诊断产物及备份仍只保留本地。
- 对 20 个变更测试模块重新执行 333 项：331 通过，2 项因需要 macOS Cocoa/WebKit/xcrun 或 POSIX `cksum` 跳过；69 个 Python 文件编译与 6 个 JavaScript 语法检查通过。修正了测试对 `cksum` 和 README 平台说明的旧假设；不是全仓库测试。现有 UI 字符串的 `\s` SyntaxWarning 仍存在。
- 签名工具的 5 项防护断言全部通过，包括保留已有有效签名、拒绝无效签名和缺失发布凭据、含特殊字符的 Inno 回调，以及签名失败时禁止产出安装器。负向测试的 Inno 退出码 2 为预期结果；没有真实发布凭据，也没有声称完成发行签名。
- 52 个源码、资源和 Windows 指南文件逐一匹配已安装的 0.1.11；本轮只增加测试兼容性与状态记录，没有重建或改动正式安装。此前原安装位置的真实启动、正常关闭重开与打包 MCP 检查见下文。验证记录保留在 ignored `tmp/windows-push-0.1.11-20260910/`。

## 2026-09-10 16:07 JST：按用户确认删除 3159 条未收藏论文记录

- 用户明确要求删除此前 3203 条中的其余 **3159 条**，保留关联 Publications、Library 或研究文件的 **44 篇**。原生应用正常关闭后，对正式 schema 18 数据库作独立备份，并备份/核对 11 个受管及引用文件；先在数据库副本验证同一删除事务，再应用于正式库。
- 仅删除明确列出的 3159 个 paper_id，并按现有 SQLite 外键规则移除其监控结果、来源观察、已读状态等关联记录。44 篇完整论文行、39 项 Publications、8 个 Library 条目、5 个文件夹、4 项 resources 均逐行不变，文件字节与选择的工作区不变；所有表的最终变化均与事先计算的级联结果一致，integrity_check OK、外键错误 0。
- 取消 3 项属于被清理 Subject 窗口的旧重试记录，同步剩余重试数为 0，避免旧任务立即补回这些记录。保留监控配置、历史 fetch_runs、正常每日监控机制和手动刷新功能；这次是既有记录清理，不是永久禁止未来获取论文。没有删除研究文件、报告、浏览器配置或历史备份。
- 0.1.11 正常重开后仍恰好为 44 篇，全部 3159 个删除 ID 均不存在；保留的论文/资料表与 11 个文件再次核对一致。真实 Library 原目录和条目可见，health、认证工作区、Library bootstrap、My Publications 均返回 200。当前 App/服务为 35068/27072；程序仍使用原安装目录和原研究库。
- 记录及恢复资料保留在 ignored `tmp/paper-cleanup-3159-20260910/`：`before.sqlite`、研究文件备份、`plan.json`（精确保留/删除清单和摘要）、`trial-result.json`、`result.json`、`reopened.json`。只执行了用户批准的数据清理和本地状态文档更新；没有产品源码/安装包改动或 commit/push。下方 3203 篇的数字是清理前安装核对的历史状态。

## 2026-09-10 15:48 JST：0.1.11 已恢复启动并通过正式重开

- **当前安装和运行均为 0.1.11**。15:37 JST 直接复测此前受阻的原始 DLL，在隐藏桌面、独立临时库中成功启动。随后用原安装器恢复正式安装目录，退出 0；2109 个程序文件逐一匹配原包。实际安装位置的隔离启动和认证工作区也通过后，15:43 JST 打开正式库，正常关闭并再次打开成功。真实 About 显示 0.1.11，Library 原目录/文件可见，Settings → AI Access 正常打开，保持 Disabled、无连接。最后留在可响应的 Library 窗口。
- Smart App Control 一直为 1（开启）；DLL 仍未签名，SHA-256 仍为 `F7E53BDE8D88469F96BC51264720B6E28493460EC49ED8E830E5EC58E09349B4`。没有重新编译、修改二进制、签名、外部复核、证书信任或防护设置改动。当前放行结果已实测，但现有证据不能说明同一文件为何由阻止变为允许，也不能承诺其他电脑或后续构建一定获准。正规发布签名仍待真实凭据。
- 恢复前完整备份并核对 2083 个旧版/研究文件；旧版正常运行期间仅自动监控的三个状态设置发生变化，关闭后另存 `before-launch.sqlite` 静止检查点。新版打开前，26 张原有表和 10 个研究文件均与该检查点/备份一致。首次正常启动将 schema 16 升至 18，新增 7 张工作流/AI 表；原 papers、Publications、Library、资源内容保留，仍为 **3203 papers / 39 Publications / 8 items / 5 folders / 4 resources**，10 个原研究文件哈希和工作区选择未变，integrity_check OK、外键错误 0。
- 正常自动监控随后新增 2 条 fetch_runs；194 条旧记录不变。3 张监控表仅 `last_seen_at`、`fetched_at`、`searched_at` 更新时间戳，其余字段逐行相同；另有三个监控状态设置变化。其余 21 张既有表逐行摘要相同。不能把正常运行后的数据库描述为全表字节不变，也没有为了验证而修改正式库或重新导入资料。
- 原包服务在合成库中连续两次启动，工作区/指南/API、跨站拒绝、MCP 读合成 PDF/中文分析/重复保存、原配置跟随重启端口和 SQLite 完整性通过。正式两次启动后 health、认证工作区、Library bootstrap、AI Access 资源/API 均 200，跨站访问 403；真实窗口和版本另经 Computer Use 核对。没有新建正式 AI grant、执行用户资料写入测试或重复全部功能验收。早期诊断探针误用 `/ai-access-ui.js` 标记而返回 false；产品实际路径是 `/ai-access.js`，正式两次检查均确认存在且可访问。
- 本轮仅更新状态文档；未改产品源码、重建安装包、commit/push 或改动远端 Mac 分支。`tmp/reinstall-0.1.11-20260910/` 保存完整旧版/资料备份、安装日志、`after.json`（启动前）、`installed-native-check.json`、`service-check/result.json`、`running-first.json`、`running-restart.json`、`native-running.json`。此前的旧版、新版受阻目录和备份均保留；正式库现已为 schema 18，不能未经迁移评估直接降回旧版使用。

## 2026-09-10 15:14 JST：本地恢复 0.1.10 可用性

- 用户禁止外部复核；没有提交文件，复核草稿已取消。只在本机检查未修改的 0.1.10 备份，DLL 哈希 `1B98B35D6792B1D9477F2DBF336DBB5E0A18765C6D360C8079C9EE013EBEFC97`。在独立隐藏桌面、空白临时库、自动监控关闭的环境下，原生启动和服务 health 通过；测试进程树随后关闭。测试脚本最初遇到 Windows API 空名称参数错误，修正后才执行成功，不将该失败计为通过。
- 为恢复应用可用性，先对当前 schema 16 库作在线备份，再把完整受阻 0.1.11 安装目录移入项目 ignored 备份目录。源和目标绝对路径已验证，未删除文件。用原 0.1.10 安装器恢复原安装位置，退出 0；安装器 SHA-256 `19CFA991453E2E650FAFC9298AFBD8C4EB1C4E1E48F907465D662AAEF3C22E04` 与历史发布记录一致。
- **当前实际安装和运行版本为 0.1.10**。2070 个非缓存 payload 文件逐一匹配；重新打开前，26 张数据库表逐行摘要与最新备份一致，10 个研究文件字节不变，quick_check OK：3203 papers / 39 Publications / 8 Library items / 5 folders / 4 resources。没有对数据做降级或重新导入。
- 重新打开实际安装 App 后，显示正式窗口 `Gewu Insight — Windows Preview`，响应正常；其子服务明确使用原库 `%USERPROFILE%/Gewu Insight Preview/data/paper_monitor.sqlite`，health 和 workspace 均为 HTTP 200，没有新增对应 CodeIntegrity 拦截。首次后台启动隐藏了正式窗口，随后仅按进程和准确标题显示该产品窗口；没有显示测试面板。
- `tmp/local-restore-0.1.10-20260910/` 保留本轮在线数据库备份、完整 `blocked-install-0.1.11/`、安装日志、`verified.json` 和 `running.json`；旧备份、新版源码及 dist 安装包也保留。**这是临时恢复，0.1.11 Mac 同步版的启动阻塞仍未解决。** 没有修改系统防护、证书信任、专有许可或远端分支。

## 2026-09-10：许可已澄清，用户拒绝外部复核

- 用户随后明确要求“不要外部复核”。未上传或提交任何样本；本地复核草稿已标记取消。不要再次推进或反复请求同一项外部提交批准。后续仅作本地诊断与恢复检查，保留免费使用/专有许可的选择。

- 用户明确选择“免费使用，保留专有许可”。保留 LICENSE 和 README 的专有授权，不继续申请仅面向开源项目的 SignPath Foundation，也不自动改为 MIT 等开源许可。
- 已核实微软 Security Intelligence 官方提交页面支持 Smart App Control，可按被误拦截的正常程序请求文件复核。准备了实际安装 DLL（215040 字节，SHA-256 `F7E53BDE8D88469F96BC51264720B6E28493460EC49ED8E830E5EC58E09349B4`）、1671 字符英文说明和用户审阅说明，位于 ignored `tmp/microsoft-sac-review-0.1.11/`。
- 尚未上传或提交。发送专有程序文件给微软分析需用户明确确认；样本不带研究资料库、论文、笔记、凭据、浏览器配置、独立源码/PDB，但编译 DLL 本身含产品代码/资源/构建元数据。微软条款说明分析数据存储于美国；登录或验证码由用户完成。复核结果和时长不能保证，现有 0.1.11 启动阻塞仍未解决。
- Store MSIX 经认证后由微软重新签名也是适用于专有软件的正规分发路线，但需要开发者账号、打包和提交流程，本次未创建账号、构建 MSIX 或发布产品。详见 [签名与复核说明](WINDOWS_SIGNING.md)。

## 2026-09-10：正规签名修复准备（尚缺发布者凭据）

- 用户随后明确意图是免费开源软件。已核实 SignPath Foundation 对符合条件的开源项目提供免费签名；不将付费个人/公司证书当作唯一途径。但当前 `LICENSE` 和 README 明确为 proprietary、非开源，尚不满足该项目的开源许可条件，已请求用户澄清，未修改授权。Foundation 禁止用项目证书重签第三方代码，现有逐文件本地签名脚本不能直接当作 SignPath 集成。免费路线、资格和待办见 [签名说明](WINDOWS_SIGNING.md)。
- 用户要求解决启动问题并强调必须合法。查明旧、新包均使用相同 .NET 10.0.11 与打包方式；旧版也未签名，未将云端信誉推测写成旧版获准的确定原因。用户 11:50 的两次启动仍有 CodeIntegrity 3033/3077 与 .NET 1026，程序在窗口创建前退出。
- 实际包扫描 375 个 EXE/DLL/PYD：300 个有效 RSA 签名，75 个未签名。微软 SDK SignTool 独立验证自身签名有效、已安装 Gewu DLL 无签名。保留已分发依赖许可证文件；没有改动第三方代码、用户资料、系统安全设置或证书信任库。
- 新增 `scripts/windows_signing.ps1` 和 Inno 签名入口；构建安装器必须提供真实发布者的证书或 Microsoft Artifact Signing Public Trust 配置。逐个签署未签名二进制、保留有效上游签名、拒绝覆盖无效签名、检查 RSA/SHA-256/时间戳、签名后生成摘要；Setup 与卸载器同样签名。见 [签名说明](WINDOWS_SIGNING.md)。这不会自动修复已经安装的无签名 DLL。
- PowerShell 语法与无凭据提前终止检查通过；真实包严格检查准确拒绝 75/375 项。隔离检查验证有效供应商文件字节不变、受损签名不被重签覆盖、缺失证书被拒绝，以及带空格/美元符路径的真实 Inno 回调因缺少证书退出 2、没有产生可安装 Setup。检查不使用真实私钥，未声称真实签名成功；完整签名及正常启动验收仍待真实凭据。
- 本机两个个人证书库均无代码签名证书。已向用户询问是否有证书或已验证签名账号，尚未收到回答。身份验证、费用和任何外部提交需发布者参与；未注册、购买、上传、发布或 commit/push。0.1.11 保持已安装但无法运行，旧版和资料备份仍保留。

## 2026-09-10：0.1.11 Mac 更新同步版（已安装，启动被系统阻止）

- 用户要求同步 Mac 远端的 8 个更新；范围固定为 `57a8b2d..2a123205ad0c13a8a1fdec4cdb4157d6bb0b5b42`。源码在原 Windows 分支 `codex/windows-preview-0.1.10-20260910` 上做三方合入，保留 Windows 预览、回收、文件关联、正版 PDF 下载限制和界面文案。没有 commit、push、切换或改写 Mac 分支。用户原有未跟踪迁移附件未修改。
- 新增 AI Access/API/MCP、Subject 关键词修改历史保留与纯数字日历、可暂停/继续/重试的 Add All Publications 与标识补全、引用感知的 My Publications 删除、Default PDF 物理位置同步与首份 Unknown 文章 PDF 后备选择、PDF 按钮拖入修复、Browser 标签不可选字。Mac 原生源码与手册作为参考同步；Mac `.app` 二进制未替换或作为 Windows 发布。
- Windows 适配：AI Access 接入原生 Settings；首次工作区导航和原生 Naming Rule 请求携带独立私有会话，HTTP 客户端禁止重定向。工作区 token 文件由 Windows DACL 限制到当前所有者。远程 Browser 继续使用独立 profile，不收到该会话。安装包包含 MCP 脚本；生成配置使用包内 Python，并通过仅含 loopback URL 的 `.gewu-api-url` 导出跟随 App 重启后的端口。中文 MCP stdio 明确使用 UTF-8；PDF 解析子进程无控制台窗口。
- My Publications 私有受管文件删除接入既有 Windows Shell 回收与 SQLite 恢复日志；以主库 canonical paper 的删除提交为准，支持多文件失败恢复和启动恢复。共享引用、外部原件及 Library Recycle 批量永久删除的既有边界保留。
- 最终 34 组隔离 Python 检查共 **353 项：335 通过、18 跳过**（41.444 s），包括真实 Shell 的原有单资源及新增 Publications 成功、SQL 失败和中断恢复。49 个 Python 文件编译、6 个 JS 文件语法及 `git diff --check` 通过。保留原有 `ui_server.py` 的 `\s` SyntaxWarning。早期失败包含 sandbox Shell 拦截、Windows ACL 适配错误和两个测试的 Mac/接口形状假设；均已修正或在正常桌面隔离环境复验，未把失败运行称为通过。
- Headless Edge：AI Access 三宽度、目录选择、权限、创建/清除/撤销、启停、焦点刷新；Publications/Subject 状态控件；PDF 按钮优先、替换后目标、权威文件快照、忙碌/多文件/误投；既有 Windows 剪贴板回归均通过。AI probe 的初始文件请求等待已修正，避免把启动请求误算为 AI 焦点刷新。
- 最终包的 embedded Python 服务连续两次启动，工作区/API/指南和跨站拒绝、MCP 初始化/工具发现/读合成 PDF/写中文分析/重复保存均通过；第二次复用第一次生成的配置，端口变化无需重配。SQLite 重启完整性通过。未连接用户实际 AI 客户端、没有新建正式 AI grant 或导入测试资料到用户库。
- 用户库在线备份后，只在第二份副本上执行 schema **16 → 18** 升级；原有 **26 张表逐行摘要一致**，新增 7 张工作流/AI 表，quick_check 正常、外键错误 0。备份时为 3203 papers / 39 Publications / 8 Library items / 5 folders / 4 resources。原库没有升级或修改。私人副本和摘要在 ignored `tmp/mac-sync-2a12320/migration/`。
- Windows HTML/PDF Guide 已同源补充本次研究更新与安装版 MCP 配置，PDF 3 页均已渲染检查。上游 102 页/32 图 Mac 参考手册保留；Windows Help 仍打开独立 Windows 指南，不冒用 Mac 截图。
- **11:41 JST 的安装已完成，原生启动被系统阻止。** 用户明确要求执行安装；先备份原安装、在线 SQLite、受管资料/报告和工作区选择，共校验 2083 个备份文件。安装器退出 0，无需重启，覆盖原目录 `C:\Users\Zhengran\AppData\Local\Programs\Gewu Insight Preview`；当时注册表 DisplayVersion 为 0.1.11，DLL FileVersion 为 0.1.11.0，2109 个正式 payload 文件逐一哈希一致（排除可重新生成的 Python 字节码缓存）。后续 15:14 JST 已恢复 0.1.10，见本页最新记录。
- 11:42 JST 启动实际安装 EXE 时，`Gewu Insight.dll` 在服务启动前被 Windows Code Integrity 拦截（事件 3033/3077，`0x800711C7`，policy `0283ac0f-fff1-49ae-ada1-8a933130cad6`）。该 GUID 对应 [Smart App Control 的 VerifiedAndReputableDesktop 策略](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/inbox-appcontrol-policies)，本机状态值为 1。旧、新 DLL 均未签名，新版没有 Zone.Identifier；不能仅凭日志中的 Enterprise signing level 推断企业管理。当前用户没有可用代码签名证书；[微软说明](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)推荐给应用添加有效签名，且不支持单独放行一个应用。没有关闭或更改系统防护。需可信签名途径后继续原生菜单、认证首屏、预览及会话抓取验收；目前没有运行中的新版 App 或服务。
- 安装后只读核对原资料库：schema 仍为 16，26 张既有表逐行摘要与安装前一致，quick_check 正常；3203 papers / 39 Publications / 8 Library items / 5 folders / 4 resources 保留，受管研究文件和工作区选择的字节不变。完整安装备份、研究数据备份、安装/启动日志和 `after.json` 在 ignored `tmp/install-0.1.11-20260910/`。安装不等于启动通过，之前版本的原生验收不替代本版。
- 构建成功，仍有 NuGet 漏洞索引不可达的 NU1900 警告。安装器 `dist/installers/Gewu-Insight-Windows-Preview-0.1.11-x64-Setup.exe`，SHA-256 `4F69464B32568FBF7D83BE9774CA6D3CA944B5E03DF3474B5CFB16F3648712D1`。这是已按用户要求本机安装、但启动受系统阻止的预览包，未发布。原检查日志/截图在 ignored `tmp/mac-sync-2a12320/`；旧包与正式资料保留。

## 2026-09-10：Windows 独立分支提交检查

- **已完成**：Windows 源码提交 [`59fa205c3037db0c387d9456cb8d0cc3a4370b51`](https://github.com/LKong92/Gewu-Insight/commit/59fa205c3037db0c387d9456cb8d0cc3a4370b51) 已推送至新分支 [`codex/windows-preview-0.1.10-20260910`](https://github.com/LKong92/Gewu-Insight/tree/codex/windows-preview-0.1.10-20260910)。实际推送前 Mac `main` 已更新为 `2a123205ad0c13a8a1fdec4cdb4157d6bb0b5b42`；推送后全部既有远端分支与即时推送前完全一致。只创建了 Windows 分支，未创建 PR、合并或强推。
- 用户明确要求提交 Windows 版并推送至全新分支，绝不能混入远端 Mac 版。目标为 `codex/windows-preview-0.1.10-20260910`；原始源码基线仍为 `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`，不合并 Mac 后续提交，不向 `main` 推送，也不创建合并到 Mac 的 PR。
- 准备阶段只读查询确认远端 `main` 为 `3e1e50aaffd0822fe9f74df70e07f282daae8adb`，新 Windows 分支尚不存在。后续 Mac 源码差异未检查或移植；详见 [基线与功能差异记录](WINDOWS_MAC_PARITY_TRACKER.md)。
- 本次重新运行 18 组隔离 Python 检查，共 260 项：258 通过、2 项 macOS 专用跳过，包含 4 项真实 Windows Shell 回收恢复检查。隔离服务健康检查和全部主要区域标记通过；自动 Monitor 关闭，未使用用户研究库或浏览器配置。
- 32 个 Python 包文件编译、3 个 JS 文件语法和可执行剪贴板回归通过。`ui_server.py` 原有 `\s` SyntaxWarning 仍存在。现有 0.1.10 包的服务在隔离数据下连续启动两次，API/指南、跨站拒绝和 SQLite 重启完整性通过。
- 最初沙箱检查因无法读取包内 `bs4` 文件而失败；正常桌面环境的隔离复验通过。WindowsApps 下 Node 执行也被权限阻止，改用已有用户目录 Node 后语法与剪贴板检查通过。没有修改安全设置。
- 这是当前 Windows 源码快照及既有安装包的提交前复核。本轮没有更改产品运行代码、重新构建/安装/重开用户 App，也没有重复全部原生 UI 验收；原有 0.1.10 安装、哈希与界面证据保留如下，功能仍未完整对齐 Mac。
- 提交范围为产品源码、构建/安装脚本、Windows 指南、产品测试及维护文档；安装器、runtime/SDK 缓存、临时检查日志、正式 SQLite/资料、benchmark 和含历史聊天的原始迁移附件留在本地。

## 0.1.10：Windows 文案与入口整理

- 按用户确认的 10 类文案统一 File Explorer、Destination Folder、List view、Preview/preview settings、Windows Recycle Bin、Loader folder structure 和通用书签 HTML 导入错误。Space 错误使用 local files/local folder；移除 Windows Library 文件夹尚未接通的拖出提示。应用内 Recycle 名称、真实 macOS 导入/迁移说明、已正确适配的 Default App/Default Browser/Preview Settings 与快捷键保留。
- Windows Browser 不创建 Open Passwords 按钮（包括无障碍名称），书签菜单不创建 Sync from Safari；macOS 原入口保留。Sync from Chrome 仍按当前能力禁用。本次只整理文案和入口，没有修改预览、删除、下载、拖动或资料模型的执行路径。
- 117 项相关 Python 检查通过，31 个 Python 文件编译、Browser/生成页面 JS 语法、diff 检查通过。隔离 Edge 无界面渲染核验 Windows 隐藏入口、macOS 原入口、预览设置保存、文件夹提示，无页面 JS 错误；共享 macOS HTML 文案保留。测试未使用原资料库。Windows HTML/PDF Guide 同源更新，两页均渲染并视觉检查；Help 继续直接打开安装目录中的 Windows 手册，既有 `/user-guide` API 仍为 macOS 参考手册。
- 自包含安装包服务连续两次启动、API/指南、跨站拒绝、SQLite 重启完整性通过。首次沙箱构建因依赖网络权限失败，半成品保留于 ignored tmp；正常桌面环境构建成功，NuGet 漏洞索引不可达仍有 NU1900 警告，不宣称依赖安全审计通过。
- 安装器退出 0，当前安装 `0.1.10+57a8b2d` 已正常重开。外壳、三份修改后的服务源文件及 Windows HTML/PDF Guide 哈希与包一致，运行服务 health 和页面文案通过。升级前后均为 2704 papers / 39 Publications / 8 Library items / 5 folders / 4 resources，quick_check 正常，工作目录仍为 `%USERPROFILE%/Gewu Insight Preview`。安装器 70,861,185 字节，SHA-256 `19CFA991453E2E650FAFC9298AFBD8C4EB1C4E1E48F907465D662AAEF3C22E04`。无 commit/push。

## 0.1.9：预览交互纠正与正版来源约束

- 移除 0.1.8 自行增加的页码、前后页、加减、Text 控件栏。PDF 使用稳定页尺寸构建连续文档，正文滚动容器限制在预览窗内，原生 wheel 可跨页；缩略图包含全部页，仅附近正文/缩略图加载像素，最多两项并发。捏合对应的 Ctrl-wheel 缩放 PDF 并保留指针下方位置，放大后可横向滚动。保留既有标题栏、Default App、缩略图和关闭入口。
- 默认 PDF 软件设置菜单未添加，遵循用户明确要求。现有 Open in Default App 仍使用 Windows 的 .pdf 关联。Get PDF 位置是 Browser → 网页/PDF → Save to Gewu → Details → PDF link 右侧；没有合格候选时禁用。
- 用户明确要求只下载正版 PDF。新增共用静态来源表 `paper_monitor/pdf_source_hosts.txt`，Python 普通下载/附件下载与 Windows Get PDF 使用同一表；下载候选、请求前与每次重定向都检查，未知来源停止，不把可访问、.edu 或搜索接口 OA 标签单独视为授权。Browser 普通 PDF/二进制文件下载也检查最终来源；本地用户选择不推断远程授权。来源表覆盖已核对出版商和授权学术库，不包含盗版服务、通用网盘或任意镜像。合法预印本可用；登录指用户已有的出版社/机构访问权限，不绕过订阅。未知来源表示未核实，并不等同于盗版。
- 后台透明 WebView2 检查通过：无额外工具栏、有界正文区、连续滚入下一页、Ctrl-wheel 仅缩放 PDF、横向滚动、240 页跳转、屏外像素回收、快速切换/Markdown、PNG、公开 W3C 官方 PDF 获取。没有显示测试栏；模拟浏览器输入不等同于所有实体触摸板型号验收。Python 200 项检查：198 通过，2 项 macOS 专用跳过；30 个包文件编译、JS 和 diff 检查通过。
- 0.1.9 安装器退出 0；外壳、服务、来源表和指南与最终包哈希一致，已重开用户原资料库。升级前后均为 2704 papers / 39 Publications / 6 Library items / 5 folders / 3 resources，quick_check 正常。最终包自带服务两次启动、API/指南/跨站拒绝和 SQLite 重启完整性通过。安装器 70,849,347 字节，SHA-256 `6EFA889D2A52F20BEA7B9C4BFE4AC2A953901861BEDD009BE9DC844B1F8EBFB5`。HTML/PDF Guide 同步，两页渲染检查通过；无 commit/push。
- 实际安装版打开原有 Nature Materials 45 页 PDF，额外控件栏已消失；原生滚动输入连续滚到第二页，第二页正文与跟随的缩略图高亮均可见，标题/Default App 入口保留。该观察验证实际安装窗口的滚动，不将模拟 Ctrl-wheel 检查冒称用户实体触摸板捏合已经实测。

## 0.1.8：阅读、会话 PDF 与单文件恢复

- Windows 专用 PDFium 按页预览替换该平台的 PDF iframe；支持 Page Up/Page Down、任意页码（已测第 240 页）、缩略图、缩放和当前页 Text。Up/Down 跟随 Paper Files，Space/Esc 开关。原文件只读，文件版本进入缓存键，内存最多 12 页/32 MB，切换和关闭取消过期请求。macOS 继续使用原预览路线，未恢复之前回退的方案。完整 PDF 搜索、链接、打印和批注仍通过 Open in Default App。
- 修复 Paper Files 丢失 MIME 信息导致 PNG 显示为不支持格式；路径文件名正确处理 Windows 分隔符。原生窗口验证 PDF → Markdown → text 的键盘切换；最新原生 harness 验证 PNG 实际像素加载和 PDF 快速连切后 Markdown 不被旧请求覆盖。
- `Get PDF` 已接上同一 Browser environment/profile 的隐藏 WebView2。原页面和标签保留；下载只接受当前快照候选，检查导航代次/取消/公共地址/重定向/90 秒和 64 MB 限制。读取浏览器收到的原始响应流，再以仅本机、禁止重定向的 token 上传至既有 capture 服务。后台仍验证 PDF 结构、身份、去重和手动 Default，只有 Save to Library 才入库。未读取用户凭据或导出 cookie。
- 实测定位并修正 WebView2 `GetContentAsync` 在内嵌 PDF 中返回 348 字节阅读器 HTML 的问题；改用 [Fetch 响应流](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#method-takeResponseBodyAsStream)，公开 W3C PDF 原始 13,264 字节成功暂存并通过后端 PDF-ready 校验。真实出版商、登录会话和跨站 cookie 策略仍需更广验收；不能称所有网站已支持。
- 文件图标/名称接上 OLE CF_HDROP，只提供 Copy，不提供 Move/Delete；仅可信工作区可发起，远程页面没有桥接。原生句柄启用 Windows 的 draggable；原生拖动延后至 WebView2 消息回调返回后开始，遵循其[禁止回调重入规则](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/threading-model#reentrancy)。跨应用实际复制尚未验收，不能称拖放完成。用户不接受临时底部验收栏，该窗口已关闭、对应测试栏代码已移除，正式包没有此界面。
- Paper Files 的非默认、非共享受管附件现在可进系统回收站。SQLite 主库事务是删除提交依据；私人 `data/.file-recovery/recovery.sqlite` 和已验证字节备份记录恢复进度。数据库失败恢复原文件，启动修复中断操作，同名已变更文件不会被覆盖。四项真实 Shell/临时库检查通过。Shell 恢复后条目已消失但底层 `$I` 文件可能保留；不修改系统 `$I/$R` 内部记录。正常删除后从系统回收站恢复的文件需要重新添加 Paper Files 关联。
- **Library Recycle 的批量永久删除仍禁用**：这次完成的是单一 resource 的事务，不能据此打开尚未适配的整论文/文件夹删除。后台服务自动重启、完整备份/整库迁移、Monitor Cache 和其余 Browser 功能仍在后续范围。
- 160 项相关 Python 检查：159 通过、1 项 macOS 专用跳过；另 4 项真实 Shell 恢复检查通过。原生 WebView2 harness 验证预览、240 页跳转、Text、快速切换/Markdown、PNG、元数据和公开 PDF 上传。合成文件首次测量约 479/117 ms，缓存重跑约 193–361/50–68 ms；不代表真实大论文，也没有 macOS 对照结论。29 个 Python 文件编译、JS 语法、diff 检查通过。
- 最终包自带 Python 连续两次启动，health/Library/设置/指南/JS、跨站 API 拒绝及 SQLite 重启完整性通过。安装器 70,845,350 字节，SHA-256 `D1894F52072C69B7145423553AF48ADE278930B41B4A68D35644EA36DEE02505`。最终构建无 NuGet 索引警告；早期测试项目 restore 有 NU1900，不能称已完成依赖安全审计。Windows HTML/PDF Guide 同步，两页渲染检查通过。
- 已正常关闭 0.1.7 并覆盖升级现有按用户安装目录，安装退出 0，无需重启 Windows。实际安装为 `0.1.8+57a8b2d`，关键外壳/服务/指南文件与最终包哈希一致，已重开正常产品界面。子服务明确使用 `%USERPROFILE%/Gewu Insight Preview/data/paper_monitor.sqlite`；升级前后均为 2704 papers / 39 My Publications / 5 Library items / 5 folders / 3 resources，quick_check 正常。原有 Nature Materials PDF（5.62 MB、45 页）通过 Space 打开、第一页正文/缩略图、Page Down 切到第二页、Esc 关闭的实际安装版核验。自动化和删除恢复使用隔离资料，原资料库仅作升级前后只读核验；无 commit/push。

## 0.1.7：任务栏旧图标入口修正

- 用户截图仍是带白底、主体偏小的旧图标。核对 0.1.6 实际 ICO 与 EXE 内嵌资源，二者已经是去白底的大标记；因此仅再次放大 PNG 不能解释或修复任务栏旧图。旧入口/缓存是基于这组差异的判断，不能冒充已直接读取任务栏缓存内容。
- 外壳在任何窗口出现前设置稳定 `GewuInsight.Windows.Preview` AppUserModelID；安装器开始菜单入口设置相同 ID，并明确指向新资源名 `GewuInsight.Taskbar.ico`。新资源复用已有无白底品牌图；不改变系统图标大小，不删除全局缓存、不重启 Explorer。
- [Windows 应用标识机制](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-setcurrentprocessexplicitappusermodelid)与 [Inno Setup 快捷方式参数](https://jrsoftware.org/ishelp/topic_iconssection.htm)支持该配置。ID 保持跨版本稳定，避免每次更新创建新分组。
- .NET 构建成功，隔离安装包服务两次启动、HTTP/API/指南、跨站拒绝和 SQLite 重启完整性通过。安装退出 0，实际快捷方式的 AppUserModelID、IconLocation、TargetPath 逐项核实。
- 0.1.7 安装器 SHA-256 `ACC189979F5FB13AF1E95530A09E36B0924B92C19171EFF188500E9298E640F5`。已重开，服务显式使用 `%USERPROFILE%\Gewu Insight Preview\data\paper_monitor.sqlite`；未修改资料库配置或做迁移。
- Computer Use 未直接取得任务栏截图；用户在更新后明确反馈「已正常，大小合适」，因此最终任务栏视觉大小由用户实机确认通过。现有 HTML/PDF Guide 功能和操作描述仍适用，本次无新截图或操作入口。

## 2026-09-09：资料库已迁出 Codex 缓存

- 当前正式使用目录已切换为 `%USERPROFILE%\Gewu Insight Preview`，软件仍为 0.1.6，无需重新安装。下方 0.1.6 事故记录中“尚未搬迁”的描述是历史状态。
- 离线复制并比较 869 个文件、27 张表，保留 2,574 papers / 39 My Publications / 4 Library items；只调整 7 处操作文件路径和 1 个受管 Explorer 入口。原库保留，额外 SQLite 备份及原选择保存在私人 `.gewu-insight/backups`。
- 12 项隔离 Windows 测试通过。首次副本因触发器导致缓存标记变化而被核验阻止，未启用；修正并覆盖回归后重新复制成功。schema、触发器定义、Default、论文身份及关联均保留，完整性正常，外键错误 0。
- 从 Codex 启动和从 Explorer 真实双击启动均传入同一新目录数据库；后者父进程核实为 explorer.exe。真实界面显示 test1/hermitian、hyppper、新路径 Paper Files/Default 和 39 Publications。应用留在 My Publications。
- 现有 HTML/PDF Guide 已说明用户主目录、显式选择和缺失库停止规则，仍与实际实现一致。本轮未改截图或安装包，未做跨盘/其他机器/卸载重装实机验收。完整过程与边界见 `docs/WINDOWS_WORKSPACE_RELOCATION.md`。

## 0.1.6：空库启动事故与恢复

- 用户正常重开后 Library/My Publications 为空。不能沿用 0.1.5 的“安装后可见”观察作为启动一致性结论。
- 只读证据：Codex 启动上下文访问逻辑 AppData 时，`GetFinalPathNameByHandleW` 返回 Codex Package 的 `LocalCache/Local` 物理路径；其中原库仍有 2,260 papers、39 my_publications、4 library_items、5 library_folders，quick_check 正常。错误运行实例的 API 则返回 20:32 新建空库。
- 先 SQLite 在线备份并备份受管资料文件，诊断和私人备份仅在 ignored `tmp/data-recovery-20260908`。未删除空库、未替换或重建原 DB、未重新导入；未修改已有文件路径。
- 外壳读取用户主目录 `.gewu-insight/preview-workspace.txt` 中已核实的物理根目录，独立于 AppData 重定向；显式 --workspace 测试覆盖不写该选择。当前选择仍指向找回的原库物理位置，并未实施数据搬迁。以后需要将该旧位置迁出 Codex 缓存时，必须另做文件与路径完整性验证，不能直接移动或清理原目录。
- 已选 DB 不存在则停止，不能静默创建空替代库；新用户默认位置在用户主目录 `Gewu Insight Preview`。检测到未确认的 legacy Library 时停止自动建库。File > Open Data Folder 显示实际位置，启动日志与子服务 --db 参数明确记录该位置。
- 真实窗口重新显示 test1/hermitian/hyppper 及 39 Publications。恢复后 library_folders/library_items/my_publications/resources 逐行相同，论文身份与存储路径相同，11 个原有资料文件 SHA-256 均不变，DB quick_check 正常。
- 0.1.6 安装器退出 0，SHA-256 `A539E8F81544B554A8BED160DA532CCE5F2302D5CF03157B9822123348AA6A2D`。从 Windows Explorer 中双击实际安装 EXE 后，子服务仍明确使用原库物理路径；不是只验证从 Codex 启动。独立临时库的两次 packaged-service 启动、API 边界、SQLite 完整性通过。
- HTML/PDF Windows Guide 已更正资料库位置说明，两页已渲染检查；无 commit/push。完整 macOS 功能对齐仍未完成。

## 0.1.5：Windows 交互与入库适配

- 本节为最新状态；下方 0.1.4/0.1.3 是历史记录，不能据其“未接通”清单判断当前版本。完整 macOS 功能对齐仍未完成。
- 图标从原始品牌图中去掉大面积灰白底与留白，生成 16–256 多尺寸 ICO；窗口使用该图标。印章在 Windows 页面内缩 16px、透明度 24%，完整显示，不再向右/向下裁切。
- Settings 改为 Preview Settings，实际移除 macOS Quick Look 两个选项；Windows 对话框使用右上角关闭按钮，Explorer/默认应用标签与快捷键提示按 Windows 命名。Help 不再展示 macOS 参考指南入口。
- 可信工作区 pointerdown/Esc 与原生 WebView 焦点接通菜单关闭。实际隔离窗口已验证点击空白处收起菜单、Preview Settings 仅显示受支持的内置预览。
- 原生文件夹选择器已接通 Loader；实际选择合成资料目录、Skip metadata、Import，报告 1 created / 1 resource / 0 missing，源资料与受管目录均在隔离 tmp。
- Explorer 文件拖入通过 WebView2 的实际 File additional objects 传路径，复用现有 Library/Loader 导入。仅可信工作区可发消息；不向远程网页开放桥接。代码已接通，跨窗口真实拖放尚未验收；拖出到其他应用尚未实现。
- Windows PDF 缩略图使用锁定版本 pypdfium2/Pillow，不再调用 sips。全部 PDFium 调用串行、PNG 原子缓存、原文件只读。真实窗口显示两页正文/缩略图，Space 打开、Esc 关闭并返回原文件焦点；大型文档和快速连续切换性能仍待验收，没有恢复被回退的 macOS 预览方案。
- Browser 在选中页面的隔离执行环境读取既有有限元数据探针；导航代次、页面 URL 和当前标签核对后才接收。来源论文仅作为 backend 上下文提示。远程网页仍无本地消息或通用文件/凭据桥接。
- **Save to Gewu 本机闭环通过**：公共 example.org（无文章元数据）→明确人工确认合成标题→匹配导入论文 Gewu Key→选本地合成 PDF→层级目标选 unsorted→保存显示 Existing PDF reused→Show in Library 定位同一 Key 的新位置。不是实际出版商文章抓取或登录会话 PDF 下载的全量验收。
- 网站会话 Get PDF 与自动 PDF 抓取仍禁用并说明本地文件方式。普通网页发起的下载保留。History 原生范围选择与确认已实现，核心范围删除测试通过；原生清除提交未执行，不能称 UI 删除验收通过。
- 本轮 59 项 Python 检查：58 通过、1 项 macOS 原生跳过；覆盖 PDF 真 PNG/并发/缓存/原文件不变、Windows 设置、capture 身份与资源边界、书签与预览设置。JS 语法与可执行剪贴板回归通过。安装包验证另行记录。
- 最终自包含构建成功；安装器 70,836,140 字节，SHA-256 `D83433E74515A0B21DC43BCDA44ECC56A59C67502EBC310233C5752CF7689633`。该次恢复 NuGet 无 NU1900 警告；不能将成功 restore 描述为完整安全审计。
- 最终包自带 Python 连续两次启动、health/Library/设置/指南/JS、跨站 API 拒绝、SQLite 重启完整性通过；包内 PDFium 实际输出 PNG。打包外壳正常重开隔离库，导入文件与 unsorted 新位置保留，Windows 右上角关闭按钮和完整印章视觉检查通过。
- 已正常关闭用户原窗口后覆盖升级按用户安装目录，安装器退出 0，无需重启 Windows。已打开实际安装版 `0.1.5+57a8b2d`，用户的 test1、hermitian 和 hyppper 仍显示；未重建数据库或导入测试资料到该库。该观察不替代全量数据恢复验收。
- HTML/PDF Windows Guide 已同步，两页已渲染视觉检查。产品未更改 schema/identity/Default 语义，用户资料库没有用于测试；无 commit/push。

仍需继续：会话 PDF 下载、实际出版商识别、完整浏览导航/弹窗/键盘、跨应用拖放、系统回收与失败恢复、Monitor cache、源书签同步、全量工作区/批注/Default 验收、旧库副本迁移工具、备份恢复与其他 Windows 机器发布验证。

## 0.1.4：本机试用反馈修复

- 安装包 `dist/installers/Gewu-Insight-Windows-Preview-0.1.4-x64-Setup.exe`，64,294,261 字节，SHA-256 `4A2854EA2F922FDB3DD801DC67A2372850611DAF64E5EEDECBD6CBA399992319`。以下 0.1.3 记录为历史验证；完整功能对齐仍未完成。
- Ctrl+V 根因：共享页面拦截 Ctrl+V 后调用 `navigator.clipboard.readText()`，Windows 外壳拒绝该权限，错误又被吞掉。Windows 可编辑文本现在保留浏览器原生复制/粘贴，不开放通用剪贴板读取权限；Ctrl+Shift+V 在可编辑框也不再切换 Library 视图。Library 位置复制/粘贴和 macOS 既有处理保持。
- 增加 Edit、View、Loader、About、Naming Rule 和 Quick Look Settings；其余设置采用 macOS 对应名称。Clear Monitor Cache 仍为 macOS 专用实现，Windows 菜单明确禁用；macOS Quick Look 的两个模式禁用并解释限制。接上菜单不代表 Loader 文件夹选择、所有设置持久化和所有编辑上下文都已验收。
- Windows 页面把 `Open in Preview` 更正为 `Open in Default App`，实际调用 Windows 文件关联；空格预览仍为应用内 WebView2 PDF iframe。未解决用户报告的数秒延迟，未恢复被回退的 macOS 方案。另发现 PDF 缩略图仍依赖 `sips`，Windows 返回后备页码卡，属于待适配缺口。
- 原有 PNG Logo 转为多尺寸 ICO，用于外壳和安装器；窗口图标已显示。右下角印章原有透明度 4%，Windows 专用样式调整为 10%，未改 macOS 显示。
- 实测：隔离原生窗口中输入合成文字，Ctrl+A/C、End、Ctrl+V 后出现两份连续文字；Settings 的完整当前列表和 Quick Look 限制实际显示；应用图标及印章视觉核对通过。7 项文件边界/预览设置测试、可执行 JS 剪贴板回归、Python 编译与 diff 检查通过。自包含服务两次启动、接口、跨站 API 拒绝和临时 SQLite 完整性通过。
- 构建曾受 sandbox 网络/包读取限制，授权的正常桌面环境构建与服务测试通过；NuGet 漏洞索引不可达的 NU1900 警告仍需后续恢复检查，不能声称漏洞审计通过。
- Windows HTML/PDF 指南已同步，两页重新渲染检查。测试没有写入用户资料库。
- 0.1.4 已覆盖升级正常按用户安装目录并重新打开，安装器退出码 0，运行版本 `0.1.4+57a8b2d`；实际 Library 仍显示用户刚创建的文件夹、Space 和论文入口。安装没有迁移/重建数据库；该观察不等于完整数据恢复验收。

用户目标仍是「可安装、功能与当前 macOS 一致」。本次产物是可安装的开发 Preview，是中间交付物，**尚未达到这个最终目标**。新 Windows Library 优先验收；旧 macOS 库只在副本上设计和验证迁移，尚未开放正式迁入。Explorer 的每个 Library/Space 位置必须有文件入口，这一要求保留。

## 基线与安装产物

- 工作分支 `codex/windows-migration`，基线 `57a8b2dcea77e97fd6b5acdd5e076c1aee61042d`，本轮没有 commit/push。
- 本机 Windows 11 x64 build 26200，WebView2 Runtime 152.0.4191.66。
- 安装包 `dist/installers/Gewu-Insight-Windows-Preview-0.1.3-x64-Setup.exe`；开发产物被 Git 忽略。SHA-256: `2C9EDBA17E7BE8BBDFCECC0201928840182B7729BDD4A543943808BCD21AFB2C`。
- Inno Setup 6.7.3 创建按用户安装包，`PrivilegesRequired=lowest`；默认应用目录 `%LOCALAPPDATA%\Programs\Gewu Insight Preview`。
- Python 3.13.15 官方嵌入式运行时，程序签名核对为 Python Software Foundation；依赖版本固定于 `windows/requirements.lock`。不要求用户另装 Python。
- .NET 10 自包含 WinForms 外壳 + WebView2 1.0.4191.47 SDK；不要求用户另装 .NET，仍依赖系统已有 WebView2 Evergreen Runtime。
- 包目标为 Windows 10 2004+ x64；仅 Windows 11 x64 有本机实测。ARM64、Windows 10、全新离线机器未验收。安装器/外壳本身没有发布签名。
- PyInstaller 原型曾构建成功，但本机应用控制拒绝执行其服务 EXE。已改为官方嵌入式 Python；没有修改 Windows 安全设置。旧 0.1.0 包不可作为交付依据。

## 本轮已实现

| 区域 | 实际变化 | 验收边界 |
|---|---|---|
| 文件位置 | 新 `desktop_files` 层创建有标记的 `.lnk`，同一真实文件在多个位置复用；识别失效/非受管入口，碰撞命名；旧 macOS symlink 分支保留 | 原子替换、中文/空格/特殊名与业务生命周期回归通过；跨盘、Explorer 双击和外部改名还需实测 |
| 文件操作 | Windows 默认应用打开普通文件/PDF；Explorer 选择文件或打开目录；Windows 保留名过滤；导出结果走系统默认应用 | 原生打开/定位全流程尚未全量实测 |
| 数据隔离 | `GEWU_WORKSPACE_ROOT` 分离源码与可写工作目录；数据库、文件、导入报告、分析、缓存跟随测试/用户工作目录 | macOS 默认仍为原 ROOT；没有更改 schema/identity/Default 模型 |
| 原生外壳 | 同一窗口显示完整共享 UI，独立可信 workspace 和远程 Browser profile；native message 按完整 origin 校验；远程页无 host objects/message bridge | 网络地址防护、网页弹窗/POST/会话仍须专项强化与验收 |
| Browser | 本地 Home/Favorites、保留每标签 WebView2、导航和下载事件；书签编辑、确认、HTML 导入/导出对话框；页内查找适配 | Save to Gewu、显式下载按钮、分享、源书签同步、History 范围清除未接通；相关入口禁用或明确报错 |
| 菜单/选择 | Settings 菜单复用已有设置窗口；Paper Files/Author Photo 原生文件选择；File > Library Loader 入口 | Loader 文件夹选择、完整菜单/键盘/拖放尚未完成 |
| 安装 | 自包含 runtime、明确 app/data 边界、独立工作区文件锁；升级与卸载保留数据设计 | 正式发布签名、完整异常恢复、不同机器依赖检查仍待完成 |
| 文档 | `Windows_Preview_Guide.html` 和 PDF 从同一生成器创建，Help 提供 Windows 指南；原 macOS Guide 明确标为参考 | Windows Guide 没有使用 macOS 截图冒充 Windows；完整操作截图随功能验收补齐 |

## 已有真实验证

- `test_library_file_ops` 37 项全部通过。原阶段 1 的 8 项 symlink 权限错误已通过实际 Windows placement 集成解决，没有靠 skip 掩盖。
- `test_windows_placements` 5、`test_windows_preview_boundaries` 3、`test_paper_resources` 54、`test_inventory_importer` 25、`test_inventory_path_safety` 2、`test_timezone_portability` 5、`test_browser_bookmarks` 11 全部通过。
- `test_browser_capture` 39 项运行，38 通过，1 项 macOS 原生测试按平台跳过。上述去重共 181 项，180 通过、1 跳过；不是整个产品测试集，也不是 Windows Browser capture 已接通。
- Python 32 文件编译、Browser JS 语法、`git diff --check` 通过。既有 `ui_server.py` 的 `\s` SyntaxWarning 尚在，未视为本轮编译失败。
- 安装版使用内置 Python 3.13.15 连续两次启动：health、Library bootstrap、Website Links 设置、主 UI、Browser JS、HTML/PDF Guide 返回 200；跨站请求 Library API 返回 403；SQLite integrity/foreign-key check 通过。0.1.1 与 0.1.2 分别执行。
- 实际安装目录 `tmp/windows-install-review`；不传源码路径、不传 Python 路径、不设置 DOTNET_ROOT，原生窗口成功加载 Library。Browser 的本地 Favorites 以及测试书签 https://example.org 的远程页面实际显示，窗口位置正确；原生书签编辑框能打开并取消。Windows 显示缩放下顶部标签拥挤问题已修复；书签对话框裁切已发现并修正，0.1.3 实际安装窗口视觉复验通过（标签和按钮无裁切）。
- 0.1.1 -> 0.1.2 实际覆盖升级成功，升级前隔离测试数据所有文件 SHA-256 在升级后保持一致；0.1.2 -> 0.1.3 也以相同方式复验通过。0.1.3 实际卸载成功，应用已移除；测试 SQLite 和独立保留标记共 2 个文件哈希均不变。该项不等于带真实大库的全量恢复验收。
- Windows Guide 两页均渲染并检查，修正了跨页孤立标题；源 HTML/PDF同步。
- 诊断留在 Git 忽略的 `tmp/windows-*`；没有正式研究库、论文、登录配置、API key 或 benchmark 进入安装包。

## 尚未完成的关键验收

1. **输入与完整交互**：自动化整段文本注入未成功，但物理单键 e 已在地址栏实际出现，UIA `set_value` 返回缓存属性错误。增加了原生激活/导航完成后的焦点交接，仍需实际输入复验；不能把 UIA 的问题直接判为产品正确或产品错误。Library/Monitor 表单、上下键、空格/Esc/返回焦点、菜单、原生拖放必须逐项验收。
2. **文件回收与恢复**：Windows 原生回收可以返回真实 `$R` 文件，但测试中普通移动及 Shell IFileOperation 恢复留下 `$I` 记录，ContextMenu 恢复尝试未通过。实验留在隔离 tmp，没有将未验证恢复代码纳入产品。当前永久移除明确失败并保留源文件，不使用非 macOS 的 `.Trash` 假替代；Library 内 Recycle 与系统回收站分开验收。
3. **预览**：PDF 快速连续切换、图片/文本/Markdown/其他附件、默认文件同步与打开后备方案尚未完成 Windows 原生适配/性能实测。没有恢复被用户回退的 macOS PDF 方案。
4. **Browser 与 Save to Gewu**：当前网页地址/会话、多标签 Home 历史、导航请求体/弹窗、PDF 暂存/下载、身份与重复资源、来源上下文、失败重试、层级目标选择与 Show in Library，必须在 WebView2 上连通并验收。服务层 capture 测试通过不等于此项完成。
5. **研究工作区**：Library/Shortcut/Space/My Publications、三类 Monitor、附属版本/Default/Annotation/Source 的跨平台核心继续复用，但真实 Windows 数据导入、移动重命名、批注应用、导出/备份等未做全量端到端验证。Windows 上的 LaTeX/图像和 PDF 工具依赖需单独处理。
6. **旧库工具与正式发布**：副本备份、资源完整性清单、逐项路径重定位、稳定 identity/关联核对、可中断恢复工具仍待实现；不可替换字符串、重建 DB 或重新导入整库。离线首次启动/重启、不同机器、普通权限、发布签名、异常中断和完整备份恢复都属于剩余验收。

下一轮首先完成输入/表单与关键导入闭环，再接预览和 Browser capture；回收恢复与迁移工具独立验证。只有上述产品能力和安装生命周期全部通过，才能以「与 macOS 功能一致」交付。

## 构建

在 Windows 上准备官方签名的 Python 3.13.15 x64 embedded runtime、.NET 10 SDK 和 Inno Setup 6.7.3。用开发 Python 安装项目依赖；指南生成另外需要 ReportLab。源码构建脚本不会删除或合并已有版本目录：

```powershell
python scripts/build_windows_preview_guide.py
./scripts/build_windows.ps1 -Version 0.1.3 -PythonRuntime PATH_TO_EMBEDDED_PYTHON -Dotnet PATH_TO_DOTNET -InnoCompiler PATH_TO_ISCC
python scripts/windows_package_smoke.py --install PATH_TO_TEST_INSTALL --output tmp/package-check
```

依据：[Python 嵌入式发行说明](https://docs.python.org/3/using/windows.html#the-embeddable-package)、[按用户安装权限](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)、[Windows 删除完成回调](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-postdeleteitem)。这些说明不能替代本机产品测试结果。
