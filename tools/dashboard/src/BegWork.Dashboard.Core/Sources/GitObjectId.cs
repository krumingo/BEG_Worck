using System.Security.Cryptography;
using System.Text;

namespace BegWork.Dashboard.Core.Sources;

/// <summary>
/// Local recomputation of Git object ids.
///
/// The control state cites its sources by blob SHA. Trusting the blob SHA the API
/// reports back would only prove the API is self-consistent; recomputing it from
/// the bytes we actually rendered proves the bytes on screen are the bytes the
/// producer validated.
/// </summary>
public static class GitObjectId
{
    public static string BlobSha1(ReadOnlySpan<byte> content)
    {
        var header = Encoding.ASCII.GetBytes($"blob {content.Length}\0");
        var buffer = new byte[header.Length + content.Length];
        header.CopyTo(buffer, 0);
        content.CopyTo(buffer.AsSpan(header.Length));
        return Convert.ToHexString(SHA1.HashData(buffer)).ToLowerInvariant();
    }

    public static string Sha256Hex(ReadOnlySpan<byte> content) =>
        Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant();
}
