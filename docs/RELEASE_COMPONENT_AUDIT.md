# Released installer components and notices

## macOS 1.0.1 package — October 19, 2026

[macOS 1.0.1](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.1)
Build 1 was built from `f6df8c30c8d1c11bef06287460ccb62cede996ef`; its tag
and build manifest identify the same source. The DMG is 116,838,335 bytes.

```text
SHA-256: e788217a885087d7ad09fb041653b6c835b41147d68d23a837bb9447466d614f
```

Both Python runtime archives match the prior pinned input hashes. Dependencies
and license inputs were copied from the prior DMG after verifying its checksum.
The new package contains current contribution/notices documents and the referenced
audit pages. Its User Guide is unchanged at the user's request; the release notes
supersede its Default-file deletion guidance and explain the new website editor.

The actual DMG was mounted read-only and its copied App passed strict signature
verification, isolated service first launch/restart with retained database and
settings, and the bundled PDF subprocess check. All 241 scoped regressions passed
against the packaged Python modules. The Intel interpreter ran under Rosetta;
no native Intel hardware, clean external Mac or Windows acceptance was performed.
App bytes and signatures remained valid after execution. All five uploaded asset
hashes matched the local validated files. Existing releases remain available;
Windows remains at 1.0.0. These checks do not establish additional artwork rights,
Developer ID signing or Apple notarization.

## Earlier release metadata — October 10, 2026

GitHub release metadata and the attached build JSONs were read again for this
repository cleanup. Their recorded sizes and hashes agree. The current installers
were not downloaded, extracted, rebuilt or executed in this follow-up, so the
earlier package inspection below must not be treated as inspection of these bytes.

| Platform and release | Installer bytes | Source in current build JSON | Current tag source |
| --- | ---: | --- | --- |
| [macOS 1.0.0](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0) | 116,729,930 | `eb8714d` | `539d00d` |
| [Windows 1.0.0](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0) | 86,255,214 | `725ae8f` | `725ae8f` |

```text
macOS:   5085329390e5ce7e507b4ff554163b5c5e0c8a420b42ad4287b03d2939a08d4d
Windows: b9056eab0ec6a0af40ae7608a24437d82cfd3508ecb300c8d43047286cf3445e
```

The Windows build record describes the corrected 94-page guide, with SHA-256
`458cd0560a03dcd41ba5e4144f94c79090c1a9840db98b34d7a6389fa7a1eb18`,
and 2,165 payload files. Both build records point to source revisions containing
the updated seal. The Windows tag and release metadata were subsequently aligned
to `725ae8f` by a separate authorized operation, with installer bytes unchanged;
the current remote ref and updated build JSON were rechecked here. The macOS
tag retains `539d00d` while its current build records source `eb8714d`; use the
build record for that package's source rather than the automatic tag archive.
The old Windows r2 release is not a current download entry in the queried list.
This cleanup itself changes no release or tag.

Windows source packaging now includes CONTRIBUTING.md and the linked licensing
and audit pages in future builds. That change has not been installed or published.
The notice contents of the current installers still require a fresh package
inspection; repository edits alone do not establish their contents.

## Historical package inspection — earlier October 10 assets

The rest of this page preserves the earlier static inspection of the exact
hashes below. It is not a declaration that all redistribution rights are cleared.
LICENSE 1.1 remains unchanged.

### Packages examined in the historical inspection

| Release | Asset | Bytes | Source revision |
| --- | --- | ---: | --- |
| [macOS 1.0.0](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0) | `Gewu-Insight-macOS-1.0.0.dmg` | 114,588,662 | `539d00dd1a3b0f5857912223868ca232d56680c9` |
| [Windows 1.0.0 Revision 2](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0-r2) | `Gewu-Insight-Windows-1.0.0-x64-Setup.exe` | 83,804,820 | `4b952e4b51a1ae6f4ad9303ea9bd230fabd3f504` |

SHA-256, matched against the release checksums and build manifests:

```text
macOS:   4d6a587753439c70dfcd31c90145838068e605708c4bb5ecdd79bb0b7d2daf0a
Windows: 8473d0a4e44e04b1c145472f9063f9707ab87e72da47a197ba1d69bc33dd11cf
```

The macOS build JSON records the source revision, two runtime archives and
their license-source archives, dependency versions and packaging-script hashes.
Its common fields agree with the App's `Standalone Build.json`. Windows records
its release source, build-input hashes and payload-manifest hash. The Windows
native assembly retains a precommit informational revision, as disclosed in the
release build JSON; it is not a different claim about the release tag.

## Runtime and component inventory

For macOS, paths below are relative to `Gewu Insight.app/Contents/Resources`.
For Windows, they are relative to the installed program directory.

| Component | macOS package | Windows package | Notice location and scope |
| --- | --- | --- | --- |
| CPython | 3.12.15, python-build-standalone 20261003, arm64 and x86_64 | 3.13.15, x64 embedded distribution | Mac: `Runtime Licenses/<architecture>/PYTHON.json` and `licenses/`. Windows: `service/LICENSE.txt`, including historical and Windows binary conditions. |
| .NET | Not bundled | .NETCore and WindowsDesktop runtime 10.0.11 | Windows: `licenses/microsoft.netcore.app.runtime.win-x64/10.0.11/` (LICENSE and THIRD-PARTY-NOTICES), and `licenses/microsoft.windowsdesktop.app.runtime.win-x64/10.0.11/LICENSE`. |
| WebView2 SDK | Not bundled; uses system WebKit | 1.0.4191.47 | Windows: `licenses/microsoft.web.webview2/1.0.4191.47/LICENSE.txt` and `NOTICE.txt`. Setup separately carries the Evergreen bootstrapper and reuses/downloads the WebView2 Runtime; the SDK version is not the installed Runtime version. |
| markdown-it | 15.0.1 | 15.0.1 | Vendor LICENSE and the six-component attribution section in THIRD_PARTY_NOTICES.md, including mdurl, uc.micro, entities, linkify-it and punycode.js. |
| js-yaml | 4.2.0 | 4.2.0 | Vendor LICENSE and THIRD_PARTY_NOTICES.md. |
| KaTeX | 0.18.9 | 0.18.9 | Vendor LICENSE and THIRD_PARTY_NOTICES.md; JavaScript/MathML usage, without KaTeX font or CSS bundles. |

The macOS runtime metadata references 15 distinct license files per architecture;
all were present. These cover CPython and notices for bzip2, Expat, libedit,
libffi, liblzma, libuuid, mpdecimal, ncurses, OpenSSL, SQLite, Tcl, zlib and
zlib-ng. Each architecture's directory retains 20 license texts, including extra
upstream notices. `LICENSE-SOURCES.json` records the separately sourced zlib-ng
notice omitted from the upstream full archive; its recorded SHA-256 matched.
`BUNDLED_RUNTIME_NOTICES.txt` correctly states that the App bundles Python.

### Python packages

Versions below came from the extracted packages' distribution metadata. The
macOS set agrees with the release build JSON; the Windows set agrees with
`windows/requirements.lock` at its release revision. License labels are indexes
to the complete bundled terms, including embedded third-party components.

| Package | macOS | Windows | License index |
| --- | --- | --- | --- |
| beautifulsoup4 | 4.15.0 | 4.15.0 | MIT |
| certifi | 2026.7.22 | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.2 | 3.5.1 | MIT |
| idna | 3.20 | 3.19 | BSD-3-Clause |
| pypdf | 6.19.0 | 6.18.0 | BSD-3-Clause |
| requests | 2.34.2 | 2.34.2 | Apache-2.0; NOTICE retained |
| soupsieve | 2.10 | 2.9.2 | MIT |
| typing_extensions | 4.16.0 | 4.16.0 | PSF-2.0 and historical notices |
| urllib3 | 2.8.0 | 2.7.0 | MIT |
| Pillow | Not bundled | 12.3.0 | MIT-CMU plus native-library notices |
| pypdfium2 | Not bundled | 5.12.1 | BSD-3-Clause, Apache-2.0 and dependency notices |
| pywin32 | Not bundled | 312 | PSF and component-specific notices |
| tzdata | Not bundled | 2026.3 | Apache-2.0 and included time-zone data notice |
| tzlocal | Not bundled | 5.4.4 | MIT |

Mac package source and metadata are in `dependencies/`; Windows uses
`service/Lib/site-packages/`. All 11 macOS and 42 Windows `License-File`
declarations resolved to existing files inside the corresponding `.dist-info`
directories. certifi includes its covered CA data and license in both packages.

The Windows pypdfium2 wheel includes PDFium **152.0.7947.0** and its notices in
`pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/`, alongside
the wrapper's `LICENSES/` directory. Its PDFium, FreeType, ICU, JPEG, PNG, TIFF,
OpenJPEG and other dependency notices must be retained together. Pillow's
`pillow-12.3.0.dist-info/licenses/LICENSE` includes the compiled library notices;
pywin32's licenses include Pythonwin, Scintilla, IDLE, COM/MAPI and adodbapi.
Their top-level Python license labels alone do not describe the whole wheel.

## Discrepancies found in the historical packages

| Finding | Actual package state | Required follow-up |
| --- | --- | --- |
| Gewu license | Both packages contain LICENSE 1.1 with text matching the repository (ignoring Windows line endings). | Preserve the research/commercial policy; no license rewrite is needed. |
| Top-level third-party summary | Both retain the older description that Python is installed separately and not bundled. Mac's separate runtime notice contradicts that older summary. | Include the corrected summary in a newly built package, checking every bundled copy. |
| Contribution policy | Mac includes the earlier policy; Windows omits CONTRIBUTING.md. | Carry the current policy in both packages. This does not supply a signed contributor agreement. |
| Audit-document references | Both summary notices refer to `docs/DEPENDENCY_LICENSE_AUDIT.md`, which is absent from both packages. | Bundle the referenced audit documents or provide a valid, access-qualified source link. |
| Windows component overview | The older summary lists only the historical cross-platform Python set, not the extra native dependencies; component notices themselves are present. | Add the Windows-specific inventory and retain all nested notices. |
| Seal-style artwork | The examined installers predate the October 10 AI-assisted motif replacement in source. | Include the new motif, its provenance and the updated manual in future packages; no existing Release asset has been replaced. |
| Build provenance | Windows' sidecar does not consolidate exact interpreter/dependency versions or original runtime-input archive digests. | Record those inputs and the WebView2 bootstrapper version/hash in the next build manifest. |

Font and calligraphy redistribution evidence remains unresolved. PDF embedding,
system-font availability, authorship of a composite image, or inclusion of a
notice does not establish those permissions. The formal external-contributor
agreement and signature process also remains unfinished. See the
[asset audit](DEPENDENCY_LICENSE_AUDIT.md) and [contribution policy](../CONTRIBUTING.md).
No evidence was removed and no authorization was inferred during this review.

## Historical verification performed

- Downloaded the actual GitHub assets and checked both complete installer hashes
  against their published `.sha256` files and build JSONs.
- Mounted the DMG read-only; image verification and the App's deep, strict code
  signature verification passed. This ad-hoc signature does not establish an
  Apple-verified publisher identity or notarization.
- Extracted Windows Setup without running it. Independently verified all **2,162**
  entries in its payload manifest, including size and SHA-256. The manifest hash
  matched the published build JSON. The supported-format extractor emitted
  checksum-readback warnings; the independent manifest check supplied the file
  integrity verification instead of treating extraction alone as proof.
- Checked runtime metadata, declared license files, nested native-library notices
  and all three JavaScript vendor licenses. JavaScript bundles matched current
  source, allowing only Windows line-ending differences for markdown-it.
- Compared license/policy/summary copies against the repository and examined both
  platform build paths. Did not rerun installer/native UI acceptance, verify every
  upstream archive afresh, or assert complete legal clearance. Existing release
  validation JSONs describe earlier testing, not new testing performed here.

## Remaining package verification and release work

1. Prepare separately versioned packaging revisions from reviewed platform source
   and the corrected documentation. Preserve LICENSE 1.1 and existing runtime
   behavior; include current CONTRIBUTING.md, THIRD_PARTY_NOTICES.md and an
   accessible component inventory. The Windows source now carries that notice-copy
   change; it still needs a new package and Windows validation before publication.
2. Record exact component versions, input URLs/hashes and the new package hashes.
   Check nested licenses against the actual payload, including Python runtime,
   .NET/WebView2, PDFium/Pillow and pywin32 notices. Obtain or explicitly resolve
   the missing artwork/font permissions and contribution authorizations before
   claiming the intended redistribution is cleared.
3. Verify the actual rebuilt DMG/Setup, then test clean install, update, restart
   and retained database selection on the respective platforms using isolated
   synthetic data. Keep signing limitations and test coverage explicit.
4. Submit the resulting artifacts and validation for approval before uploading
   new revision assets. Retain the existing releases and checksums; do not silently
   overwrite a published filename or tag. Preserve the repository's current visibility.
