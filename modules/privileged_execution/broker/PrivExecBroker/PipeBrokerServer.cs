using System;
using System.Buffers.Binary;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace PrivExecBroker;

public sealed class PipeBrokerServer
{
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
        while (!cancellationToken.IsCancellationRequested)
        {
            PipeOptions options = PipeOptions.Asynchronous | PipeOptions.WriteThrough;
            if (firstInstance)
            {
                options |= PipeOptions.FirstPipeInstance;
            }

            using var server = NamedPipeServerStreamAcl.Create(
                _pipeName,
                PipeDirection.InOut,
                1,
                PipeTransmissionMode.Byte,
                options,
                65536,
                65536,
                _pipeSecurity);

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
                break;
            }

            try
            {
                await HandleConnectionAsync(server, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (IOException)
            {
                // Client disconnected mid-request; continue serving next request.
            }
        }
    }

    private async Task HandleConnectionAsync(NamedPipeServerStream server, CancellationToken cancellationToken)
    {
        byte[] lenBuf = await ReadExactAsync(server, 4, cancellationToken);
        uint frameLen = BinaryPrimitives.ReadUInt32LittleEndian(lenBuf);
        if (frameLen == 0 || frameLen > ProtocolConstants.MaxFrameBytes)
        {
            throw new IOException($"Invalid request frame length: {frameLen}.");
        }

        byte[] bodyBuf = await ReadExactAsync(server, (int)frameLen, cancellationToken);
        string requestJson = Encoding.UTF8.GetString(bodyBuf);

        // Capture authenticated Windows identity server-side after reading client bytes.
        ClientIdentity? clientIdentity = null;
        server.RunAsClient(() =>
        {
            clientIdentity = SecurityAndAcl.GetCurrentWindowsIdentity();
        });

        if (clientIdentity is null)
        {
            throw new InvalidOperationException("Failed to derive Windows client identity from pipe.");
        }

        string responseJson = await _engine.HandleRawRequestAsync(requestJson, clientIdentity, cancellationToken);
        byte[] responseBytes = Encoding.UTF8.GetBytes(responseJson);
        if (responseBytes.Length > ProtocolConstants.MaxFrameBytes)
        {
            throw new InvalidOperationException("Response frame exceeds maximum allowed size.");
        }

        byte[] outLen = new byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(outLen, (uint)responseBytes.Length);
        await server.WriteAsync(outLen, CancellationToken.None);
        await server.WriteAsync(responseBytes, CancellationToken.None);
        await server.FlushAsync(CancellationToken.None);
        server.WaitForPipeDrain();
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
