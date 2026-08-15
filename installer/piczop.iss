; Windows installer for Piczop. Compile with Inno Setup 6 (ISCC.exe).
; Expects a prior build: dist\Piczop\Piczop.exe from scripts\build-windows.ps1
; Prefer: powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1

#define MyAppName "Piczop"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Piczop"
#define MyAppExeName "Piczop.exe"
#define MyAppURL "https://github.com/axstart/Piczop"

[Setup]
AppId={{8F3C2A11-6B4E-4D9A-9C1F-A1B2C3D4E5F6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
InfoBeforeFile=portable-note.txt
OutputDir=..\dist
OutputBaseFilename=Piczop-Setup
SetupIconFile=..\assets\piczop.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Skip empty PiczopLibrary from the build tree — app creates it next to the exe when
; writable, or under %LOCALAPPDATA%\Piczop\ when installed to Program Files.
Source: "..\dist\Piczop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "PiczopLibrary"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Piczop"; Flags: nowait postinstall skipifsilent
