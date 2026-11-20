using System;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PrivExecBroker;

public static class OutputSanitizer
{
    public const int MaxStdoutChars = 262144; // 256 KiB text cap
    public const int MaxStderrChars = 65536;  // 64 KiB text cap

    private static readonly Regex[] SecretPatterns =
    {
        new(@"(?i)(password|passwd|pwd|secret|api[_-]?key|token|credential)\s*([:=])\s*([^\s,;""']+)", RegexOptions.Compiled),
        new(@"(?i)(""password""|""secret""|""token""|""credential"")\s*:\s*""([^""]*)""", RegexOptions.Compiled),
        new(@"(?i)(Authorization\s*:\s*Bearer\s+)(\S+)", RegexOptions.Compiled),
        new(@"(?i)(ConvertTo-SecureString\s+)([^\s;]+)", RegexOptions.Compiled),
        new(@"(?i)(PRIVEXEC_SECRET:)(\S+)", RegexOptions.Compiled)
    };

    public static string SanitizeText(string? input, int maxChars)
    {
        if (string.IsNullOrEmpty(input))
        {
            return string.Empty;
        }

        string text = input.Length > maxChars
            ? input[..maxChars] + "\n...[TRUNCATED]"
            : input;

        text = SecretPatterns[0].Replace(text, "$1$2[REDACTED]");
        text = SecretPatterns[1].Replace(text, "$1:\"[REDACTED]\"");
        text = SecretPatterns[2].Replace(text, "$1[REDACTED]");
        text = SecretPatterns[3].Replace(text, "$1[REDACTED]");
        text = SecretPatterns[4].Replace(text, "$1[REDACTED]");
        return text;
    }

    public static JsonElement SanitizeJsonElement(JsonElement element)
    {
        string raw = element.GetRawText();
        string sanitized = SanitizeText(raw, MaxStdoutChars);
        try
        {
            using JsonDocument doc = JsonDocument.Parse(sanitized);
            return doc.RootElement.Clone();
        }
        catch (JsonException)
        {
            return JsonSerializer.SerializeToElement(new { sanitized_preview = sanitized });
        }
    }

    public static JsonElement ParseStructuredOutput(string sanitizedStdout, string sanitizedStderr, int exitCode)
    {
        string trimmed = sanitizedStdout.Trim();
        if (!string.IsNullOrEmpty(trimmed))
        {
            if (TryParseJsonObject(trimmed, out JsonElement fullObj))
            {
                return fullObj;
            }

            // Fallback: check last non-empty line for a JSON object emitted after human log lines.
            string[] lines = trimmed.Split(new[] { "\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries);
            for (int i = lines.Length - 1; i >= 0; i--)
            {
                string candidate = lines[i].Trim();
                if (candidate.StartsWith('{') && candidate.EndsWith('}') &&
                    TryParseJsonObject(candidate, out JsonElement lineObj))
                {
                    return lineObj;
                }
            }
        }

        return JsonSerializer.SerializeToElement(new
        {
            exit_code = exitCode,
            stdout = sanitizedStdout,
            stderr = sanitizedStderr
        });
    }

    private static bool TryParseJsonObject(string text, out JsonElement element)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(text);
            if (doc.RootElement.ValueKind == JsonValueKind.Object)
            {
                element = SanitizeJsonElement(doc.RootElement);
                return true;
            }
        }
        catch (JsonException)
        {
        }
        element = default;
        return false;
    }
}
