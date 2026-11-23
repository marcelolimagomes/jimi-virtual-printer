#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif

[Setup]
AppId={{82A5A0D4-4E96-4FC8-BCB8-F6F58F86357C}
AppName=POSvirtual
AppVersion={#AppVersion}
AppPublisher=Taskblu
AppPublisherURL=https://www.taskblu.com/
AppSupportURL=https://www.taskblu.com/
AppUpdatesURL=https://www.taskblu.com/
AppCopyright=Copyright (C) 2026 Taskblu
AppComments=Impressora térmica virtual ESC/POS da Taskblu
AppReadmeFile={app}\README.md
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=Taskblu
VersionInfoDescription=Instalador Taskblu POSvirtual
VersionInfoCopyright=Copyright (C) 2026 Taskblu
VersionInfoProductName=POSvirtual
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Taskblu\POSvirtual
DefaultGroupName=Taskblu\POSvirtual
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\windows\installer
OutputBaseFilename=POSvirtual-Setup-{#AppVersion}
UninstallDisplayIcon={app}\tray\POSvirtualTray.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "autostart"; Description: "Iniciar POSvirtual ao entrar no Windows"; GroupDescription: "Inicialização:"

[Dirs]
Name: "{localappdata}\Taskblu\POSvirtual\PDF"

[Files]
Source: "..\..\dist\windows\POSvirtualServer\*"; DestDir: "{app}\server"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\windows\POSvirtualTray\*"; DestDir: "{app}\tray"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\COPYRIGHT.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\POSvirtual"; Filename: "{app}\tray\POSvirtualTray.exe"; Parameters: "--output ""{localappdata}\Taskblu\POSvirtual\PDF"""; WorkingDir: "{app}\tray"
Name: "{userstartup}\POSvirtual"; Filename: "{app}\tray\POSvirtualTray.exe"; Parameters: "--output ""{localappdata}\Taskblu\POSvirtual\PDF"""; WorkingDir: "{app}\tray"; Tasks: autostart

[Run]
Filename: "{app}\tray\POSvirtualTray.exe"; Parameters: "--output ""{localappdata}\Taskblu\POSvirtual\PDF"""; WorkingDir: "{app}\tray"; Description: "Iniciar POSvirtual agora"; Flags: postinstall nowait skipifsilent

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
