# Windows signing and local installation recovery

## Current direction: 0.1.20 desktop shell with local source (2026-09-29)

The user clarified that Gewu must retain its independent desktop window and
match 0.1.20. The default CMD launcher now starts the existing complete 0.1.20
build with this checkout's Python service. About confirms 0.1.20; Library and
embedded Browser/history render, and normal close/service exit/lock release and
CMD reopening pass. The 0.1.20 Nature Python and C# fixes are both included.
See [Desktop from Source](WINDOWS_SOURCE_DESKTOP.md). Source Web is optional
through `--web`; the installed 0.1.19 and its verified recovery backup remain.

The exact formerly blocked 0.1.20 DLL now passes isolated source startup and
the original-Library launch; why Windows allows it now is unknown. All 2,266
payload hashes match. Protected DB tables and 19 research files remain intact:
schema 18, 4,442 papers, 39 Publications, 10 Library items, 5 folders, 6 resources,
integrity OK/zero foreign-key errors. Only automatic monitor state settings
change. Seven launcher checks, six download-fallback checks and Python compile
pass. Evidence: `tmp/windows-desktop-source-20260929/`; the earlier full recovery
backup remains in `tmp/windows-source-20260929/`.

This is the user's explicitly chosen source-desktop delivery, with no installer,
signing enrollment, security/trust changes, external submission or commit/push.
The fresh unsigned release-preflight failure below remains valid; local startup
does not satisfy formal release acceptance. Do not request a signing identity
for this chosen source route. Real publisher download acceptance is not repeated
in this run.

## Earlier direction: Source Web, superseded by desktop source (2026-09-29)

The user rejected solutions requiring publisher signing and explicitly accepted
the source web interface with a convenient launcher. `Start Gewu Insight.cmd`
now opens the existing Library using the source Python service and the default
browser; see [Source Web](WINDOWS_SOURCE_WEB.md). Do not continue asking for a
publisher identity or signing account for this chosen route. The native release
checks remain in place for any future desktop release.

Fresh static checks still reject the unchanged 0.1.20 desktop package: 2,266
manifest hashes match, 75 of 375 binaries lack valid RSA signatures, and Setup
is unsigned. Installed 0.1.19 was independently verified by file version and
SHA-256. No blocked component or installer was retried. The original App was
closed normally, a 2,339-file recovery backup verified, and Source Web started
through the actual CMD launcher. Four authenticated/health endpoint checks,
2,266 unchanged installed payload hashes, all protected database table digests
and 19 research files pass: schema 18, 4,442 papers, 39 Publications, 10 Library
items, 5 folders, 6 resources, integrity OK and zero foreign-key errors. Only
the automatic arXiv retry-state setting changed during startup.

Three new launcher checks pass, including real subprocess authentication and
exclusive locking; the original native App's lock also rejects a source launch.
The pre-existing isolated source smoke, Python compile and scoped diff checks
pass. Chrome exposes a `Gewu Insight - Google Chrome` window, but Computer Use
stopped before visual inspection because it could not confidently determine
the browser URL; no full visual acceptance is claimed. Evidence and recovery
backup: `tmp/windows-source-20260929/`; fresh native preflight:
`tmp/windows-delivery-20260929/release-preflight.json`.

This is a working source-service alternative, not a completed 0.1.20 desktop
upgrade. Native Browser/PDF integration and the native Nature change are not
delivered. No security-policy change, external submission, commit, push or public
release occurred. The historical RSA-only explanation below reflects the earlier
guidance; Microsoft's current signing page now also lists ECC support. The
project's existing RSA-only release check has not been broadened or revalidated
for ECC as part of this source-only task.

## Earlier result: 0.1.19 running; 0.1.20 blocked; release checks strengthened (2026-09-11)

The repeated failures were never permanently resolved by the earlier unsigned
local installations. The 0.1.20 application-control error identifies the new
Gewu DLL (`0x800711C7`); the unchanged package has 375 binary components, 300
valid RSA signatures and 75 unsigned files. The unsigned Setup is another
untrusted component. These are component trust failures, not a damaged Library
or a Nature subscription failure. A prior unsigned release running does not
establish acceptance of a later build. The actual installed version remains
0.1.19; the blocked 0.1.20 installer has not been run.

The user confirms having no existing signing certificate or service account.
Read-only certificate-store checks also find zero code-signing certificates;
Smart App Control stays ON (1). Publisher identity (individual/organization and
country) is pending before selecting a compatible service. The current official
[Artifact Signing prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
allow individuals in the US/Canada and organizations in the documented countries,
including Japan; do not infer eligibility from the computer's locale. The
proprietary/free-use license and earlier refusal of external file review remain.
No purchase, registration, submission or security/trust change was performed.

`scripts/windows_release.ps1` and `scripts/test_windows_release.ps1` now enforce
fresh static checks of every payload file against its manifest, real RSA
signatures on every EXE/DLL/PYD, verified timestamps on the Gewu shell and Setup,
consistent publisher identity, and matching payload/installer versions. Extra,
missing, modified, linked, duplicate or unsafe manifest paths stop acceptance.
The report is stored outside the payload and explicitly says
`RuntimeValidated: false`: static checks do not replace real startup tests.
The standard builder calls the check after signed installer creation. The pending
0.1.20 upgrade and direct install scripts call it before closing the working App
or executing Setup; cached process-creation checks are insufficient. Future
updates must use this flow, not temporary unsigned Inno recipes.

```powershell
./scripts/test_windows_release.ps1 -PayloadPath dist/windows-preview-0.1.20 `
  -InstallerPath PATH_TO_SIGNED_SETUP -Version 0.1.20 `
  -ReportPath tmp/release-preflight.json
```

Validation: 26 release checks pass (17 real disposable-manifest/guard cases plus
9 policy cases with explicitly synthetic signature/version metadata), and the
existing 5 real signing/Inno safeguards pass. Four PowerShell syntax checks,
upgrade-script Python compilation and diff checks pass. The actual unchanged
0.1.20 release fails preflight with its 2,266 file hashes intact and the 75
unsigned components/unsigned Setup reported; it is not launched. Evidence:
`tmp/install-0.1.20-20260911/release-preflight.json`,
`tmp/release-preflight-859b485f2a3a4c4fb33fbb34ab37958a/`,
`tmp/signing checks $literal 9b9d503ef1624211955274ac616aa95f/`.
No real signed Gewu release has been produced or accepted yet. Signing credentials
and subsequent installed/runtime verification remain necessary; this is not a
promise that every future operating-system or dependency failure is impossible.

## Earlier result: 0.1.13 installed and normally reopened (2026-09-10)

The verified 0.1.13 payload was packaged with the existing temporary local
unsigned Inno recipe and installed successfully at 18:40 JST (exit 0, no Windows
restart). Installer SHA-256:
`F228D2269CB6DC1D2CA3AC9982135E67704FBF1C591D5CD849A4A92386A17A40`.
All 2109 manifest-listed installed payload files match. Two actual-install-path
starts with a disposable Library pass, followed by opening the original Library
and normally closing/reopening it. At 18:47 JST the original window is visible,
file and uninstall versions are 0.1.13, and four live API checks pass. All protected
paper/Library/Publications/bookmark/history rows and 17 persistent research/cache
files remain unchanged; schema 18 integrity and foreign keys pass. Only two
automatic monitor status settings change on restart. The verified backup contains
2317 files; evidence is ignored `tmp/install-0.1.13-20260910/`.

The installer and Gewu DLL remain unsigned; Smart App Control remains ON (1).
No protection-policy, trust-store or external-review change occurred. The standard
release signing gate remains unchanged. Local installation does not establish
publisher signing or acceptance on other machines. No commit or push occurred.

## Earlier result: 0.1.12 installed and normally reopened (2026-09-10)

At the user's request, the exact previously blocked installer was retried and
completed successfully at 17:49 JST (exit 0, no Windows restart). Its SHA-256 is
still `FF5E66709A62BBCB989C7B869573DB051243E342A6EC1AB7D4B16F0ACA189E11`.
No rebuild, renaming, signing, external submission, protection-policy change or
trust-store change occurred. Smart App Control remains ON (1). The evidence
does not establish why Windows now permits the same installer.

The installed file and uninstall-registration versions are 0.1.12; all 2109
payload files match the validated development package. The actual installed
EXE passes two hidden-desktop starts with a disposable Library. The original
Library then opens and normally closes/reopens; the window is visible and four
live API checks plus the Browser asset hash pass (17:53 JST). All 44 paper rows,
Library/Publications/bookmarks/history and 17 persistent research/cache files
remain intact; schema 18 integrity and foreign keys pass. Only the two automatic
monitor status settings change on restart. Fresh verified backup and evidence:
ignored `tmp/install-0.1.12-retry-20260910/`.

The installer and Gewu DLL remain unsigned. This is a successful local Preview
installation, not a completed publisher-signing solution or a guarantee for
other machines. The standard release signing gate is unchanged. No commit or
push was performed. Earlier failed-attempt evidence is retained below.

## Earlier 0.1.12 local installation block (2026-09-10)

The user requested directly installing the tested 0.1.12 development payload.
The earlier stop was the standard builder's conservative signing gate, not an
observed Windows installation failure. A temporary explicitly unsigned local
Inno recipe then produced an installer without changing the standard release
script. Windows blocked this installer before execution (Code Integrity
3077/3033); no installer log or installed-file change occurred. This block is
specific evidence about the installer, while the earlier two development-path
0.1.12 native launches passed. No installation-path 0.1.12 launch was performed.

The original 0.1.11 window was reopened, all 2111 installed files match the
backup, and the 44 paper rows plus Library/Publications/bookmarks/history and
research files remain intact. Smart App Control stays ON (1); no protection,
trust, external review, commit or push change was made. Evidence and rollback
copy: ignored `tmp/install-0.1.12-20260910/`. See the latest Preview status.

## Earlier 0.1.11 recovery result

**Windows Preview 0.1.11 is now installed and running**, including a normal
close/reopen of the original Library (2026-09-10, verified at 15:48 JST).
At 15:37 JST the exact previously blocked DLL passed a hidden-desktop launch;
the original installer then restored 0.1.11, and an isolated launch from the
actual installation path passed before opening the real Library. The About
dialog shows 0.1.11; Library, the new AI Access menu, authenticated workspace
and service respond normally. Smart App Control remains enabled (state 1).

The DLL is still unsigned and has the original SHA-256
`F7E53BDE8D88469F96BC51264720B6E28493460EC49ED8E830E5EC58E09349B4`.
No executable was modified or rebuilt, no signature was added, no file was
submitted for external review, and no security policy or trust store was changed.
This is a verified local recovery, not a demonstrated permanent signing fix.
The available evidence does not identify why the same file is now allowed;
do not attribute it to a proven cloud-reputation update or path exception.

Earlier that day the DLL was rejected with Code Integrity 3033/3077 and .NET
1026, `0x800711C7`, under Smart App Control policy
`0283ac0f-fff1-49ae-ada1-8a933130cad6`. Running as administrator did not resolve
that observed block; 0.1.10 was temporarily restored at 15:14 JST. These are
historical failures, not the current installed state. Current backups and
verification are in `tmp/reinstall-0.1.11-20260910/`; details and data boundaries
are in [Preview status](WINDOWS_PREVIEW_STATUS.md).

The 0.1.10 and 0.1.11 native DLLs are both unsigned. Their build configuration
and bundled .NET 10.0.11 versions are unchanged. Local events do not establish
why the earlier file was permitted. A file's reputation can change, so an
earlier unsigned release passing is not reliable evidence for the next release.
See Microsoft's [signature guidance](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control).

Read-only audit of the 0.1.11 payload found 375 EXE/DLL/PYD files: 300 have valid
RSA signatures and 75 are unsigned, including the Gewu shell and native Python
dependencies. This is an inventory, not evidence that every unsigned dependency
has been blocked. Original dependency notices remain packaged. The selected
research database and files were not changed during this signing work.

## License decision: free use, proprietary source

The user explicitly clarified the intended model as free use with the current
proprietary license retained. Do not change the source license to MIT or another
open-source license. Charging for software is unrelated to the Windows trust
decision; a paid personal certificate is not the only route to investigate.

[SignPath Foundation](https://signpath.org/) provides free signing to accepted
open-source projects, using its foundation certificate and verified build
provenance rather than requiring each maintainer to purchase a personal
certificate. Acceptance is reviewed and is not guaranteed. Its
[conditions](https://signpath.org/terms) require an OSI-approved license, an
actively maintained and released project, verified builds and approval roles.

The root `LICENSE` is explicitly titled "Gewu Insight Proprietary License";
README repeats that it is not an open-source license. Both remain unchanged.
The user's clarification closes the earlier ambiguity: SignPath Foundation's
open-source-only program is not applicable to this selected licensing model.
No application to that program should be made claiming this project is OSS.

Foundation certificates may sign the project's own builds; their terms prohibit
re-signing third-party binaries under the project's foundation subscription.
Unsigned upstream libraries may be included in packages under their terms.
Therefore the existing local-certificate helper is not a ready-made SignPath
integration, and the 73 unsigned third-party files must not be automatically
signed with a foundation project certificate. Upstream signatures and the actual
Windows runtime paths need review if this route is selected.

The builder's strict signature gate is a local conservative release safeguard,
not a universal requirement that every Windows application must buy a certificate.
Its addition occurred after the original 0.1.11 runtime block and did not cause
that block. No signing service application, publication or paid purchase has
been made. The earlier request for personal/company signing identity is not a
prerequisite for the Microsoft file-review route below.

## Cancelled option: Microsoft Smart App Control file review

The user explicitly rejected external review. No files were uploaded or
submitted. Do not submit these drafts, reopen the submission flow, or keep
asking for the same approval. Continue only with local diagnosis and recovery
unless the user later changes this restriction explicitly.

The official [Microsoft Security Intelligence submission portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
explicitly offers Smart App Control as a product and accepts files believed to
have been incorrectly classified. It asks for the specific affected file rather
than a whole installer. This route does not require declaring the software open
source or supplying a signing certificate. Review is not a guaranteed or instant
allow decision, and a favorable result must be followed by actual launch tests.

A local review draft is prepared under `tmp/microsoft-sac-review-0.1.11/`:

- `Gewu Insight.dll`: exact installed file, 215040 bytes, SHA-256
  `F7E53BDE8D88469F96BC51264720B6E28493460EC49ED8E830E5EC58E09349B4`.
- `submission.txt`: 1671-character English description within the form's 1900-character limit.
- `REVIEW.md`: user-facing scope and submission explanation.

Only the blocked DLL and factual description are proposed for submission. No
research library, papers, notes, credentials, browser profile, separate source
file or PDB is included. The DLL itself contains proprietary compiled code,
embedded application resources and normal build metadata. Microsoft's submission
consent describes storage of analysis data in the United States. The form may
require user login or human verification. Do not invent a company or detection
name; the observed events provide only an application-control block.

Nothing has been uploaded or submitted. The user refused this concrete
submission; the draft is retained only as a local historical artifact. Later
local retesting and reinstallation restored 0.1.11 startup, as recorded above.
The cancelled submission played no part in that recovery.

For a future distribution route, Microsoft also documents [Store MSIX signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options):
the Store re-signs MSIX packages after certification without a publisher-managed
certificate purchase. An EXE/MSI submission does not get the same re-signing.
This would require packaging work, a developer account and Store submission;
none of those actions has been performed or represented as an immediate fix.

## Existing publisher-certificate release path

Use the actual publisher's RSA code-signing certificate from a trusted provider,
or a Microsoft Artifact Signing **Public Trust** profile with completed identity
validation. Smart App Control currently requires RSA certificates; a locally
invented certificate does not establish public publisher trust. Microsoft
documents [supported certificates](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
and [Artifact Signing prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).

The publisher must complete identity verification and authorize any fees. No
purchase, account registration, software submission, public release, certificate
trust-store edit, or Windows policy change has been performed. CurrentUser and
LocalMachine personal stores contain no code-signing certificate. Whether the
publisher already has a remote signing account remains unanswered.

`scripts/build_windows.ps1` now requires `-SigningConfiguration` whenever
`-InnoCompiler` is provided. It signs unsigned PE binaries, preserves valid
upstream signatures, refuses to overwrite invalid signatures, and verifies
SHA-256/RFC3161 timestamped output. The complete payload must pass the valid RSA
signature check before an installer is built. Hashes are generated after signing.
Inno calls the same signer for Setup, its temporary copies and the uninstaller.
The final Setup signature is checked again. Omitting signing and Inno produces
only an explicitly unsigned development payload.

These checks do not certify licensing, grant publisher identity, or guarantee all
runtime behavior. After real signing, test the original app's startup, authenticated
workspace, Browser, PDF preview and file recovery with Smart App Control still
enabled. Install only after isolated acceptance passes, then verify installed
hashes, process paths, original Library identity and database integrity.

## Configuration

Keep local configuration under ignored `tmp/`; do not include passwords,
private keys or access tokens. The configuration selects existing signing
credentials; it does not import or manufacture certificates.

For a CA-issued RSA certificate accessible through the current user's Windows
certificate store (including an authorized token/HSM provider):

```json
{
  "Mode": "CertificateStore",
  "SignTool": "C:\\path\\to\\Microsoft-Windows-SDK\\x64\\signtool.exe",
  "Thumbprint": "REPLACE_WITH_THE_ACTUAL_40_HEX_CERTIFICATE_THUMBPRINT"
}
```

For a completed Microsoft Public Trust signing profile:

```json
{
  "Mode": "ArtifactSigning",
  "SignTool": "C:\\path\\to\\Microsoft-Windows-SDK\\x64\\signtool.exe",
  "Dlib": "C:\\path\\to\\official-client\\x64\\Azure.CodeSigning.Dlib.dll",
  "Metadata": "C:\\path\\to\\local\\artifact-metadata.json"
}
```

Create the metadata file using the account's actual regional endpoint,
`CodeSigningAccountName` and `CertificateProfileName`; authenticate through the
publisher's approved Azure credential provider. Required client/runtime versions
and authentication are in Microsoft's [integration instructions](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations).
The script verifies Microsoft signatures on SignTool and the client library.

The official SDK tool prepared locally is
`tmp/windows-toolchain/sdk-buildtools-10.0.28000.2705/bin/10.0.28000.0/x64/signtool.exe`.
Its Microsoft Authenticode signature and independent `signtool verify /pa` check
passed. A real publish command, after replacing paths and obtaining credentials:

```powershell
./scripts/build_windows.ps1 -Version 0.1.12 `
  -PythonRuntime PATH_TO_OFFICIAL_EMBEDDED_PYTHON `
  -Dotnet PATH_TO_DOTNET -InnoCompiler PATH_TO_ISCC `
  -SigningConfiguration tmp/publisher-signing.json
```

Version 0.1.12 has now been built and installed locally as an unsigned Preview,
as recorded above. No successful signing is claimed until an actual publisher
credential is used.

## Local evidence

- Prior application and coherent research backup: `tmp/install-0.1.11-20260910/`.
- Original audit: `payload-signatures.json`; release-gate audit: `signature-gate-report.json` in that folder.
- The actual 0.1.11 payload fails the gate with exactly 75 of 375 unsigned binaries.
- Microsoft SignTool independently accepts its own signed binary and rejects the installed Gewu DLL as unsigned.
- `tests/test_windows_signing.ps1` verifies missing-credential rejection, unchanged vendor binaries, refusal to overwrite damaged signatures, and the actual Inno failure path with spaces/dollars in paths. Run it with `-SignTool PATH_TO_MICROSOFT_SIGNTOOL -InnoCompiler PATH_TO_ISCC`. Results stay in its isolated `tmp/` fixture directory.

Inno's [SignTool integration](https://jrsoftware.org/ishelp/topic_setup_signtool.htm)
and [signed uninstallers](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm)
cover Setup and uninstall signing. No `--no-signing` or signature-check suppression
is used by the builder.
