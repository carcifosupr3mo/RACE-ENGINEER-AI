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
AppVerName=Race Engineer AI {#AppVer}
AppPublisher=Race Engineer AI
AppPublisherURL=https://github.com/carcifosupr3mo/RACE-ENGINEER-AI
AppSupportURL=https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/issues
AppUpdatesURL=https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/releases
VersionInfoVersion={#AppVer}
VersionInfoProductName=Race Engineer AI
VersionInfoDescription=Race Engineer AI - installazione
; Signing: only when the build has a certificate (scripts/build.py passes /DSIGN and the "resign" tool = scripts/sign_windows.py).
; Inno Setup then signs the installer and the uninstaller it embeds.
#ifdef SIGN
SignTool=resign
SignedUninstaller=yes
#endif
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
; The running app is stopped by PrepareToInstall below (clean shutdown first), not by the Restart Manager: closing its window only
; hides it in the system tray, so the Restart Manager could not close it and the files would stay in use.
CloseApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
[Files]
Source: "..\dist\RaceEngineerAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\windows\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\windows\*.ps1"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display-auto"
Name: "{group}\Verifica LMU reale"; Filename: "{app}\VERIFICA_LMU.bat"
Name: "{group}\Avvia con Driving Display"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--port 8765 --display"
Name: "{autodesktop}\Race Engineer AI"; Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display-auto"
[Run]
Filename: "{app}\RaceEngineerAI.exe"; Parameters: "--display-auto"; Description: "Avvia Race Engineer AI"; Flags: nowait; Check: not WizardSilent
; User data (%LOCALAPPDATA%\RaceEngineerAI) is NOT removed on uninstall: sessions and race memory are the user's data.

[Code]
{ Stop the running copy before files are replaced or removed. First the clean way (the installed exe asks the running copy to
  shut down: recording closed, data flushed; versions before 0.6.4 do not know --quit and just exit), then taskkill as the fallback
  for those older versions or a hung process. Only one copy per user can run, so matching by image name is exact enough. }
procedure StopRunningApp(Dir: String);
var
  Rc: Integer;
begin
  if FileExists(AddBackslash(Dir) + 'RaceEngineerAI.exe') then
    Exec(AddBackslash(Dir) + 'RaceEngineerAI.exe', '--quit', Dir, SW_HIDE, ewWaitUntilTerminated, Rc);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM RaceEngineerAI.exe', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp(ExpandConstant('{app}'));
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp(ExpandConstant('{app}'));
  Result := True;
end;

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
    Exec(AddBackslash(Loc) + 'RaceEngineerAI.exe', '--display-auto', Loc, SW_SHOW, ewNoWait, Rc);
    Result := False;
  end;
end;
