# Windows 0.1.21 对齐交付记录

日期：2026-09-29。已更新并重开原 App；继续使用源码桌面路线，不安装发布包。

## 对齐范围

以 Windows `70fa8a0` 为起点，将 macOS `9ea2bb3..8a2789512164a42ac066a3cee67548b1328d5056` 的最终产品状态适配到 Windows。范围覆盖已审计的 53 个 Mac 提交；不包含 Mac 上未推送的工作。

| 审计项 | 0.1.21 的处理 |
| --- | --- |
| D01–D02 身份与公告 | 规范论文身份、旧 ID/Key 别名、冲突与纠正历史；公告独立身份和原文关联 |
| D03–D05 文件与回收 | 相同字节去重并保留导入来源；移动到另一论文、从文件创建论文；关联文件、Default 和位置事务；Windows `.lnk`、目录更名 journal、Shell 回收及恢复 |
| D06–D07 刷新与作者监控 | 统一 Refresh Info、持久队列、暂停/继续/停止/历史；缓存即时展示、作者范围后台补全、退避恢复和冲突提示 |
| D08–D10 AI/MCP | 适配器 1.5.0、24 项工具；目录浏览、交付配额/释放、独立写权限和可写范围、幂等导入及整理；外部写入刷新界面 |
| D11 下载 | 在途请求合并、独立临时目录、Science 主文/补充校验和 First Release 分类；保留 Windows Nature 会话回退与下载快照刷新 |
| D12 原始 PDF | 保留当前文档的原始响应，支持无扩展名、内嵌与附件预览；Use Loaded PDF 不重新请求；128 MiB 上限、导航失效与缓存限额 |
| D13–D14 阅读与界面 | Markdown 属性折叠、宽表/代码、离线公式；20 种文件分类、表头排序、默认添加位置与统一匹配 |
| D15–D16 拖放与 Loader | Windows 托管文件拖放载荷与重复手势保护；整列 Paper Files 接收；Loader 日志定位及任务保留 |
| D17 恢复 | 工作区渲染进程有限恢复；连续服务恢复保留 Browser 草稿与已完成 Loader 结果 |
| D18 设置与帮助 | Literature Data Sources、Add to Library、联系和官网入口；新版 Windows HTML/PDF 帮助；共享许可证/说明随上游同步 |

Windows 的私有 DACL、UTF-8 MCP、端口跟随、路径边界和文件关联继续保留。修复了大小写更名、长路径、SQLite 备份句柄占用、并发复制目标规范化，以及保留 mtime 时 Markdown 缓存失效的问题。

## 验证

- 全量 Python：1,420 项，1,388 通过、32 项平台条件跳过，216.807 秒。跳过包括普通 Windows 用户缺少创建 POSIX 符号链接的权限，以及 macOS App/平台专属检查；Windows Shell Link 用例另有覆盖。
- 编译与语法：76 个产品 Python 文件、3 个独立 JavaScript 文件和主界面内联脚本；`.NET` 发布构建与 `git diff --check` 通过。
- 原生出版社/PDF 范围：132 项检查通过；后续原生组合运行亦通过更新后的原始 PDF、附件/iframe、授权来源、POST/弹窗和拖放部分。使用合成文件与测试专用本地 HTTP 站点，不代表实际订阅账户验收。
- 原生工作区范围：106 项检查通过，包括实际 Loader 导入/定位、历史输入、读取缓存、捕获、Chrome 子树同步、连续三次服务崩溃、工作区渲染进程崩溃及恢复上限。
- 交付目录的实际 0.1.21 外壳隔离启动成功；正常关闭原 0.1.20 后重开原 Library，检查到可见 0.1.21 进程、4 个接口 HTTP 200 与新版 Browser 资源。
- 内置 Windows PDF 帮助重新生成并逐页检查，共 3 页。没有新造 App 截图或把 macOS 截图作为 Windows 验收证据。

## 原资料与交付位置

- 入口：`Start Gewu Insight.cmd`；外壳 `dist/windows-preview-0.1.21`，279 个文件哈希校验通过；服务使用原 `.venv` 与当前源码。
- 原 Library：`C:/Users/Zhengran/Gewu Insight Preview`；选择文件未改变。
- 结构升级演练：schema 18→22，33 张旧表的全部旧字段和记录保持一致；普通启动不执行历史资料扫描、合并或布局迁移。
- 实际升级后：4,442 papers、39 My Publications、10 Library items、5 folders、6 resources；12 张受保护表的旧字段与全部记录完全一致；19 个研究文件哈希不变；完整性 OK，外键错误 0。新增 AI 可写范围默认空，不扩大已有授权。
- 恢复备份：`tmp/windows-parity-0.1.21/delivery-backup/`，含研究文件、在线 SQLite 快照、正常关闭后的 SQLite 快照和被替换源码。旧 0.1.20 外壳保留作为恢复材料。
- 交付证据：同目录上级的 `schema-rehearsal.json`、`source-delivery-manifest.json`、`installed-native-result.json`、`verified-original.json`。隔离回归证据位于托管工作树 `C:/Users/Zhengran/.codex/worktrees/windows-mac-parity/gewu-insight/tmp/windows-parity-0.1.21/`。

## 保留边界

Apple Passwords/AutoFill、Safari 同步、macOS 系统 Quick Look 按用户范围排除。真实机构登录下载、每个第三方拖放目标、跨盘恢复和其他 Windows 硬件尚未全面实测；WebView2 与 WebKit 的底层会话行为仍有平台差异。

这是本机源码桌面更新，不等同签名安装包或跨机器正式发行验收。未创建安装包、未改变系统安全设置；未 commit/push，未更新远端 main 或 macOS 分支。审计原文保留在 [0.1.20 差异核对](WINDOWS_MAC_DIFF_2026-09-29.md)。
