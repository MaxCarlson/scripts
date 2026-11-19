using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;

namespace PrivExecBroker;

public sealed record ClientIdentity(string Sid, string AccountName, string AuthenticationType);

public static class SecurityAndAcl
{
    public static ClientIdentity GetCurrentWindowsIdentity()
    {
        using var identity = WindowsIdentity.GetCurrent(TokenAccessLevels.Query);
        string sid = identity.User?.Value ?? throw new InvalidOperationException("Unable to determine Windows client SID.");
        return new ClientIdentity(sid, identity.Name, identity.AuthenticationType ?? string.Empty);
    }

    public static string GetCurrentProcessUserSid()
    {
        using var identity = WindowsIdentity.GetCurrent(TokenAccessLevels.Query);
        return identity.User?.Value ?? throw new InvalidOperationException("Unable to determine broker operator SID.");
    }

    public static PipeSecurity BuildPipeSecurity(string operatorSid, IEnumerable<string> allowedClientSids)
    {
        var security = new PipeSecurity();

        // Explicitly deny network and anonymous access on the local named pipe.
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.NetworkSid, null),
            PipeAccessRights.FullControl,
            AccessControlType.Deny));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.AnonymousSid, null),
            PipeAccessRights.FullControl,
            AccessControlType.Deny));

        // Administrative / operator control.
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
            PipeAccessRights.FullControl,
            AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null),
            PipeAccessRights.FullControl,
            AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(operatorSid),
            PipeAccessRights.FullControl,
            AccessControlType.Allow));

        // Grant only ReadWrite (no CreateNewInstance / WriteDac / TakeOwnership) to explicit client SIDs.
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { operatorSid };
        foreach (string rawSid in allowedClientSids)
        {
            if (string.IsNullOrWhiteSpace(rawSid) || !seen.Add(rawSid))
            {
                continue;
            }
            var sid = new SecurityIdentifier(rawSid);
            security.AddAccessRule(new PipeAccessRule(
                sid,
                PipeAccessRights.ReadWrite,
                AccessControlType.Allow));
        }

        return security;
    }

    public static void AssertNoReparsePoints(string path, string label)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException($"{label} path cannot be empty.");
        }
        if (!Path.IsPathFullyQualified(path))
        {
            throw new InvalidOperationException($"{label} path must be fully qualified: '{path}'.");
        }

        string full = Path.GetFullPath(path);
        string? root = Path.GetPathRoot(full);
        string? current = full;

        while (!string.IsNullOrWhiteSpace(current) && !string.Equals(current, root, StringComparison.OrdinalIgnoreCase))
        {
            if (File.Exists(current) || Directory.Exists(current))
            {
                FileAttributes attrs = File.GetAttributes(current);
                if ((attrs & FileAttributes.ReparsePoint) != 0)
                {
                    throw new UnauthorizedAccessException(
                        $"{label} traverses or targets a reparse point/symlink/junction at '{current}'.");
                }
            }
            string? parent = Path.GetDirectoryName(current);
            if (string.Equals(parent, current, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            current = parent;
        }
    }

    public static string ComputeFileSha256(string filePath)
    {
        using FileStream stream = File.OpenRead(filePath);
        byte[] hash = SHA256.HashData(stream);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static void AssertFileSha256(string filePath, string expectedSha256, string label)
    {
        if (!File.Exists(filePath))
        {
            throw new FileNotFoundException($"{label} file not found: '{filePath}'.", filePath);
        }
        string actual = ComputeFileSha256(filePath);
        if (!string.Equals(actual, expectedSha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new UnauthorizedAccessException(
                $"{label} SHA-256 mismatch for '{filePath}': expected '{expectedSha256.ToLowerInvariant()}', got '{actual}'.");
        }
    }
}
