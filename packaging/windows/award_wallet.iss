; The Windows installer, build\Award-Wallet-Setup.exe, made with Inno Setup 6. build_windows.ps1
; builds the app with PyInstaller first, then runs this with the version from pyproject.toml:
;   ISCC.exe /DAppVersion=0.14.0 packaging\windows\award_wallet.iss
;
; Setup installs the app for you alone, with no administrator prompt, in
; %LOCALAPPDATA%\Programs\Award Wallet, and adds it to the Start menu. It's removed in
; Settings > Apps. Your data is in %LOCALAPPDATA%\Award Wallet: updating or removing the app
; leaves it there.
;
; The app updates itself by downloading the next Setup and running it with /VERYSILENT: Setup
; waits for the app to quit, puts the new version in place and opens it again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Award Wallet"
#define AppExe "Award Wallet.exe"
; The running app holds this (src/award_wallet/windows.py): the two names must stay the same.
#define AppMutex "AwardWallet"

[Setup]
; How Windows knows each version is the same app: never change it.
AppId={{BDD11649-201F-4DE2-A6E2-98694C44617D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisherURL=https://github.com/rafaelcgama/award-wallet
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
; For you alone: no administrator prompt, and {autopf} is %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
; Windows 10 (version 1809) or later, on an Intel or AMD PC, or a newer ARM one that runs its apps.
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\AppIcon.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\..\build
OutputBaseFilename=Award-Wallet-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Each version's files replace the last one's entirely, so nothing from an older version lingers.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\build\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Opens the app when Setup is done: a box to tick at the end of Setup, and always after an update.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[Code]
function AppIsRunning: Boolean;
begin
  Result := CheckForMutexes('{#AppMutex}');
end;

// Asks you to close the app for as long as it's open. False if you click Cancel instead.
function AskToCloseApp(const ToDo: String): Boolean;
begin
  Result := True;
  while AppIsRunning do
    if MsgBox('Award Wallet is open. Close its window to ' + ToDo + ', then click Retry.',
      mbInformation, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup: Boolean;
var
  Waited: Integer;
begin
  if WizardSilent then
  begin
    // An update the app started: the app quits a moment later, so wait for it, up to two minutes.
    Waited := 0;
    while AppIsRunning and (Waited < 240) do
    begin
      Sleep(500);
      Waited := Waited + 1;
    end;
    Result := not AppIsRunning;
    if not Result then
      Log('Award Wallet was still open after two minutes, so it was left as it was.');
  end
  else
    Result := AskToCloseApp('install this version');
end;

function InitializeUninstall: Boolean;
begin
  if UninstallSilent then
    Result := not AppIsRunning
  else
    Result := AskToCloseApp('remove it');
end;
