; PupShock Voice - Inno Setup Script
; Creates a Windows installer with automatic update detection
; 
; Dependencies bundled by PyInstaller:
; - customtkinter, sounddevice, numpy, requests, vosk, pystray, Pillow
; - word2number (for voice command parsing)
; - All other required packages as defined in voice_shock_control.spec

#define MyAppName "PupShock Voice"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LunaFennec"
#define MyAppURL "https://github.com/LunaFennec/PupShock-Voice"
#define MyAppExeName "PupShockVoice.exe"
#define MyAppId "{{A7B8C9D0-1E2F-3A4B-5C6D-7E8F9A0B1C2D}"

[Setup]
; Unique AppId - DO NOT CHANGE after first release (enables update detection)
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=PupShockVoice_Setup_v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
; Version info for Windows
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
; Uninstaller
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "launchonstartup"; Description: "Launch at Windows startup"; GroupDescription: "Additional options:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "QUICKSTART.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "myicon.ico"; DestDir: "{app}"; Flags: ignoreversion
; NOTE: Don't include config.json - it should be user-specific
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Quick Start Guide"; Filename: "{app}\QUICKSTART.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: launchonstartup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Delete model cache on uninstall (optional - comment out to preserve)
Type: filesandordirs; Name: "{%USERPROFILE}\AppData\Local\vosk\models"

[Code]
var
  UpgradingFromVersion: String;

function InitializeSetup(): Boolean;
var
  OldVersion: String;
begin
  Result := True;
  UpgradingFromVersion := '';
  
  // Check if previous version is installed
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'DisplayVersion', OldVersion) or
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'DisplayVersion', OldVersion) then
  begin
    UpgradingFromVersion := OldVersion;
    Log('Upgrading from version: ' + OldVersion);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  WelcomeText: String;
begin
  if CurPageID = wpWelcome then
  begin
    if UpgradingFromVersion <> '' then
    begin
      // Upgrading existing installation
      WizardForm.WelcomeLabel2.Caption := 
        'Setup will upgrade {#MyAppName} from version ' + UpgradingFromVersion + ' to version {#MyAppVersion}.' + #13#10 + #13#10 +
        'Your settings and configuration will be preserved.' + #13#10 + #13#10 +
        'It is recommended that you close {#MyAppName} before continuing.' + #13#10 + #13#10 +
        'Click Next to continue, or Cancel to exit Setup.';
    end
    else
    begin
      // Fresh installation
      WizardForm.WelcomeLabel2.Caption := 
        'Setup will install {#MyAppName} version {#MyAppVersion} on your computer.' + #13#10 + #13#10 +
        'Click Next to continue, or Cancel to exit Setup.';
    end;
  end;
  
  if CurPageID = wpFinished then
  begin
    if UpgradingFromVersion <> '' then
    begin
      WizardForm.FinishedLabel.Caption := 
        '{#MyAppName} has been successfully upgraded to version {#MyAppVersion}.' + #13#10 + #13#10 +
        'Your settings have been preserved.' + #13#10 + #13#10 +
        'Click Finish to close Setup.';
    end
    else
    begin
      WizardForm.FinishedLabel.Caption := 
        'Setup has finished installing {#MyAppName} on your computer.' + #13#10 + #13#10 +
        'IMPORTANT NOTES:' + #13#10 +
        '- First run will download AI models (requires internet)' + #13#10 +
        '- Configure API credentials in the API tab before use' + #13#10 +
        '- Always test with low intensity first' + #13#10 + #13#10 +
        'Click Finish to close Setup.';
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  // Skip the "Select Additional Tasks" page if upgrading
  if (PageID = wpSelectTasks) and (UpgradingFromVersion <> '') then
    Result := True;
end;
