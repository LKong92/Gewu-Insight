# Windows 资料库位置与迁移

Windows Preview 的资料应保存在独立用户目录，默认 `%USERPROFILE%\Gewu Insight Preview`。不要把正式使用的资料放在安装目录或开发工具的缓存中。File > Open Data Folder 打开当前资料位置。

当前外壳通过 `%USERPROFILE%\.gewu-insight\preview-workspace.txt` 读取已选物理目录，向后台显式传入数据库路径，并统一设置受管文件根目录。已选数据库缺失时停止启动；不得自动创建空替代库。开发测试的 `--workspace` 覆盖不修改用户选择。

## 离线复制工具

`paper_monitor.windows_workspace_relocation` 是保守的 Windows 同机迁移工具，不是 macOS 整库导入器，也不开放自动寻找、合并不同资料库。

1. 正常关闭应用，等待后台和 WebView2 退出。另存 SQLite 在线备份与原资料库选择。
2. 选择不存在的独立目标目录。工具取得外壳排他锁及数据库写入锁，检查源库完整性。
3. 通过 SQLite backup 复制数据库，复制其余文件与浏览器配置；不复制运行锁或直接复制数据库 WAL/SHM。
4. 仅重定位有明确语义的标量文件字段：论文主文件、合并文件、分析文件、资源存储路径、作者照片。源文件必须真实存在且在原目录内。嵌入 JSON 或未知字段中的原目录引用会停止迁移，不能批量替换。
5. 受管 `.lnk` 指向同一个新位置的真实文件；外部目标保持不变。陌生快捷方式、失效目标、符号链接或 junction 要求单独审计。原快捷方式不改写。
6. 比较每个文件 SHA-256、全部表记录、schema、完整性及外键检查结果。重定位时仅在复制数据库的连接上临时关闭编辑触发器，防止路径调整被当成产品编辑；之后恢复触发器，schema 和原记录保持。测试覆盖后续正常编辑仍触发更新。
7. 成功后才原子切换用户选择；失败不切换、不覆盖既有目录、不删除原库或未完成副本。报告仅用于诊断，SQLite 仍是事实来源。
8. 分别从开发环境和 Explorer 启动，检查实际后台 `--db` 与受管目录，查看 Library、Paper Files、My Publications。原库保持可回退；开始在新库编辑后，不能盲目切回旧快照，否则会遗漏新改动。

开发者命令（参数应为事先审计的绝对路径）：

```powershell
python -m paper_monitor.windows_workspace_relocation --source SOURCE --destination NEW_DESTINATION --report NEW_DIAGNOSTIC_REPORT
```

此命令只准备并验证副本，不修改启动选择。受管目录以外的论文仍由原外部位置提供，不会被偷偷复制为另一份论文。

## 本机执行记录：2026-09-09

- 在副本上执行迁移，最终切换至 `%USERPROFILE%\Gewu Insight Preview`。软件版本仍为 0.1.6，此次不需要重装。
- 迁移时 2,574 papers、39 My Publications、4 Library items、5 Library folders、2 resources。27 张表逐行核对，仅 7 个操作路径单元格改变；869 个文件核对，1 个受管快捷方式重定位，完整性正常，外键错误 0。
- 首次副本核验发现更新路径触发缓存 revision 改变，停止且未切换。修正为连接级触发器控制并通过回归后重新复制；未启用副本保留在私人备份目录。
- 原库仍保留；额外 SQLite 快照和原选择保存在用户主目录 `.gewu-insight/backups/`。备份、浏览器配置、日志和诊断报告均未加入源码或安装包。
- 12 项隔离 Windows 测试通过，覆盖中文/空格/特殊文件名、实际快捷方式、Default/身份/多处关联、外部目标、运行锁、缺失文件、目标冲突、未知 JSON 引用、复制失败、内容损坏和触发器恢复。Python 编译通过。
- Codex 启动与 Explorer 真实双击启动的服务均显式使用新目录下的同一个数据库。Library 的 test1/hermitian、hyppper、新目录 Paper Files/Default 和 39 Publications 已核对，应用留在 My Publications。

这不是跨盘实机、其他 Windows 机器、macOS 整库迁入或完整备份恢复的验收。应用 HTML/PDF Guide 现有资料库路径说明仍适用；没有添加未实现的设置或替换截图。
