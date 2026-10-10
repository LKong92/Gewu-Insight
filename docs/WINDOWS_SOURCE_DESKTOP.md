# Windows desktop development and installed startup

Normal use opens **Gewu Insight** from the Start menu after installing
[Windows Setup](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0).
`Start Gewu Insight.cmd` opens that installed shortcut. It does not start a
0.1.21 source shell, select a Preview database or load changes from this checkout.

Develop on `Windows` using an isolated database, build a fresh Setup, install
locally and validate the installed App. See [development](DEVELOPMENT.md) for
commands and [distribution](../DISTRIBUTION.md) for requirements and provenance.

The historical `scripts/windows_source.py` desktop mode remains a diagnostic
tool for compatible test shells. Supply an explicit test executable and isolated
workspace if exercising it; it is not the daily-use or release-acceptance path.
[Source Web](WINDOWS_SOURCE_WEB.md) is available for isolated web diagnostics.

Earlier 0.1.19–0.1.21 installation records are retained in Git history and the
ignored local development archive, not as current setup instructions.
