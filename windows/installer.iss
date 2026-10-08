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
; The bundled .NET 10 runtime supports Windows 10 starting with 1607.
; Do not require 2004: that unnecessarily excludes 1607/1809 LTSC and 1909.
MinVersion=10.0.14393
OutputDir={#OutputDir}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=GewuInsight.ico
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayIcon={app}\Gewu Insight.exe
RestartApplications=no

[Messages]
WindowsVersionNotSupported=Gewu Insight requires 64-bit Windows 10 version 1607 (build 14393) or later. This x64 installer does not support 32-bit Windows or Windows 10 on ARM.

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
  DatabaseModePage: TInputOptionWizardPage;
  DatabaseDirectoryPage: TInputDirWizardPage;
  KeepDatabaseSelection: Boolean;
  SavedDatabasePath: String;

function InitializeSetup(): Boolean;
begin
  { Per-user installation must run as the daily user, never a different elevated
    administrator. This also makes reinstall discovery and ownership unambiguous. }
  Result := not IsAdminLoggedOn;
  if not Result then
    MsgBox('Run Setup normally from your Windows account, without Run as administrator. Gewu Insight installs for the current user and preserves that user''s database location.', mbError, MB_OK);
end;

procedure InitializeWizard();
var
  LegacyDatabasePath: AnsiString;
  RequestedDatabasePath: String;
begin
  SavedDatabasePath := GetIniString('database', 'path', '', ExpandConstant('{%USERPROFILE}\.gewu-insight\database-location.ini'));
  if SavedDatabasePath = '' then begin
    if LoadStringFromFile(ExpandConstant('{%USERPROFILE}\.gewu-insight\preview-workspace.txt'), LegacyDatabasePath) then
      SavedDatabasePath := Utf8Decode(LegacyDatabasePath);
  end;
  SavedDatabasePath := Trim(SavedDatabasePath);
  DatabaseModePage := CreateInputOptionPage(wpSelectDir, 'Gewu Database',
    'Choose where to keep your research data',
    'The database is separate from the software installation. Uninstalling Gewu Insight keeps your research data.', True, False);
  DatabaseModePage.Add('Create new Gewu Database');
  DatabaseModePage.Add('Use existing Gewu Database');
  DatabaseDirectoryPage := CreateInputDirPage(DatabaseModePage.ID, 'Gewu Database location',
    'Select the database root directory',
    'An existing database contains data\paper_monitor.sqlite. For a new database, choose a new or empty folder.', False, 'Gewu Database');
  DatabaseDirectoryPage.Add('Gewu Database:');
  if SavedDatabasePath <> '' then begin
    DatabaseModePage.SelectedValueIndex := 1;
    DatabaseDirectoryPage.Values[0] := SavedDatabasePath;
  end else begin
    DatabaseModePage.SelectedValueIndex := 0;
    DatabaseDirectoryPage.Values[0] := ExpandConstant('{%USERPROFILE}\Gewu Database');
  end;
  RequestedDatabasePath := ExpandConstant('{param:DATABASEDIR|}');
  if RequestedDatabasePath <> '' then DatabaseDirectoryPage.Values[0] := RequestedDatabasePath;
  if ExpandConstant('{param:DATABASEMODE|}') = 'existing' then DatabaseModePage.SelectedValueIndex := 1;
  if ExpandConstant('{param:DATABASEMODE|}') = 'new' then DatabaseModePage.SelectedValueIndex := 0;
  WebView2ProgressPage := CreateOutputMarqueeProgressPage(
    'Installing Microsoft WebView2',
    'WebView2 is required to display Gewu Insight.');
end;

function DatabaseSelectionError(): String;
var
  DatabasePath, InstallPath: String;
  Entry: TFindRec;
begin
  Result := '';
  DatabasePath := RemoveBackslashUnlessRoot(Trim(DatabaseDirectoryPage.Values[0]));
  InstallPath := RemoveBackslashUnlessRoot(WizardDirValue);
  if (Length(DatabasePath) < 3) or (DatabasePath[2] <> ':') or (DatabasePath[3] <> '\') then begin
    Result := 'Choose an absolute local disk path, such as D:\Research\Gewu Database.'; Exit;
  end;
  if (CompareText(DatabasePath, InstallPath) = 0)
    or (CompareText(Copy(DatabasePath, 1, Length(InstallPath) + 1), InstallPath + '\') = 0)
    or (CompareText(Copy(InstallPath, 1, Length(DatabasePath) + 1), DatabasePath + '\') = 0) then begin
    Result := 'Choose separate software and database directories.'; Exit;
  end;
  if DatabaseModePage.SelectedValueIndex = 1 then begin
    if not FileExists(DatabasePath + '\data\paper_monitor.sqlite') then
      Result := 'The existing Gewu Database was not found. Reconnect its disk or select its root directory. No empty database will be created.';
  end else if DirExists(DatabasePath) then begin
    if FindFirst(DatabasePath + '\*', Entry) then begin
      try
        repeat
          if (Entry.Name <> '.') and (Entry.Name <> '..') then
            Result := 'A new Gewu Database needs an empty directory. Existing files will not be overwritten or merged.';
        until not FindNext(Entry);
      finally
        FindClose(Entry);
      end;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if CurPageID = DatabaseDirectoryPage.ID then begin
    Error := DatabaseSelectionError();
    Result := Error = '';
    if not Result then MsgBox(Error, mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Mode, Directory: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Directory := Trim(DatabaseDirectoryPage.Values[0]);
  { Leave an unchanged locator intact on updates, including its expected identity.
    The application validates disk availability, identity, locks and schema. }
  KeepDatabaseSelection := (SavedDatabasePath <> '') and
    (CompareText(Directory, SavedDatabasePath) = 0) and
    FileExists(ExpandConstant('{%USERPROFILE}\.gewu-insight\database-location.ini')) and
    (DatabaseModePage.SelectedValueIndex = 1);
  if KeepDatabaseSelection then Exit;
  if DatabaseModePage.SelectedValueIndex = 0 then Mode := 'new' else Mode := 'existing';
  if not ExecAsOriginalUser(ExpandConstant('{app}\Gewu Insight.exe'),
    '--configure-database ' + Mode + ' "' + Directory + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    RaiseException('Database selection could not start. Open Gewu Insight to select your database.');
  if ExitCode <> 0 then
    RaiseException('Database selection failed. The previous location is retained. Open Gewu Insight to choose a valid database.');
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
  Result := DatabaseSelectionError();
  if Result <> '' then Exit;
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
