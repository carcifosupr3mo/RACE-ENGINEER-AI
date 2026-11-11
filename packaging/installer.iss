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
; zero-click: no directory/group/ready/finish pages; the app starts by itself when the install is done
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableWelcomePage=yes
CloseApplications=yes
ArchitecturesInstallIn64BitMode=x64compatible
[Files]
Source: "..\dist\RaceEngineerAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\windows\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\windows\*.ps1"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display"
Name: "{group}\Verifica LMU reale"; Filename: "{app}\VERIFICA_LMU.bat"
Name: "{group}\Avvia con Driving Display"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--port 8765 --display"
Name: "{autodesktop}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display"
[Run]
Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display"; Description: "Avvia Race Engineer AI"; Flags: nowait; Check: not WizardSilent
; User data (%LOCALAPPDATA%\RaceEngineerAI) is NOT removed on uninstall: sessions and race memory are the user's data.

[Code]
{ Same exe = installer + launcher. Already installed at this version: only check that the files are there, start the app, exit
  (no copy, no reinstall). New or different version: normal install, then the app starts. Silent installs (CI) always install. }
function InitializeSetup(): Boolean;
var
  Ver, Loc: String;
  Rc: Integer;
begin
  Result := True;
  if WizardSilent then Exit;
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E1B7C3A-5D0F-4C1E-9A55-2B8F0A1D7E10}_is1', 'DisplayVersion', Ver)
     and (Ver = '{#AppVer}')
     and RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E1B7C3A-5D0F-4C1E-9A55-2B8F0A1D7E10}_is1', 'InstallLocation', Loc)
     and FileExists(AddBackslash(Loc) + 'RaceEngineerAI.exe') then
  begin
    Exec(AddBackslash(Loc) + 'RaceEngineerAI.exe', '--display', Loc, SW_SHOW, ewNoWait, Rc);
    Result := False;
  end;
end;
