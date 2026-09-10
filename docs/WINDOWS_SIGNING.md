# Windows signing and local installation recovery

## Current result: 0.1.13 installed and normally reopened (2026-09-10)

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
