# Gewu Insight 依赖与授权审查范围

更新：2026-10-10。本页保留组件核对依据和适用边界，历史操作日志另行归档。
现行软件许可为 [LICENSE 1.1](../LICENSE)；使用与分享说明见
[LICENSING.md](LICENSING.md)。

## 当前分发与审查范围

当前 macOS DMG 和 Windows Setup 均内置 Python 与应用依赖；Windows
还内置 .NET，并复用或安装 WebView2。旧源码文件夹分发方式的“不捆绑
解释器”结论不适用于当前安装包。

本页的 Python 版本来自 2026-09-24 源码环境审计，JavaScript 记录包含
9 月 27 日的 KaTeX 补充。它们不是依赖锁定文件，也不是当前双平台安装包
的完整组件清单。10 月 10 日曾静态检查当时的 macOS DMG 和
Windows Setup；那次解包、许可与文件清单结论只对应历史哈希。随后远端
替换了安装包，本次只复核当前 Release 元数据和 build JSON，没有重新
解包当前安装器。准确版本、源码、哈希和两次检查范围见
[发行包组件审计](RELEASE_COMPONENT_AUDIT.md)。

Windows 源码打包现已补入 CONTRIBUTING 与授权/审计页，待下一次实际构建
和 Windows 验收。不能把源码修正写成已更新现有发布包；也不能把历史许可
清单核对写成当前安装器已完成全部授权确认。

- macOS：核对 App `Contents/Resources` 中的 `Standalone Build.json`、
  `BUNDLED_RUNTIME_NOTICES.txt`、`Runtime Licenses/<architecture>/` 和
  `dependencies/`，包括运行库与 Python 包的许可、元数据和对应源码。
- Windows：按该分支构建清单和实际随包通知核对 Python、.NET、WebView2
  及原生组件；macOS 的审计不能代替 Windows 的审计。
- 发布前按实际分发物复核通知和源码提供义务。详见
  [分发指南](https://github.com/LKong92/Gewu-Insight/blob/Windows/DISTRIBUTION.md)和[第三方通知](../THIRD_PARTY_NOTICES.md)。

## Python 组件证据

以下是 9 月 24 日 Python 包元数据和随包许可证的核对快照，并已在当时与
主要组件的官方许可页面交叉核对。`requirements.txt` 使用版本下限，
后续安装解析出的版本可能不同。

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

certifi 的 MPL-2.0 适用于其受保护文件；分发时保留许可和对应源码提供
义务。Gewu 的科研用途限制不覆盖这些独立许可组件。可选 crypto wheel
如被纳入实际安装包，还需核对其 OpenSSL、libffi 等内嵌通知。

## JavaScript 组件证据

完整版本表、来源链接和上游许可原文保存在
[第三方通知](../THIRD_PARTY_NOTICES.md#bundled-javascript)，各 vendor
目录另保留组件自己的 LICENSE 和来源说明，避免在本页重复维护清单。

9 月审计对 markdown-it 和 js-yaml 核对了上游 npm 完整性信息；忽略
已移除的 source-map 链接后，浏览器包与上游一致。markdown-it 内嵌的
mdurl、uc.micro、entities、linkify-it 和 punycode.js 也通过源映射核对，
其中 entities 为 BSD-2-Clause，不能统称为 MIT。

9 月 27 日的 KaTeX 0.18.9 使用未修改的浏览器 JavaScript 包，SHA-256 为
`155f6c2d673c5912e3b48f45d8830eaad18ae1953915939ceb648ea8b9c3e7e2`。
产品使用 MathML 输出，不分发该包的字体、CSS、CLI 或 npm 依赖。

## 外部工具与后续变更

LibreOffice 和 TeX 工具由用户另行安装。Pandoc 是手册构建工具，Poppler
用于文档检查；这些使用方式不能作为未来捆绑这些工具的授权结论。
macOS 原生界面链接系统框架，具体使用方式见第三方通知。

依赖版本、extras、原生库或打包方式变化时，重新按实际分发物核对。
旧源码环境未发现 GPL/AGPL 必需运行依赖，不代表所有未来版本或当前
安装包已获得完整合规结论。

外部贡献的商业授权与科研分享权限分开处理。正式 CLA 和签署流程尚未
完成，现行入口与维护者检查清单见 [CONTRIBUTING.md](../CONTRIBUTING.md)
及 [LICENSING.md](LICENSING.md#contribution-authorization-checklist)。

## 当前素材与保留事项

1. **篆书水印已替换，行草集字的来源与权利核查仍保留。**
   当前 `GewuSealGlyphs.png` 采用项目通过 AI 辅助生成、由用户选定的
   格物洞見图案；生成记录见 [素材来源](https://github.com/LKong92/Gewu-Insight/blob/Windows/assets/branding/README.md)。
   该记录说明制作方式，不构成法律清权或独占权利证明。当前发行记录指向
   更新后的印章；旧版本可能仍保留早期素材，各安装包应按实际哈希分别核查。
   `GewuAboutCalligraphy.png` 图像未改。Guide 改引明代祝允明（号枝山）及
   已核对的原作：“洞”对应上海博物馆藏《草书前后赤壁赋卷》中“客有吹洞簫者”。
   “格、物、見”的具体原帖仍待考，不能把作者归属当作已确认全部原帖。
   旧获取记录与比对证据保留在本地研究归档。原作与具有独创性的现代加工
   应分别判断；缺少网站开放许可本身不等于古代字形必须购买授权。
   自定义 LICENSE 不作为外部图像的权利证明。
2. **PDF 嵌入字体是独立问题。** 手册实际嵌入了 Avenir Next、Palatino、
   Menlo、Songti SC、Hiragino Sans GB、Arial Unicode MS 的子集。
   本机字体 OS/2 标志中，Avenir/Palatino 为 4（Preview & Print），Menlo
   为 0，实际用到的 Songti SC Regular/Bold、Hiragino、Arial Unicode 为 8
   （Editable）。Songti SC Black 为 2，但当前 PDF 未用到该字重。
   标志不是完整许可合同；分发可编辑模板、字体文件或不同嵌入用途前仍需
   核对适用 EULA。本轮不把系统字体本体加入发布包。
3. **截图中的论文图、期刊标识、作者肖像及外部页面仍归各权利人。** 当前
   截图用于解释软件操作；软件 License 不授予这些内容的独立商业复用权。
   公开或商业发布应逐项确认适用许可/例外，不能以“截图是我们拍的”替代。

## 官方依据

- [GitHub：仓库授权与公开仓库的查看/fork 权利](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [OSI：Open Source Definition，尤其领域限制](https://opensource.org/osd)
- [Mozilla：MPL 2.0 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)，[许可正文](https://www.mozilla.org/en-US/MPL/2.0/)
- [certifi 的许可证](https://github.com/certifi/python-certifi/blob/master/LICENSE)
- [requests 的许可证](https://github.com/psf/requests/blob/v2.32.5/LICENSE)，[pypdf 的许可证](https://github.com/py-pdf/pypdf/blob/main/LICENSE)
- [LibreOffice 官方许可说明](https://www.libreoffice.org/licenses/)
- [Pandoc 版权清单](https://github.com/jgm/pandoc/blob/main/COPYRIGHT)，[GNU 关于程序输出及独立程序的 FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [Apple 软件许可入口](https://www.apple.com/legal/sla/)，[字体嵌入条款示例](https://www.apple.com/legal/sla/docs/macOSMonterey.pdf)
