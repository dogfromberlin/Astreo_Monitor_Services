#Requires -Version 5.1
# Astreo Monitor - verifica del certificato del centrale con la sua CA (usato dall'agente e dall'installatore).
if (-not ('AstreoTls' -as [type])) {
  Add-Type -IgnoreWarnings -TypeDefinition @'
using System;
using System.Net;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public static class AstreoTls {
  public static X509Certificate2 Ca;
  public static bool AcceptAny;
  public static bool Validate(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) {
    if (AcceptAny) return true;
    if (errors == SslPolicyErrors.None) return true;
    if ((errors & SslPolicyErrors.RemoteCertificateNameMismatch) != 0 || Ca == null || cert == null) return false;
    X509Chain c = new X509Chain();
    c.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
    c.ChainPolicy.VerificationFlags = X509VerificationFlags.AllowUnknownCertificateAuthority;
    c.ChainPolicy.ExtraStore.Add(Ca);
    if (!c.Build(new X509Certificate2(cert))) return false;
    X509Certificate2 root = c.ChainElements[c.ChainElements.Count - 1].Certificate;
    return root.Thumbprint == Ca.Thumbprint;
  }
  public static void Enable(string caPath) {
    if (!String.IsNullOrEmpty(caPath)) { Ca = new X509Certificate2(caPath); }
    ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
    ServicePointManager.ServerCertificateValidationCallback = Validate;
  }
}
'@
}
