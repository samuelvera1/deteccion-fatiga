; Instalador de Fatiga Detector (Inno Setup). Lo compila build.py:
;   ISCC /DAppVersion=1.0.0 installer\fatiga_detector.iss      ->  dist\FatigaDetector-Setup-1.0.0.exe
; Se instala solo para el usuario actual (no pide permisos de administrador). Los datos (sesiones, registro...) quedan
; en Documentos\Fatiga Detector, fuera de la carpeta del programa: no se pierden al actualizar ni desinstalar.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{3F6C1B7E-5E0B-4B65-9C4C-6C1F2A4D9A11}
AppName=Fatiga Detector
AppVersion={#AppVersion}
AppVerName=Fatiga Detector {#AppVersion}
DefaultDirName={autopf}\Fatiga Detector
DefaultGroupName=Fatiga Detector
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FatigaDetector-Setup-{#AppVersion}
SetupIconFile=..\assets\fatiga.ico
UninstallDisplayIcon={app}\FatigaDetector.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un icono en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
; portable.txt haría que el programa guardara sus datos junto al .exe: solo es para la versión portátil (.zip)
Source: "..\dist\FatigaDetector\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs; Excludes: "portable.txt,sesiones,participantes_privado.csv,fatiga_detector.log,cache_revisor,sonidos"

[Icons]
Name: "{autoprograms}\Fatiga Detector"; Filename: "{app}\FatigaDetector.exe"
Name: "{autodesktop}\Fatiga Detector"; Filename: "{app}\FatigaDetector.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FatigaDetector.exe"; Description: "Abrir Fatiga Detector"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usDone then
    SuppressibleMsgBox('Tus sesiones y datos se conservaron en Documentos\Fatiga Detector.', mbInformation, MB_OK, IDOK);
end;
