#ifndef PayloadDir
  #error PayloadDir must point to the reviewed Windows payload
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installers"
#endif
#ifndef AppVersion
  #error AppVersion must identify the reviewed Windows payload
#endif
#ifndef WebView2Bootstrapper
  #error WebView2Bootstrapper must point to the verified official Evergreen Bootstrapper
#endif

[Setup]
AppId={{C8772BBC-43B6-41D3-85E8-9034A8E9BA66}
AppName=Gewu Insight
DefaultDirName={localappdata}\Programs\Gewu Insight
DefaultGroupName=Gewu Insight
OutputBaseFilename=Gewu-Insight-Windows-{#AppVersion}-x64-Setup
InfoBeforeFile={#PayloadDir}\PREVIEW.txt
LicenseFile={#PayloadDir}\LICENSE
CloseApplications=yes
SignedUninstaller=no
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
VersionInfoProductVersion={#AppVersion}.0
VersionInfoProductTextVersion={#AppVersion}
AppPublisher=Gewu Insight
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDir}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=GewuInsight.ico
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Gewu Insight.exe
RestartApplications=no

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Gewu Insight"; Filename: "{app}\Gewu Insight.exe"; IconFilename: "{app}\GewuInsight.Taskbar.ico"; AppUserModelID: "GewuInsight.Windows.Preview"
Name: "{group}\Uninstall Gewu Insight"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Gewu Insight.exe"; Description: "Open Gewu Insight"; Flags: nowait postinstall skipifsilent

; Data is stored outside {app}. No UninstallDelete section: uninstall retains
; the Library, SQLite database, reports and the separate WebView2 profiles.

[Code]
var
  WebView2ProgressPage: TOutputMarqueeProgressWizardPage;

procedure InitializeWizard();
begin
  WebView2ProgressPage := CreateOutputMarqueeProgressPage(
    'Installing Microsoft WebView2',
    'WebView2 is required to display Gewu Insight.');
end;

function HasWebView2At(Root: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root,
    'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
    and (Version <> '') and (Version <> '0.0.0.0');
end;

function HasWebView2(): Boolean;
begin
  Result := HasWebView2At(HKCU) or HasWebView2At(HKLM32);
  if IsWin64 then
    Result := Result or HasWebView2At(HKLM64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2() then begin
    Log('Using the existing Microsoft WebView2 Runtime.');
    Exit;
  end;
  WebView2ProgressPage.SetText(
    'Downloading and installing WebView2 from Microsoft...',
    'Please stay connected to the internet. This may take a few minutes.');
  WebView2ProgressPage.Show;
  try
    WebView2ProgressPage.Animate;
    ExtractTemporaryFile('MicrosoftEdgeWebView2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2Setup.exe'),
        '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      Result := 'Microsoft WebView2 Setup could not start. Gewu Insight has not been installed. Please try Setup again.';
      Exit;
    end;
    Log(Format('Microsoft WebView2 Bootstrapper finished with code %d.', [ExitCode]));
    if not HasWebView2() then
      Result := Format('Microsoft WebView2 could not be downloaded or installed (code %d). Check your internet connection and try Setup again. Gewu Insight has not been installed.', [ExitCode]);
  finally
    WebView2ProgressPage.Hide;
  end;
end;
