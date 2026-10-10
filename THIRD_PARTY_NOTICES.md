# Third-party notices for Gewu Insight

Reviewed September 24, 2026. Gewu's custom research license applies only to its
own covered materials. It does not restrict the independent licenses below.
Keep this file and the component-specific notices when redistributing Gewu.

## Bundled JavaScript

The following original license texts are reproduced from the exact upstream
packages. The five markdown-it subcomponents are embedded in its browser UMD
bundle, even where an optional feature is disabled. Package versions were
checked against the upstream source map. Existing vendor LICENSE files remain.
The bundles differ from the official releases only by omitted source-map links.

| Component | Version | License | Location |
|---|---|---|---|
| markdown-it | 15.0.1 | MIT | paper_monitor/vendor/markdown-it/markdown-it.min.js |
| mdurl | 2.1.0 | MIT, including Node/Joyent attribution | Embedded in markdown-it |
| uc.micro | 3.0.0 | MIT | Embedded in markdown-it |
| entities | 8.0.0 | BSD-2-Clause | Embedded in markdown-it |
| linkify-it | 6.0.0 | MIT | Embedded in markdown-it |
| punycode.js | 2.3.1 | MIT | Embedded in markdown-it |
| js-yaml | 4.2.0 | MIT | paper_monitor/vendor/js-yaml/js-yaml.min.js |
| KaTeX | 0.18.9 | MIT | paper_monitor/vendor/katex/katex.min.js |

## KaTeX 0.18.9

Added September 27, 2026 for offline Markdown math. Official package:
https://registry.npmjs.org/katex/-/katex-0.18.9.tgz

Only the unmodified browser JavaScript bundle is shipped. MathML output uses
the platform renderer; KaTeX web fonts, CSS, CLI and npm dependencies are not
bundled. The complete upstream license is also in
`paper_monitor/vendor/katex/LICENSE`.

```text
The MIT License (MIT)

Copyright (c) 2013-2020 Khan Academy and other contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## markdown-it 15.0.1

Official package: https://registry.npmjs.org/markdown-it/-/markdown-it-15.0.1.tgz

```text
Copyright (c) 2014 Vitaly Puzrin, Alex Kocharin.

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
```

## mdurl 2.1.0

Official package: https://registry.npmjs.org/mdurl/-/mdurl-2.1.0.tgz

```text
Copyright (c) 2015 Vitaly Puzrin, Alex Kocharin.

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

--------------------------------------------------------------------------------

.parse() is based on Joyent's node.js `url` code:

Copyright Joyent, Inc. and other Node contributors. All rights reserved.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
```

## uc.micro 3.0.0

Official package: https://registry.npmjs.org/uc.micro/-/uc.micro-3.0.0.tgz

```text
Copyright Mathias Bynens <https://mathiasbynens.be/>

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## entities 8.0.0

Official package: https://registry.npmjs.org/entities/-/entities-8.0.0.tgz

```text
Copyright (c) Felix Böhm
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## linkify-it 6.0.0

Official package: https://registry.npmjs.org/linkify-it/-/linkify-it-6.0.0.tgz

```text
Copyright (c) 2015 Vitaly Puzrin.

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
```

## punycode.js 2.3.1

Official package: https://registry.npmjs.org/punycode.js/-/punycode.js-2.3.1.tgz

```text
Copyright Mathias Bynens <https://mathiasbynens.be/>

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## js-yaml 4.2.0

Official package: https://registry.npmjs.org/js-yaml/-/js-yaml-4.2.0.tgz

```text
(The MIT License)

Copyright (C) 2011-2015 by Vitaly Puzrin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Python packages and standalone runtimes

Current macOS and Windows installers bundle Python and application dependencies.
Source development installs `requirements.txt` into a separate virtual environment.
The versions below are the September 24 source-environment audit snapshot, not
an installation lock or an inventory of every component in either installer.
Use each release's build manifest and shipped component notices for its exact
versions. Preserve the original licenses and any source-provision obligations.

The macOS standalone builder includes CPython from python-build-standalone and
its transitive runtime components. Inside the App's `Contents/Resources`,
`Runtime Licenses/<architecture>/` contains the matching runtime metadata and
license texts; `dependencies/` contains Python package source, metadata and
licenses. `Standalone Build.json` and `BUNDLED_RUNTIME_NOTICES.txt` describe that
build. A CPython license alone does not cover every library bundled with it.

The Windows release also bundles .NET and reuses or installs Microsoft WebView2.
Their terms, Python runtime notices, package licenses and any bundled native
components must be reviewed against that Windows build. Follow its included
notices and build manifest; the macOS inventory is not a Windows license audit.
See [distribution guidance](DISTRIBUTION.md) for the platform release links.

| Component | Audited version | License | Upstream information |
|---|---|---|---|
| requests | 2.32.5 | Apache-2.0 | https://pypi.org/project/requests/2.32.5/ |
| beautifulsoup4 | 4.14.3 | MIT | https://pypi.org/project/beautifulsoup4/4.14.3/ |
| pypdf | 6.11.0 | BSD-3-Clause | https://pypi.org/project/pypdf/6.11.0/ |
| charset-normalizer | 3.4.7 | MIT | https://pypi.org/project/charset-normalizer/3.4.7/ |
| idna | 3.15 | BSD-3-Clause | https://pypi.org/project/idna/3.15/ |
| urllib3 | 2.6.3 | MIT | https://pypi.org/project/urllib3/2.6.3/ |
| certifi | 2026.4.22 | MPL-2.0 | https://pypi.org/project/certifi/2026.4.22/ |
| soupsieve | 2.8.3 | MIT | https://pypi.org/project/soupsieve/2.8.3/ |
| typing_extensions | 4.15.0 | PSF-2.0 and included historical notices | https://pypi.org/project/typing-extensions/4.15.0/ |

certifi includes Mozilla CA certificate data subject to MPL-2.0. Its covered
files retain that license, including its source-availability obligations when
redistributed; they are not relicensed under Gewu's research-only terms.
The current source/package is available at the versioned PyPI location above
and https://github.com/certifi/python-certifi; MPL-2.0 is available at
https://www.mozilla.org/MPL/2.0/.

Optional crypto support and unrelated local documentation tools are not default
requirements. If adding their wheels or binaries to a distribution, retain all
of their own embedded component notices, not just the top-level license label.

## System components and external tools

The macOS native App uses system frameworks including Cocoa/AppKit, WebKit,
Quartz/PDFKit, ImageIO and Quick Look; these remain under their respective Apple
and third-party terms. Their implementations are not copied into the App.
System commands are invoked as separate programs. Optional LibreOffice and TeX
installations are supplied separately by the user. Pandoc is a GPL-licensed
manual-build tool, not a bundled runtime library. None of those programs is
relicensed by Gewu. The audit describes the precise usage and limitations.

## Fonts, artwork and content

System fonts used in the generated manual retain their own display/embedding
terms; no standalone font files are shipped. In particular, document embedding
permissions do not imply permission to distribute or relicense the fonts.

The seal artwork uses Hanyi seal-script glyphs. The About wordmark was composed
from four externally sourced historical-calligraphy images, identified in the
User Guide. The repository does not include proof of the relevant artwork/font
redistribution permissions. Gewu's LICENSE does not clear those rights. Confirm
those permissions before public or commercial redistribution; original project
contributions do not erase rights in the underlying materials.

Paper figures, journal marks, author portraits and other third-party content
visible in screenshots remain with their respective owners. Viewing content or
having a software license does not grant independent reuse of that content.

For the full inventory, source evidence and unresolved issues, see
`docs/DEPENDENCY_LICENSE_AUDIT.md` in the complete distribution. This notice is
not a claim that every future dependency version or distribution is cleared.
