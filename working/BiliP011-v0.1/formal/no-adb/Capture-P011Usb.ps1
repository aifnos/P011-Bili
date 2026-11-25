param([ValidateRange(1,90)][int]$Seconds=60,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $OutputDirectory){throw 'Output directory already exists'}
[void](New-Item -ItemType Directory -Path $OutputDirectory)
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
public sealed class P011UsbObservation {
 public string Hardware; public string Name; public string Port;
 public bool Early; public bool Started; public uint Problem;
}
public static class P011UsbReadOnlyCapture {
 [StructLayout(LayoutKind.Sequential)] struct D { public uint cbSize; public Guid ClassGuid; public uint DevInst; public IntPtr Reserved; }
 [DllImport("setupapi.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr SetupDiGetClassDevsW(ref Guid g,string e,IntPtr p,uint f);
 [DllImport("setupapi.dll",SetLastError=true)] static extern bool SetupDiEnumDeviceInfo(IntPtr s,uint n,ref D d);
 [DllImport("setupapi.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool SetupDiGetDeviceInstanceIdW(IntPtr s,ref D d,StringBuilder b,uint size,out uint need);
 [DllImport("setupapi.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool SetupDiGetDeviceRegistryPropertyW(IntPtr s,ref D d,uint property,out uint reg,byte[] b,uint size,out uint need);
 [DllImport("setupapi.dll")] static extern bool SetupDiDestroyDeviceInfoList(IntPtr s);
 [DllImport("cfgmgr32.dll")] static extern uint CM_Get_DevNode_Status(out uint status,out uint problem,uint dev,uint f);
 public static P011UsbObservation[] Read() {
  var result=new List<P011UsbObservation>(); var g=Guid.Empty;
  IntPtr set=SetupDiGetClassDevsW(ref g,null,IntPtr.Zero,6);
  if(set==new IntPtr(-1)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  try {
   for(uint i=0;;i++) {
    var d=new D(); d.cbSize=(uint)Marshal.SizeOf(typeof(D));
    if(!SetupDiEnumDeviceInfo(set,i,ref d)) { int err=Marshal.GetLastWin32Error(); if(err==259)break; throw new System.ComponentModel.Win32Exception(err); }
    var id=new StringBuilder(1024); uint need;
    if(!SetupDiGetDeviceInstanceIdW(set,ref d,id,1024,out need)) continue;
    var match=Regex.Match(id.ToString(),@"^USB\\(VID_1782&PID_(?:4D00|4064)(?:&MI_[0-9A-F]{2})?)(?:&|\\)",RegexOptions.IgnoreCase);
    if(!match.Success)continue;
    var b=new byte[4096]; uint reg; string name="";
    if(SetupDiGetDeviceRegistryPropertyW(set,ref d,12,out reg,b,(uint)b.Length,out need))name=Encoding.Unicode.GetString(b,0,(int)Math.Min(need,(uint)b.Length)).TrimEnd('\0');
    var port=Regex.Match(name,@"\((COM\d+)\)",RegexOptions.IgnoreCase);
    uint status,problem; if(CM_Get_DevNode_Status(out status,out problem,d.DevInst,0)!=0)problem=0xffffffff;
    result.Add(new P011UsbObservation{Hardware=match.Groups[1].Value.ToUpperInvariant(),Name=name,Port=port.Success?port.Groups[1].Value:"",Early=match.Groups[1].Value.IndexOf("PID_4D00",StringComparison.OrdinalIgnoreCase)>=0,Problem=problem,Started=(status&8)!=0});
   }
  }finally{SetupDiDestroyDeviceInfoList(set);}
  return result.ToArray();
 }
}
'@
$eventsPath=Join-Path $OutputDirectory 'usb-events.jsonl'
$clock=[Diagnostics.Stopwatch]::StartNew()
$last=$null
$early=$false
$runtime=$false
$removed=$false
$changes=0
$status='OBSERVING'
$summary=$null
Write-Output 'USB_CAPTURE_ARMED: no serial handle, no USB protocol transmission, no ADB.'
try{
 while($clock.Elapsed.TotalSeconds -lt $Seconds){
  $rows=@([P011UsbReadOnlyCapture]::Read() | Sort-Object Hardware,Port)
  $serialized=ConvertTo-Json -InputObject $rows -Compress -Depth 4
  if($serialized -cne $last){
   $row=[ordered]@{host_time=(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss.fffK');elapsed_ms=$clock.ElapsedMilliseconds;devices=$rows}
   $line=ConvertTo-Json -InputObject $row -Compress -Depth 5
   Add-Content -LiteralPath $eventsPath -Value $line -Encoding utf8
   Write-Output $line
   $last=$serialized;$changes++
  }
  if(@($rows|Where-Object Early).Count -gt 0){$early=$true}
  if(@($rows|Where-Object {-not $_.Early}).Count -gt 0){$runtime=$true}
  if($rows.Count -eq 0){$removed=$true}
  Start-Sleep -Milliseconds 50
 }
 $status=if($early){'EARLY_USB_OBSERVED_NO_HANDSHAKE'}elseif($runtime){'RUNTIME_ONLY_NO_DOWNLOAD_INTERFACE'}else{'NO_TARGET_USB_OBSERVED'}
}catch{
 $status='HOST_OBSERVATION_ERROR'
 Write-Error $_ -ErrorAction Continue
 throw
}finally{
 $summary=[ordered]@{status=$status;host_only_observation=$true;adb_invoked=$false;serial_opened=$false;protocol_tx_bytes=0;device_write_performed=$false;early_interface_seen=$early;runtime_interface_seen=$runtime;removal_seen=$removed;changes=$changes;elapsed_ms=$clock.ElapsedMilliseconds;physical_state_verified=$false}
 $summary|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $OutputDirectory 'result.json') -Encoding utf8
 Write-Output ('RESULT='+($summary|ConvertTo-Json -Compress))
}
