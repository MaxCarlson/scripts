using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PrivExecBroker;

public interface IOperatorCredentialProvider
{
    bool HasGuestCredential { get; }
    void WriteCredentialJsonToStdin(StreamWriter stdin);
}

public sealed class NullCredentialProvider : IOperatorCredentialProvider
{
    public bool HasGuestCredential => false;
    public void WriteCredentialJsonToStdin(StreamWriter stdin) { }
}

public sealed class ProcessCapabilityExecutor : ICapabilityExecutor
{
    private readonly string _evidenceBaseDir;
    private readonly IOperatorCredentialProvider _credentialProvider;
    private readonly SyntheticCapabilityExecutor _syntheticFallback = new();

    public ProcessCapabilityExecutor(string stateDir, IOperatorCredentialProvider? credentialProvider = null)
    {
        _evidenceBaseDir = Path.Combine(stateDir, "evidence");
        Directory.CreateDirectory(_evidenceBaseDir);
        SecurityAndAcl.AssertNoReparsePoints(_evidenceBaseDir, "Evidence base directory");
        _credentialProvider = credentialProvider ?? new NullCredentialProvider();
    }

    public async Task<ExecutionOutcome> ExecuteAsync(
        CapabilityDescriptor descriptor,
        ValidatedRunRequest request,
        string operationId,
        CancellationToken cancellationToken)
    {
        if (descriptor.RunnerType == "synthetic")
        {
            return await _syntheticFallback.ExecuteAsync(descriptor, request, operationId, cancellationToken);
        }

        if (descriptor.RequiresGuestCredential && !_credentialProvider.HasGuestCredential)
        {
            return FailOutcome("missing_guest_credential",
                $"Capability '{descriptor.CapabilityId}' requires operator-supplied guest credentials in broker memory.");
        }

        try
        {
            VerifyDescriptorExecutionPaths(descriptor);
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or FileNotFoundException or DirectoryNotFoundException or InvalidOperationException)
        {
            return FailOutcome("integrity_check_failed", ex.Message);
        }

        string exePath = descriptor.ExecutablePath!;
        string workDir = string.IsNullOrWhiteSpace(descriptor.WorkingDirectory)
            ? Path.GetDirectoryName(descriptor.ScriptPath!)!
            : descriptor.WorkingDirectory!;

        var psi = new ProcessStartInfo
        {
            FileName = exePath,
            WorkingDirectory = workDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = descriptor.RequiresGuestCredential,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };

        // Prevent user site-packages or bytecode pollution in child Python processes.
        psi.Environment["PYTHONNOUSERSITE"] = "1";
        psi.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        psi.Environment["PRIVEXEC_OPERATION_ID"] = operationId;
        psi.Environment["PRIVEXEC_MODE"] = request.Mode;

        BuildTypedArgumentList(psi.ArgumentList, descriptor, request, operationId);

        using var process = new Process { StartInfo = psi };
        try
        {
            if (!process.Start())
            {
                return FailOutcome("process_start_failed", $"Failed to start '{exePath}'.");
            }
        }
        catch (Exception ex)
        {
            return FailOutcome("process_start_failed", $"Failed to launch '{exePath}': {ex.Message}");
        }

        if (descriptor.RequiresGuestCredential)
        {
            try
            {
                _credentialProvider.WriteCredentialJsonToStdin(process.StandardInput);
                process.StandardInput.Close();
            }
            catch (Exception ex)
            {
                TryKillTree(process);
                return FailOutcome("credential_handoff_failed", $"Failed to pass guest credential to child process: {ex.Message}");
            }
        }

        Task<string> stdoutTask = ReadBoundedAsync(process.StandardOutput, OutputSanitizer.MaxStdoutChars);
        Task<string> stderrTask = ReadBoundedAsync(process.StandardError, OutputSanitizer.MaxStderrChars);

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(TimeSpan.FromSeconds(descriptor.MaxDurationSeconds));

        bool timedOut = false;
        try
        {
            await process.WaitForExitAsync(timeoutCts.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            timedOut = true;
            TryKillTree(process);
        }
        catch (OperationCanceledException)
        {
            TryKillTree(process);
            throw;
        }

        string rawOut = await SafeAwaitTextAsync(stdoutTask);
        string rawErr = await SafeAwaitTextAsync(stderrTask);
        string sanitizedOut = OutputSanitizer.SanitizeText(rawOut, OutputSanitizer.MaxStdoutChars);
        string sanitizedErr = OutputSanitizer.SanitizeText(rawErr, OutputSanitizer.MaxStderrChars);

        if (timedOut)
        {
            var timeoutResult = JsonSerializer.SerializeToElement(new
            {
                timed_out = true,
                timeout_seconds = descriptor.MaxDurationSeconds,
                stdout = sanitizedOut,
                stderr = sanitizedErr
            });
            return new ExecutionOutcome(
                OperationState.Failed,
                124,
                "execution_timeout",
                timeoutResult,
                WriteSanitizedEvidence(operationId, timeoutResult, sanitizedOut, sanitizedErr),
                false,
                $"Execution exceeded max_duration_seconds ({descriptor.MaxDurationSeconds}s) and was terminated.");
        }

        int exitCode = process.ExitCode;
        JsonElement parsedResult = OutputSanitizer.ParseStructuredOutput(sanitizedOut, sanitizedErr, exitCode);
        List<string> evidence = WriteSanitizedEvidence(operationId, parsedResult, sanitizedOut, sanitizedErr);

        if (exitCode == 0)
        {
            return new ExecutionOutcome(
                OperationState.Succeeded,
                0,
                null,
                parsedResult,
                evidence,
                true,
                null);
        }

        string errMsg = !string.IsNullOrWhiteSpace(sanitizedErr)
            ? sanitizedErr
            : $"Trusted execution exited with code {exitCode}.";
        return new ExecutionOutcome(
            OperationState.Failed,
            exitCode,
            "child_process_failed",
            parsedResult,
            evidence,
            false,
            errMsg);
    }

    private static void VerifyDescriptorExecutionPaths(CapabilityDescriptor descriptor)
    {
        SecurityAndAcl.AssertNoReparsePoints(descriptor.ExecutablePath!, "Executable path");
        if (!File.Exists(descriptor.ExecutablePath!))
        {
            throw new FileNotFoundException($"Executable not found: '{descriptor.ExecutablePath}'.");
        }
        if (!string.IsNullOrWhiteSpace(descriptor.ExecutableSha256))
        {
            SecurityAndAcl.AssertFileSha256(descriptor.ExecutablePath!, descriptor.ExecutableSha256!, "Executable");
        }

        SecurityAndAcl.AssertNoReparsePoints(descriptor.ScriptPath!, "Script path");
        SecurityAndAcl.AssertFileSha256(descriptor.ScriptPath!, descriptor.ScriptSha256!, "Trusted script");

        if (!string.IsNullOrWhiteSpace(descriptor.WorkingDirectory))
        {
            SecurityAndAcl.AssertNoReparsePoints(descriptor.WorkingDirectory!, "Working directory");
            if (!Directory.Exists(descriptor.WorkingDirectory!))
            {
                throw new DirectoryNotFoundException($"Working directory not found: '{descriptor.WorkingDirectory}'.");
            }
        }
    }

    private static void BuildTypedArgumentList(
        IList<string> argList,
        CapabilityDescriptor descriptor,
        ValidatedRunRequest request,
        string operationId)
    {
        foreach (string fixedArg in descriptor.FixedArgs)
        {
            string expanded = fixedArg
                .Replace("{script_path}", descriptor.ScriptPath!, StringComparison.Ordinal)
                .Replace("{operation_id}", operationId, StringComparison.Ordinal)
                .Replace("{target_id}", request.Target.Id, StringComparison.Ordinal);
            argList.Add(expanded);
        }

        List<string> modeArgs = request.Mode == "apply" ? descriptor.ApplyArgs : descriptor.DryRunArgs;
        foreach (string ma in modeArgs)
        {
            argList.Add(ma);
        }

        var orderedNames = new List<string>(request.Parameters.Keys);
        orderedNames.Sort(StringComparer.Ordinal);
        foreach (string name in orderedNames)
        {
            object? rawVal = request.Parameters[name];
            if (rawVal is null || !descriptor.ParameterSchema.TryGetValue(name, out ParameterRule? rule))
            {
                continue;
            }
            if (string.IsNullOrWhiteSpace(rule.CliFlag))
            {
                continue;
            }
            if (rule.Type == "bool")
            {
                if (rawVal is true)
                {
                    argList.Add(rule.CliFlag);
                }
                continue;
            }
            argList.Add(rule.CliFlag);
            argList.Add(Convert.ToString(rawVal, CultureInfo.InvariantCulture) ?? string.Empty);
        }
    }

    private List<string> WriteSanitizedEvidence(
        string operationId,
        JsonElement parsedResult,
        string sanitizedOut,
        string sanitizedErr)
    {
        string opDir = Path.Combine(_evidenceBaseDir, operationId);
        Directory.CreateDirectory(opDir);
        SecurityAndAcl.AssertNoReparsePoints(opDir, "Operation evidence directory");

        string resultFile = Path.Combine(opDir, "sanitized-result.json");
        var payload = new
        {
            operation_id = operationId,
            result = parsedResult,
            stdout = sanitizedOut,
            stderr = sanitizedErr
        };
        File.WriteAllText(resultFile, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
        return new List<string> { resultFile };
    }

    private static async Task<string> ReadBoundedAsync(StreamReader reader, int maxChars)
    {
        var sb = new StringBuilder();
        char[] buf = new char[4096];
        bool truncated = false;
        while (true)
        {
            int n = await reader.ReadAsync(buf, 0, buf.Length);
            if (n <= 0) break;
            if (!truncated)
            {
                int remaining = maxChars - sb.Length;
                if (n <= remaining)
                {
                    sb.Append(buf, 0, n);
                }
                else
                {
                    if (remaining > 0) sb.Append(buf, 0, remaining);
                    truncated = true;
                }
            }
        }
        if (truncated)
        {
            sb.Append("\n...[TRUNCATED]");
        }
        return sb.ToString();
    }

    private static async Task<string> SafeAwaitTextAsync(Task<string> task)
    {
        try
        {
            return await task;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static void TryKillTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
    }

    private static ExecutionOutcome FailOutcome(string category, string message)
    {
        return new ExecutionOutcome(
            OperationState.Failed,
            1,
            category,
            JsonSerializer.SerializeToElement(new { error = message }),
            new List<string>(),
            false,
            message);
    }
}
