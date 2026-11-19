using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security;
using System.Text.Json;

namespace PrivExecBroker;

public sealed class OperatorMemoryCredentialProvider : IOperatorCredentialProvider, IDisposable
{
    private readonly string _username;
    private readonly SecureString _password;
    private bool _disposed;

    public OperatorMemoryCredentialProvider(string username, SecureString password)
    {
        if (string.IsNullOrWhiteSpace(username))
        {
            throw new ArgumentException("Guest credential username cannot be empty.", nameof(username));
        }
        _username = username;
        _password = password.Copy();
        _password.MakeReadOnly();
    }

    public bool HasGuestCredential => !_disposed && _password.Length > 0;

    public static OperatorMemoryCredentialProvider PromptInConsole(string defaultUsername = @"DESKTOP-1ITSJV0\mcarls")
    {
        Console.Write($"Enter guest username [{defaultUsername}]: ");
        string? inputUser = Console.ReadLine();
        string username = string.IsNullOrWhiteSpace(inputUser) ? defaultUsername : inputUser.Trim();

        Console.Write($"Enter guest password for '{username}' (masked): ");
        var secure = new SecureString();
        while (true)
        {
            ConsoleKeyInfo key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter)
            {
                Console.WriteLine();
                break;
            }
            if (key.Key == ConsoleKey.Backspace)
            {
                if (secure.Length > 0)
                {
                    secure.RemoveAt(secure.Length - 1);
                }
                continue;
            }
            if (!char.IsControl(key.KeyChar))
            {
                secure.AppendChar(key.KeyChar);
            }
        }

        if (secure.Length == 0)
        {
            secure.Dispose();
            throw new InvalidOperationException("Guest password cannot be empty.");
        }

        return new OperatorMemoryCredentialProvider(username, secure);
    }

    public void WriteCredentialJsonToStdin(StreamWriter stdin)
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(OperatorMemoryCredentialProvider));
        }

        IntPtr bstr = IntPtr.Zero;
        try
        {
            bstr = Marshal.SecureStringToBSTR(_password);
            string plain = Marshal.PtrToStringBSTR(bstr);
            string jsonLine = JsonSerializer.Serialize(new { username = _username, password = plain });
            stdin.WriteLine(jsonLine);
            stdin.Flush();
        }
        finally
        {
            if (bstr != IntPtr.Zero)
            {
                Marshal.ZeroFreeBSTR(bstr);
            }
        }
    }

    public void Dispose()
    {
        if (!_disposed)
        {
            _password.Dispose();
            _disposed = true;
        }
    }
}
