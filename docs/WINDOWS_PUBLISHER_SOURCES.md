# Windows publisher delivery sources

Reviewed 2026-09-10 for Preview 0.1.16. This source review identifies publisher
delivery hosts; it does not establish a user's subscription or bypass any access
check. Every redirect still passes both the reviewed source policy and the
requested publisher scope.

| Added source | Primary evidence and scope |
| --- | --- |
| `acs.figshare.com` | [ACS research-data policy](https://www.acs.org/policy/publicpolicies/science-policy/highqualityscience.html) identifies its partnership for article supporting information; the [ACS repository](https://acs.figshare.com/) identifies the tenant. Only this tenant is included; arbitrary Figshare, ndownloader or S3 hosts are not allowed. |
| `sciencedirectassets.com` and subdomains | [Elsevier's access documentation](https://www.elsevier.support/elsevieraccess/answer/how-can-i-allowlist-your-product-in-our-firewall) explicitly lists this domain for ScienceDirect (updated 2026-08-04). |
| `oup.silverchair-cdn.com`, `watermark.silverchair.com` | [OCLC's official Oxford Academic EZproxy configuration](https://help.oclc.org/Library_Management/EZproxy/EZproxy_database_stanzas/Database_stanzas_O/Oxford_Academic_(formerly_Oxford_Journals)) lists these exact delivery hosts. This is the access-integration vendor's source; other Silverchair tenant hosts are excluded. |

The hidden publisher session may activate one visible, unambiguous PDF control
per page when no unused supported link is available. Forms, dialogs, disabled
controls and non-PDF labels are excluded. Verified PDF response bodies can come
from document navigation or Fetch/XHR; other application responses continue to
the page. The same 64 MB/time limits, original-byte validation and existing
Library classification apply. Preview 0.1.17 additionally accepts one hidden
popup from the selected PDF control, preserving its original POST and remote
session. Unexpected or extra windows and unknown cloud-storage routes stop;
complex popup/authentication routes are not presented as universally supported.

Monitor cache maintenance uses WebView2's explicit
[`DiskCache` profile operation](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2profile.clearbrowsingdataasync)
on the trusted local workspace profile. It does not call the all-data overload,
touch the remote Browser profile, delete SQLite results, or clear saved files.
