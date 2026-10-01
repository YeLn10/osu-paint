using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;

namespace osu.Game.Rulesets.PixelFilm;

public sealed record FilmFrame(double StartMs, double EndMs, string[] Rows);

public sealed class FilmDocument
{
    public int Width { get; }
    public int Height { get; }
    public double EndMs { get; }
    public FilmFrame[] Frames { get; }

    public FilmDocument(byte[] data, string source)
    {
        if (!FilmDescriptor.TryParse(source, out var descriptor) ||
            !Convert.ToHexString(SHA256.HashData(data)).Equals(descriptor.Hash, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Pixel Film data does not match this beatmap. Re-export and re-import it.");
        using var json = JsonDocument.Parse(data);
        var root = json.RootElement;
        Width = root.GetProperty("width").GetInt32();
        Height = root.GetProperty("height").GetInt32();
        EndMs = root.GetProperty("end_ms").GetDouble();
        Frames = root.GetProperty("frames").EnumerateArray().Select(frame => new FilmFrame(
            frame.GetProperty("start_ms").GetDouble(), frame.GetProperty("end_ms").GetDouble(),
            frame.GetProperty("rows").EnumerateArray().Select(row => row.GetString()!).ToArray())).ToArray();
        if (root.GetProperty("format").GetString() != "osu-paint-film-v1" || Width < 1 || Width > 18 ||
            Width != descriptor.Width || Height < 1 || Height > 128 || Frames.Length < 1 || Frames.Length > 20000 ||
            (long)Width * Height * Frames.Length > 2000000 || !double.IsFinite(EndMs) ||
            Math.Abs(EndMs - descriptor.EndMs) > 1e-7)
            throw new InvalidDataException("Invalid Pixel Film dimensions or duration.");
        double previousEnd = double.NegativeInfinity;
        foreach (var frame in Frames)
        {
            if (!double.IsFinite(frame.StartMs) || !double.IsFinite(frame.EndMs) ||
                frame.StartMs < previousEnd || frame.EndMs <= frame.StartMs || frame.EndMs > EndMs ||
                frame.Rows.Length != Height || frame.Rows.Any(row => row.Length != Width || row.Any(c => c != '#' && c != '.')))
                throw new InvalidDataException("Invalid Pixel Film frame.");
            previousEnd = frame.EndMs;
        }
    }

    public int FrameAt(double time)
    {
        int low = 0, high = Frames.Length;
        while (low < high)
        {
            int middle = (low + high) / 2;
            if (Frames[middle].StartMs <= time) low = middle + 1;
            else high = middle;
        }
        int index = low - 1;
        return index >= 0 && time < Frames[index].EndMs ? index : -1;
    }
}

internal sealed record FilmDescriptor(double EndMs, int Width, string Hash)
{
    public static bool TryParse(string source, out FilmDescriptor descriptor)
    {
        descriptor = null!;
        string[] fields = (source ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (fields.Length != 4 || fields[0] != "osu-paint-film-v1" || fields[3].Length != 64 ||
            fields[3].Any(c => !Uri.IsHexDigit(c)) ||
            !int.TryParse(fields[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out int width) || width < 1 || width > 18 ||
            !double.TryParse(fields[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double end) ||
            !double.IsFinite(end) || end <= 0) return false;
        descriptor = new FilmDescriptor(end, width, fields[3]);
        return true;
    }
}
