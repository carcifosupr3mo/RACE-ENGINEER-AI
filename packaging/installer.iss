; Inno Setup 6 script. Built in CI (windows-latest has Inno Setup preinstalled): iscc packaging\installer.iss
; The installer only copies files into %LOCALAPPDATA%\Programs; it never touches Le Mans Ultimate, its settings or plugins.
#define AppVer GetEnv("RE_VERSION")
#if AppVer == ""
  #define AppVer "0.0.0"
#endif
[Setup]
AppId={{6E1B7C3A-5D0F-4C1E-9A55-2B8F0A1D7E10}
AppName=Race Engineer AI
AppVersion={#AppVer}
DefaultDirName={localappdata}\Programs\RaceEngineerAI
DefaultGroupName=Race Engineer AI
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RaceEngineerAI-Setup-{#AppVer}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\RaceEngineerAI.exe
Compression=lzma2/fast
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
[Files]
Source: "..\dist\RaceEngineerAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\windows\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\windows\*.ps1"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"
Name: "{group}\Verifica LMU reale"; Filename: "{app}\VERIFICA_LMU.bat"
Name: "{group}\Avvia con Driving Display"; Filename: "{app}\AVVIA_CON_DISPLAY.bat"
Name: "{autodesktop}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Icona sul desktop"; Flags: unchecked
[Run]
Filename: "{app}\RaceEngineerAI.exe"; Description: "Avvia Race Engineer AI"; Flags: nowait postinstall skipifsilent
; User data (%LOCALAPPDATA%\RaceEngineerAI) is NOT removed on uninstall: sessions and race memory are the user's data.
