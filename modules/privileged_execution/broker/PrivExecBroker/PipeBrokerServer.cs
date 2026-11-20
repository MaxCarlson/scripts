using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Security;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PrivExecBroker;

public sealed class PipeBrokerServer
{
    private const int MaxServerInstances = 8;
    private readonly string _pipeName;
    private readonly PipeSecurity _pipeSecurity;
    private readonly BrokerEngine _engine;

    public PipeBrokerServer(string pipeName, PipeSecurity pipeSecurity, BrokerEngine engine)
    {
        _pipeName = pipeName;
        _pipeSecurity = pipeSecurity;
        _engine = engine;
    }

    public async Task RunAsync(CancellationToken cancellationToken, Action? onListening = null)
    {
        bool firstInstance = true;
        var activeHandlers = new List<Task>();
        using var concurrencySlots = new SemaphoreSlim(MaxServerInstances, MaxServerInstances);

        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await concurrencySlots.WaitAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }

            PipeOptions options = PipeOptions.Asynchronous | PipeOptions.WriteThrough;
            if (firstInstance)
            {
                options |= PipeOptions.FirstPipeInstance;
            }

            NamedPipeServerStream? server = null;
            try
            {
                server = NamedPipeServerStreamAcl.Create(
                    _pipeName,
                    PipeDirection.InOut,
                    MaxServerInstances,
                    PipeTransmissionMode.Byte,
                    options,
                    65536,
                    65536,
                    _pipeSecurity);
            }
            catch
            {
                concurrencySlots.Release();
                throw;
            }

            if (firstInstance)
            {
                firstInstance = false;
                onListening?.Invoke();
            }

            try
            {
                await server.WaitForConnectionAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                server.Dispose();
                concurrencySlots.Release();
                break;
            }
            catch (Exception ex)
            {
                LogServerError("accept", "accept", ex);
                server.Dispose();
                concurrencySlots.Release();
                if (cancellationToken.IsCancellationRequested) break;
                continue;
            }

            NamedPipeServerStream connectedPipe = server;
            string connId = Guid.NewGuid().ToString("N")[..8];
            Task handler = Task.Run(async () =>
            {
                try
                {
                    await HandleConnectionAsync(connectedPipe, connId, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                }
                catch (Exception ex)
                {
                    LogServerError(connId, "unhandled_connection_loop", ex);
                }
                finally
                {
                    connectedPipe.Dispose();
                    concurrencySlots.Release();
                }
            }, CancellationToken.None);

            activeHandlers.RemoveAll(t => t.IsCompleted);
            activeHandlers.Add(handler);
        }

        if (activeHandlers.Count > 0)
        {
            await Task.WhenAll(activeHandlers);
        }
    }

    private async Task HandleConnectionAsync(NamedPipeServerStream server, string connId, CancellationToken cancellationToken)
    {
        string requestJson;
        try
        {
            byte[] lenBuf = await ReadExactAsync(server, 4, cancellationToken);
            uint frameLen = BinaryPrimitives.ReadUInt32LittleEndian(lenBuf);
            if (frameLen == 0 || frameLen > ProtocolConstants.MaxFrameBytes)
            {
                throw new IOException($"Invalid request frame length: {frameLen}.");
            }

            byte[] bodyBuf = await ReadExactAsync(server, (int)frameLen, cancellationToken);
            requestJson = Encoding.UTF8.GetString(bodyBuf);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            LogServerError(connId, "read_frame", ex);
            await TryWriteErrorResponseAsync(server, "malformed_request", $"Failed reading request frame ({ex.GetType().Name}).");
            return;
        }

        // Capture authenticated Windows identity server-side after reading client bytes.
        ClientIdentity? clientIdentity = null;
        try
        {
            server.RunAsClient(() =>
            {
                clientIdentity = SecurityAndAcl.GetCurrentWindowsIdentity();
            });
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or SecurityException or InvalidOperationException)
        {
            SecurityAndAcl.RevertImpersonationIfActive();
            LogServerError(connId, "run_as_client_auth", ex);
            await TryWriteErrorResponseAsync(server, "authentication_failed",
                $"Failed to authenticate Windows named-pipe client ({ex.GetType().Name}). Ensure client connects with TokenImpersonationLevel.Impersonation.");
            return;
        }
        finally
        {
            SecurityAndAcl.RevertImpersonationIfActive();
        }

        if (clientIdentity is null)
        {
            LogServerError(connId, "null_client_identity", new InvalidOperationException("Null client identity."));
            await TryWriteErrorResponseAsync(server, "authentication_failed", "Failed to derive Windows client identity from pipe.");
            return;
        }

        string responseJson;
        try
        {
            responseJson = await SecurityAndAcl.RunAsProcessIdentityAsync(
                () => _engine.HandleRawRequestAsync(requestJson, clientIdentity, cancellationToken));
        }
        catch (OperationCanceledException)
        {
            await TryWriteErrorResponseAsync(server, "broker_shutting_down", "Broker is shutting down.");
            throw;
        }
        catch (Exception ex)
        {
            LogServerError(connId, "engine_dispatch", ex);
            responseJson = BuildErrorJson("broker_internal_error", $"Broker internal error ({ex.GetType().Name}).");
        }

        byte[] responseBytes = Encoding.UTF8.GetBytes(responseJson);
        if (responseBytes.Length > ProtocolConstants.MaxFrameBytes)
        {
            LogServerError(connId, "response_too_large", new InvalidOperationException("Response exceeds MaxFrameBytes."));
            responseBytes = Encoding.UTF8.GetBytes(BuildErrorJson("response_too_large", "Response frame exceeds maximum allowed size."));
        }

        try
        {
            await WriteFrameAsync(server, responseBytes);
        }
        catch (IOException ex)
        {
            LogServerError(connId, "write_response", ex);
        }
    }

    private static async Task WriteFrameAsync(NamedPipeServerStream server, byte[] responseBytes)
    {
        byte[] outLen = new byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(outLen, (uint)responseBytes.Length);
        await server.WriteAsync(outLen, CancellationToken.None);
        await server.WriteAsync(responseBytes, CancellationToken.None);
        await server.FlushAsync(CancellationToken.None);
        server.WaitForPipeDrain();
    }

    private static async Task TryWriteErrorResponseAsync(NamedPipeServerStream server, string category, string message)
    {
        try
        {
            if (!server.IsConnected) return;
            byte[] bytes = Encoding.UTF8.GetBytes(BuildErrorJson(category, message));
            await WriteFrameAsync(server, bytes);
        }
        catch
        {
        }
    }

    private static string BuildErrorJson(string category, string message)
    {
        return JsonSerializer.Serialize(new
        {
            protocol_version = ProtocolConstants.ProtocolVersion,
            ok = false,
            state = "denied",
            authorized = false,
            diagnostic_category = category,
            error = message
        });
    }

    private static void LogServerError(string connId, string phase, Exception ex)
    {
        string sanitized = OutputSanitizer.SanitizeText(ex.Message, 512).Replace('\r', ' ').Replace('\n', ' ');
        Console.Error.WriteLine($"[PRIVEXEC_PIPE_ERROR] conn={connId} phase={phase} type={ex.GetType().Name} msg={sanitized}");
        Console.Error.Flush();
    }

    private static async Task<byte[]> ReadExactAsync(Stream stream, int size, CancellationToken cancellationToken)
    {
        byte[] buffer = new byte[size];
        int offset = 0;
        while (offset < size)
        {
            int n = await stream.ReadAsync(buffer.AsMemory(offset, size - offset), cancellationToken);
            if (n == 0)
            {
                throw new IOException("Client closed pipe before completing frame.");
            }
            offset += n;
        }
        return buffer;
    }
}
