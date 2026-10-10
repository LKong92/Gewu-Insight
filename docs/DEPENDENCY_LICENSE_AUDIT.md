# Gewu Insight 授权与第三方依赖审查

## 当前适用范围（2026-10-10 更新）

以下 9 月审计保留为历史证据，不是当前双平台安装包的完整合规结论。
当前 macOS DMG 和 Windows Setup 均内置 Python 与应用依赖；Windows
还内置 .NET，并复用或安装 WebView2。旧文中的“不打包解释器/环境”仅描述
当时的源码文件夹分发方式，不适用于这些独立安装包。

macOS 打包器会复制对应架构的 `PYTHON.json`、运行库许可证、Python 包源码
及许可元数据，并生成实际构建清单。Windows 应按该分支的构建清单和随包
通知逐项核对。当前文档修订没有重新解包审计两个发行包，也没有更新已发布
资产；下一次打包须纳入更新后的通知并验证实际分发物。

字体/书法素材的分发授权证据与正式贡献者商业授权流程仍是未解决事项。
保留这些限制，不以文档整理表示已经取得授权。仓库继续保持 private。
现行安装/分发规则见 [DISTRIBUTION.md](../DISTRIBUTION.md)，当前组件通知见
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 历史审计：2026-09-24

审查日期：2026-09-24。基线：`ca3cd11`，macOS 1.0.0 / Build 1。
本轮仅处理许可、说明、版权通知和分发包中的法律文件，不调整运行功能、
依赖版本、数据库或仓库架构。以下结论不是对所有未来版本的兼容性保证。

## 修改位置清单（先审查，后实施）

| 位置 | 原状 | 本轮处理 |
|---|---|---|
| `LICENSE` | 只有保留所有权利及禁止使用的条款 | 改为自定义学术/非商业研究有限许可，保留版权及单独商业授权 |
| `README.md` | 禁止一切复用，与新的科研使用原则冲突 | 介绍、安装入口、授权段落统一使用 source-available research software |
| `DISTRIBUTION.md` | 未说明科研分发条件及随包许可证 | 补充授权边界、第三方通知及公开发布注意事项 |
| `scripts/PaperMonitorApp.m` 的 About | 只有 All Rights Reserved | 保留版权及既有署名，补充科研许可和商业授权简述 |
| `paper_monitor/user_guide.html` | 缺少新的有限许可；标识版权声明范围过宽 | 增加使用范围及第三方例外，保留操作说明和截图 |
| `scripts/build_user_guide_pdf.py` / 生成的 TeX、PDF | PDF 尾页只写 proprietary software | 同步有限许可摘要并重新生成文档 |
| `scripts/make_release.sh` | ZIP 未复制根目录 LICENSE | 将 LICENSE 和第三方通知纳入既有分发列表 |
| `scripts/build_macos_app.sh` / App Resources | App 没有独立许可文本 | 随 App 打包同一 LICENSE 和第三方通知，更新签名 |
| `THIRD_PARTY_NOTICES.md`（新增） | 缺少统一清单；内嵌 JS 子组件通知不全 | 保留上游原文，补齐内嵌组件通知及外部安装依赖边界 |
| 现有 About/Guide 测试 | 断言旧授权描述 | 按新政策更新相关断言，核对源文件与打包文本一致 |
| `PROJECT_STATE.md`、Guide 审查记录 | 仍只记录上一轮手册更新 | 记录本轮范围、证据与待确认事项 |

`Info.plist` 和构建脚本中的原始版权归属及 All Rights Reserved 保留。
文献数据源配置面板已在 9 月 25 日更名为 **Literature Data Source**，
以避免与软件许可证混淆；菜单、手册及该设置页截图同步更新，原有接口和
帮助锚点保留。第三方代码中的 MIT、BSD 等许可文字仍保留，不全局替换
“open source”。

GitHub 只读检查结果：仓库为 private，description 为空、topics 为空，
许可证识别为 `NOASSERTION`。没有已发布的开源简介需要撤下。
建议公开时的简介为：**Source-available research software for organizing
papers and evidence. Academic/non-commercial research use permitted;
commercial use requires written authorization.** 用户确认：允许为非商业科研自行修改，但公开分享仅限未修改原版；
公开修改版或补丁需另行书面授权。本轮不修改远端简介、可见性、
历史提交或发布状态。自定义许可证不应伪标为 MIT、Apache 或 GPL；
GitHub 无法识别 SPDX 标准名称不代表 LICENSE 无效。

## 2026-09-24 后续：放开修改版的非商业科研分享

用户随后撤销了上述“只分享未修改原版”的限制。LICENSE 1.1 允许原版、
修改版、衍生作品和补丁在学术/非商业研究范围内免费分享，包括公开研究
fork 和 PR；保留同等科研使用条款、版权及第三方通知，并标明修改。
商业用途和商业分发仍须单独书面授权。此前 v1.0 的限制记录仅为审计历史，
不应当作现行许可。对应 README、分发说明、HTML/PDF 手册与 App 内许可
同步更新；依赖和素材没有改变，本次没有重新作完整依赖审计。

公开修改版的权限不等于向项目方授予商业再授权权。CONTRIBUTING.md
区分下游分享与上游合入，并明确正式 CLA 尚未完成，不能以 PR 提交或
Git 署名代替贡献者的单独商业授权。两位作者与学校的权属按用户要求本次
不处理，不据此声称已经确认。软著与商标尚未申请或核验，本次不执行登记。

## 审查方法和范围

检查 `requirements.txt`、产品 Python 导入、启动器、外部进程调用、App 动态
链接、两份浏览器 JS 分发文件、发布脚本和原项目虚拟环境的包元数据及许可证。
以下 Python 版本是当前环境的审计快照，不是锁定版本；requirements 只有
三个下限约束，未来安装可能解析出不同版本，发布前应重新核对。
本轮不为审计而升级、卸载或替换依赖。

JS 上游 npm 包 SHA-512 与仓库 README 记录一致；忽略原先删除的 source-map
注释后，两份 minified 文件与官方发布包逐字一致。Markdown-it 的 UMD
source map 内嵌源文件进一步与下表五个子组件发布包逐字匹配。
没有下载后执行任何第三方安装脚本。

## 必需的 Python 运行依赖

这些包由使用者首次启动时通过 pip 安装；当前发布脚本不复制 `.venv`、wheel
或 Python 解释器。它们仍是运行依赖，不能因为未随 ZIP 发送就略过授权。

| 组件 | 核对版本 | 许可证 | 归属及影响 |
|---|---|---|---|
| requests | 2.32.5 | Apache-2.0 | 直接依赖；保留许可及适用的 NOTICE/修改声明 |
| beautifulsoup4 | 4.14.3 | MIT | 直接依赖；保留版权和许可 |
| pypdf | 6.11.0 | BSD-3-Clause | 直接依赖；保留通知，不用作者名背书 |
| charset-normalizer | 3.4.7 | MIT | requests 传递依赖 |
| idna | 3.15 | BSD-3-Clause | requests 传递依赖 |
| urllib3 | 2.6.3 | MIT | requests 传递依赖 |
| certifi | 2026.4.22 | MPL-2.0 | requests 传递依赖；证书文件的文件级 copyleft 需单独遵守 |
| soupsieve | 2.8.3 | MIT | beautifulsoup4 传递依赖 |
| typing_extensions | 4.15.0 | PSF-2.0 及其随附历史通知 | Beautiful Soup 依赖；当前 Python 3.9 的 pypdf 也需要 |

上表以安装包自己的 `dist-info` 元数据和随包许可证为证，并通过项目官方
许可页面交叉检查主要类别。安装环境未发现 chardet；requests 的
`use-chardet-on-py3` 与 Beautiful Soup 的 chardet extras 未被本项目声明。
不能将其可能的 LGPL 义务套到当前默认安装，也不能在未来添加它时漏审。

## 随仓库分发的 JavaScript

| 组件 | 核对版本 | 许可证 | 实际分发方式 |
|---|---|---|---|
| markdown-it | 15.0.1 | MIT | `paper_monitor/vendor/markdown-it/markdown-it.min.js` |
| mdurl | 2.1.0 | MIT | 内嵌在上述 UMD 文件；5 个源映射文件匹配 |
| uc.micro | 3.0.0 | MIT | 内嵌；1 个源映射文件匹配 |
| entities | 8.0.0 | BSD-2-Clause | 内嵌；5 个源映射文件匹配；不能笼统标成 MIT |
| linkify-it | 6.0.0 | MIT | 内嵌；1 个源映射文件匹配，功能关闭不等于未分发代码 |
| punycode.js | 2.3.1 | MIT | 内嵌；1 个源映射文件匹配 |
| js-yaml | 4.2.0 | MIT | `paper_monitor/vendor/js-yaml/js-yaml.min.js` |

`argparse` 出现在两者 npm 命令行依赖里，但不在这两份浏览器 UMD 的源映射中，
也未随产品打包 npm CLI。不要把整个 npm 开发依赖树误认为运行分发物。
本轮补齐上述已内嵌组件的许可证原文；不改动任何 JS 字节或现有上游 LICENSE。

### September 27, 2026：离线 Markdown 公式

新增 KaTeX 0.18.9 浏览器包（MIT），来自官方 npm tarball：
https://registry.npmjs.org/katex/-/katex-0.18.9.tgz 。下载时核对 registry
发布的 SHA-512 integrity；随仓库保存的 `katex.min.js` 与包内文件逐字一致，
SHA-256 为 `155f6c2d673c5912e3b48f45d8830eaad18ae1953915939ceb648ea8b9c3e7e2`。
完整 MIT 版权声明保存在同目录 LICENSE 及 THIRD_PARTY_NOTICES.md。
此功能仅使用 MathML 输出，由平台排版，不分发 KaTeX 字体、CSS、CLI
或 npm 依赖。该组件保留自身 MIT 许可，不套用 Gewu 的科研用途限制；
此次新增运行文件未引入 GPL/AGPL 组件。此补充不改变此前尚待解决的素材权限问题。

## 可选运行工具、系统库与开发工具

| 组件 | 当前使用方式 | 授权判断及边界 |
|---|---|---|
| LibreOffice | 可选 `soffice` / `libreoffice` 独立进程，用于 Word 补充材料转换；不打包 | 官方主要为 MPL-2.0，含 LGPL 等第三方内容；不得将整个发行版误标为一个许可。当前没有链接或复制其代码，未来捆绑需单独审查 |
| XeLaTeX / pdfLaTeX / TeX 包 | 手册构建和可选出版清单 PDF 导出，通过命令行调用；不打包 | TeX 发行版混合多种许可，包含 LPPL、BSD、GPL 等；各包及嵌入字体分别核对，不把发行版视为一项 permissive 依赖 |
| Pandoc | 仅手册构建命令行工具；不打包 | GPL-2.0-or-later。调用转换程序本身并不自动把输入文档或普通输出改为 GPL；若复制模板/程序代码进输出需另查其许可 |
| Poppler | 本次审查/文档渲染工具；产品源码无此运行依赖、发布包不含它 | GPL 工具仅用于检查。将来若改为内嵌库或捆绑分发，应重新审查，不能沿用本结论 |
| Python / SQLite | 使用者环境/标准库，SQLite 数据存储 | Python PSF 及随附组件条款；SQLite public domain。Python 的 SSL、libffi 等打包义务属于实际解释器发行方式，不能由本项目许可覆盖 |
| Cocoa、AppKit、Quartz/PDFKit、WebKit、ImageIO、QuickLook、系统库 | 通用 App 的两个架构均只链接 macOS 系统位置的库 | 未复制 WebKit 源码/二进制到 App；遵守 Apple SDK/系统条款，不能因此声称 WebKit 所含 LGPL 代码已改为 Gewu 许可 |
| `open`、`osascript`、`textutil`、`cupsfilter` 等 | macOS 自带独立程序，不打包 | 操作系统自身许可；未引入 Ghostscript/MuPDF 运行依赖 |

本机 `.venv` 还装有 pdfplumber、pdfminer.six、pypdfium2、Pillow、ReportLab
等文档检查工具，产品未直接导入、requirements 未要求、发布脚本不复制它们。
该环境也有 cryptography 50.0.0（Apache-2.0 OR BSD-3-Clause）、cffi 2.0.0
（MIT）、pycparser 2.23（BSD-3-Clause）；它们不是默认声明依赖，但 pypdf
处理加密 PDF 时可使用已安装的 cryptography。若打包这类 wheel，须连同其
OpenSSL/libffi/Rust 等内嵌通知再审，不得只凭顶层包标签签署兼容性结论。

## 潜在问题与后续决策（单独列出）

1. **已核对的必需运行依赖及内嵌 JS 未发现 GPL/AGPL。** 这不是“所有
   第三方都是 MIT”的结论，也不是未来所有安装/商业发布的法律保证。
   没有发现 PyMuPDF、MuPDF、Ghostscript 被产品导入或打包。
2. **certifi 的 MPL-2.0 义务需要保留。** MPL 是文件级规则，通常允许与
   独立的专有文件组成更大的作品；如分发/修改 covered files，必须保留 MPL
   权利并按其条款提供对应源文件。Gewu 的非商业限制不能覆盖这些文件。
3. **内嵌 JS 通知缺漏在本轮补齐。** 特别是 BSD-2-Clause 的 entities。
   两份现有 MIT LICENSE 不能代替所有内嵌组件的版权通知。
4. **字体及书法图像需要权利人确认，属于公开分发与商业授权前的未解决事项。**
   `GewuSealGlyphs.png` 来源于汉仪篆书繁；仓库没有商业/软件或机构分发
   授权凭据。汉仪将个人非商业使用与其他授权范围区分，不能假定“科研免费”
   足以覆盖公开软件分发。`GewuAboutCalligraphy.png` 来自四个 shufa5
   字形图像，Guide 已承认没有明确开放复用许可。历史作者年代久远不自动
   证明网站图像、数字化素材及修改后的传播权均已取得。本轮不替换素材，
   不把自定义 LICENSE 当成对这些素材的权利证明。
5. **PDF 嵌入字体是独立问题。** 手册实际嵌入了 Avenir Next、Palatino、
   Menlo、Songti SC、Hiragino Sans GB、Arial Unicode MS 的子集。
   本机字体 OS/2 标志中，Avenir/Palatino 为 4（Preview & Print），Menlo
   为 0，实际用到的 Songti SC Regular/Bold、Hiragino、Arial Unicode 为 8
   （Editable）。Songti SC Black 为 2，但当前 PDF 未用到该字重。
   标志不是完整许可合同；分发可编辑模板、字体文件或不同嵌入用途前仍需
   核对适用 EULA。本轮不把系统字体本体加入发布包。
6. **截图中的论文图、期刊标识、作者肖像及外部页面仍归各权利人。** 当前
   截图用于解释软件操作；软件 License 不授予这些内容的独立商业复用权。
   公开或商业发布应逐项确认适用许可/例外，不能以“截图是我们拍的”替代。
7. **未来贡献的商业再授权权利不能自动获得。** 当前 Git 作者署名为
   Lingyuan Kong、Zhengran Wu，但 Git 署名不证明完整雇佣/合作权属。
   接收外部代码前应明确取得覆盖商业再授权的贡献协议；不能只依赖入站
   非商业 License，就保证可对贡献代码完整商业化。本轮没有擅自制定 CLA
   或要求转让第三方版权。后续的外部贡献流程已写入
   [CONTRIBUTING.md](../CONTRIBUTING.md)：提交 PR 或公开研究 fork 不需要 CLA，
   但拟合入官方商业授权版本的外部贡献须先取得相应的单独书面授权。
   正式 CLA、签署流程及实际贡献者授权仍未完成。
8. **requirements 未锁版本。** 本轮只记录实际审查版本，不改变安装行为；
   新版本、新 extras、改为捆绑 Python/工具的发行方式均需要重审。

## 官方依据

- [GitHub：仓库授权与公开仓库的查看/fork 权利](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [OSI：Open Source Definition，尤其领域限制](https://opensource.org/osd)
- [Mozilla：MPL 2.0 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)，[许可正文](https://www.mozilla.org/en-US/MPL/2.0/)
- [certifi 的许可证](https://github.com/certifi/python-certifi/blob/master/LICENSE)
- [requests 的许可证](https://github.com/psf/requests/blob/v2.32.5/LICENSE)，[pypdf 的许可证](https://github.com/py-pdf/pypdf/blob/main/LICENSE)
- [LibreOffice 官方许可说明](https://www.libreoffice.org/licenses/)
- [Pandoc 版权清单](https://github.com/jgm/pandoc/blob/main/COPYRIGHT)，[GNU 关于程序输出及独立程序的 FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [汉仪授权说明](https://fund.hanyi.com.cn/license)，[具体字型](https://www.hanyi.com.cn/productdetail?id=450&type=0)
- [Apple 软件许可入口](https://www.apple.com/legal/sla/)，[字体嵌入条款示例](https://www.apple.com/legal/sla/docs/macOSMonterey.pdf)

具体版本及内嵌通知另见根目录 `THIRD_PARTY_NOTICES.md`。原始上游包、
源映射比较、安装包元数据、字体标志及核验记录保存在工作区外的临时审计
目录；不把本机完整环境、个人资料或凭据提交到仓库。

## 验证记录

- 46 项现有 Guide、审查清单和 macOS 窗口/打包检查通过；六项 PDF 结构检查
  通过。初次检查发现授权尾页被拆页，以及构建先后导致 App 内 PDF 仍为旧版；
  已在生成器中单独排授权尾页，重新打包并复验，不通过修改断言掩盖问题。
- PDF 共 119 页；11 个文字发生变化的页面已渲染复核。原有 913 个命名目标
  全部保留且可定位，只新增 `page.119`。所有 36 张截图、字体/品牌素材不变；
  Product Identity 4-1 至 4-4 连续排版规则仍由生成器及结构检查保证。
- About 的五个实际固定文案使用 AppKit 原生尺寸计算检查，均能容纳于文本框；
  新增三行许可说明需要 33 点高度，提供 35 点。通用 App 两种架构均构建成功，
  签名核验通过。既有弃用 API 警告及 iconutil 回退继续保留原图标，未换图。
- 对比基线：79 个其他产品文件、两个配置文件、40 个素材文件及
  `requirements.txt` 均逐字不变；原生源码除 About 文案及其容器布局外不变。
  未更新依赖、修改数据库、运行科研导入/删除或启动元数据任务。
- Python 编译、两个打包脚本语法及 diff 检查通过。用户随后授权提交和推送；
  GitHub 可见性保持 private，没有公开发布。提交检查时原项目 App 正常重启，
  确认只有一组 App/后端进程、本地服务健康，实际 About 已显示新授权简述，
  检查后返回 Library。没有执行科研导入、删除或手动更新来源。
- 在隔离临时目录执行现有发布脚本，ZIP 完整性检查通过，根目录与 App 内
  LICENSE、第三方通知及 PDF 与源文件一致；没有带入 SQLite、虚拟环境或
  Python 缓存。试验包仅用于本地检查，没有公开。

### 另行发现的既有分发问题（不是本轮许可修改引入）

**后续状态：** 下述 ZIP 签名问题是 9 月审计发现的历史问题。当前
`scripts/make_release.sh` 已保留签名扩展属性、只清理指定显示属性，并在复制
前后和实际 ZIP 解压后验证签名；不要把下文当作当前未修复结论。
该脚本仍只负责旧式文件夹 ZIP，不生成当前 DMG 或 Windows Setup。

源 App 的签名通过，但 ZIP 打包脚本原有的 `xattr -cr` 会清除脚本型启动
辅助程序 `Gewu Insight Server` 的签名属性，导致打包产物的严格签名检查
失败。用基线 `ca3cd11` 的原始发布脚本及同一个已验证 App 单独复现，结果
相同。本轮未修改该清理行为，也不把“法律文件打包正确”说成“发布包已全面
验收”。对外分发 Mac 安装包前应单独修复并复验；这是分发技术问题，不是
GPL/AGPL 或自定义许可证兼容性结论。
