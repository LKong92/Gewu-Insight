#ifndef PayloadDir
  #error PayloadDir must point to the reviewed Windows payload
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installers"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{4B15D2D9-CC72-4160-A56C-3E1FE830D20C}
AppName=Gewu Insight Windows Preview
AppVersion={#AppVersion}
AppPublisher=Gewu Insight
DefaultDirName={localappdata}\Programs\Gewu Insight Preview
DefaultGroupName=Gewu Insight Preview
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDir}
OutputBaseFilename=Gewu-Insight-Windows-Preview-{#AppVersion}-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=GewuInsight.ico
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Gewu Insight.exe
CloseApplications=no
RestartApplications=no
InfoBeforeFile=PREVIEW.txt
SignTool=gewu
SignedUninstaller=yes
SignToolRunMinimized=yes

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Gewu Insight Preview"; Filename: "{app}\Gewu Insight.exe"; IconFilename: "{app}\GewuInsight.Taskbar.ico"; AppUserModelID: "GewuInsight.Windows.Preview"
Name: "{group}\Uninstall Gewu Insight Preview"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Gewu Insight.exe"; Description: "Open Gewu Insight Preview"; Flags: nowait postinstall skipifsilent

; Data is stored outside {app}. No UninstallDelete section: uninstall retains
; the Library, SQLite database, reports and the separate WebView2 profiles.
