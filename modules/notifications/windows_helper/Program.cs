using System;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ScriptsNotificationsToastHelper;

/// <summary>
/// Lightweight non-elevated user-session desktop notification helper.
/// Listens on loopback HTTP (127.0.0.1:1238) with Bearer token authentication.
/// </summary>
public static class Program
{
    private static int _port = 1238;
    private static string _token = "";
    private static readonly DateTime StartTime = DateTime.UtcNow;

    public static async Task<int> Main(string[] args)
    {
        // Parse port override if provided
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--port" && i + 1 < args.Length && int.TryParse(args[i + 1], out int p))
            {
                _port = p;
            }
        }

        string tokenPath = Environment.GetEnvironmentVariable("NOTIFICATIONS_TOKEN_FILE") ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "scripts_notifications", "token");

        if (File.Exists(tokenPath))
        {
            _token = (await File.ReadAllTextAsync(tokenPath)).Trim();
        }
        else
        {
            Directory.CreateDirectory(Path.GetDirectoryName(tokenPath)!);
            byte[] bytes = new byte[32];
            RandomNumberGenerator.Fill(bytes);
            _token = Convert.ToHexString(bytes).ToLowerInvariant();
            await File.WriteAllTextAsync(tokenPath, _token, Encoding.UTF8);
        }

        using var listener = new HttpListener();
        string prefix = $"http://127.0.0.1:{_port}/";
        listener.Prefixes.Add(prefix);
        listener.Start();
        Console.WriteLine($"Scripts Notifications Helper listening on {prefix}");

        using var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            cts.Cancel();
            listener.Stop();
        };

        while (!cts.IsCancellationRequested)
        {
            try
            {
                var context = await listener.GetContextAsync();
                _ = Task.Run(() => HandleRequest(context));
            }
            catch when (cts.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"Listener error: {ex.Message}");
            }
        }

        return 0;
    }

    private static async Task HandleRequest(HttpListenerContext context)
    {
        var req = context.Request;
        var res = context.Response;

        // Verify Bearer Token
        string? auth = req.Headers["Authorization"];
        if (string.IsNullOrEmpty(auth) || auth != $"Bearer {_token}")
        {
            await SendJson(res, 401, new { ok = false, error = "unauthorized" });
            return;
        }

        string path = req.Url?.AbsolutePath.ToLowerInvariant() ?? "";
        string method = req.HttpMethod.ToUpperInvariant();

        if (path is "/health" or "/status" && method == "GET")
        {
            await SendJson(res, 200, new
            {
                ok = true,
                status = "healthy",
                user = Environment.UserName,
                uptime_seconds = Math.Round((DateTime.UtcNow - StartTime).TotalSeconds, 1),
                version = "1.0.0"
            });
            return;
        }

        if (path is "/notify" or "/toast" && method == "POST")
        {
            using var reader = new StreamReader(req.InputStream, Encoding.UTF8);
            string body = await reader.ReadToEndAsync();
            try
            {
                using var doc = JsonDocument.Parse(body);
                var root = doc.RootElement;
                string title = root.GetProperty("title").GetString() ?? "";
                string msgBody = root.GetProperty("body").GetString() ?? "";
                string severity = root.TryGetProperty("severity", out var s) ? s.GetString() ?? "info" : "info";

                // Windows App SDK or WinRT Toast Notification would be dispatched here
                string toastId = "toast-" + Guid.NewGuid().ToString("N")[..12];
                await SendJson(res, 200, new
                {
                    ok = true,
                    status = "display_requested",
                    toast_id = toastId
                });
            }
            catch
            {
                await SendJson(res, 400, new { ok = false, error = "bad_payload" });
            }
            return;
        }

        await SendJson(res, 404, new { ok = false, error = "not_found" });
    }

    private static async Task SendJson(HttpListenerResponse res, int status, object data)
    {
        res.StatusCode = status;
        res.ContentType = "application/json; charset=utf-8";
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(data);
        res.ContentLength64 = bytes.Length;
        await res.OutputStream.WriteAsync(bytes);
        res.OutputStream.Close();
    }
}
