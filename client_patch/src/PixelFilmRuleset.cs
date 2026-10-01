using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading;
using osu.Framework.Bindables;
using osu.Framework.Input.Bindings;
using osu.Game.Beatmaps;
using osu.Game.Rulesets.Mania;
using osu.Game.Rulesets.Mania.Beatmaps;
using osu.Game.Rulesets.Mania.Objects;
using osu.Game.Rulesets.Filter;
using osu.Game.Rulesets.Mods;
using osu.Game.Rulesets.UI;
using osu.Game.Screens.Select;

namespace osu.Game.Rulesets.PixelFilm;

public sealed class PixelFilmRuleset : ManiaRuleset, ILegacyRuleset
{
    public override string Description => "Pixel Film";
    public override string ShortName => "pixel-film";
    public override string PlayingVerb => "Watching pixel frames";
    public override string RulesetAPIVersionSupported => "2026.818.0";
    int ILegacyRuleset.LegacyID => -1;
    public override IEnumerable<int> GameplayVariants => Enumerable.Range(1, 18);
    public override IEnumerable<Mod> GetModsFor(ModType type) => Array.Empty<Mod>();
    public override IEnumerable<KeyBinding> GetDefaultKeyBindings(int variant = 0) => Array.Empty<KeyBinding>();
    public override int GetVariantForBeatmap(IBeatmapInfo beatmapInfo, IReadOnlyList<Mod>? mods = null) =>
        FilmDescriptor.TryParse(beatmapInfo.Metadata.Source, out var film) ? film.Width : 0;
    public override IRulesetFilterCriteria CreateRulesetFilterCriteria() => new FilmFilterCriteria();

    static PixelFilmRuleset()
    {
        using var stream = typeof(PixelFilmRuleset).Assembly.GetManifestResourceStream("PixelFilm.compatibility")!;
        using var manifest = JsonDocument.Parse(stream);
        string directory = Path.GetDirectoryName(typeof(ManiaRuleset).Assembly.Location)!;
        foreach (var entry in manifest.RootElement.GetProperty("assemblies").EnumerateObject())
        {
            using var file = File.OpenRead(Path.Combine(directory, entry.Name));
            if (!Convert.ToHexString(SHA256.HashData(file)).Equals(entry.Value.GetString(), StringComparison.OrdinalIgnoreCase))
                throw new NotSupportedException("Pixel Film requires the supported lazer build. Remove the plugin or rebuild it for this version.");
        }
    }

    public override IBeatmapConverter CreateBeatmapConverter(IBeatmap beatmap) => new FilmBeatmapConverter(beatmap);
    public override DrawableRuleset CreateDrawableRulesetWith(IBeatmap beatmap, IReadOnlyList<Mod>? mods = null) =>
        new DrawablePixelFilmRuleset(this, beatmap);
}

internal sealed class FilmFilterCriteria : IRulesetFilterCriteria
{
    public bool Matches(BeatmapInfo beatmap, FilterCriteria criteria) => FilmDescriptor.TryParse(beatmap.Metadata.Source, out _);
    public bool TryParseCustomKeywordCriteria(string key, osu.Game.Screens.Select.Filter.Operator op, string value) => false;
    public bool FilterMayChangeFromMods(FilterCriteria criteria, ValueChangedEvent<IReadOnlyList<Mod>> change) => false;
}

internal sealed class FilmBeatmapConverter : ManiaBeatmapConverter
{
    public FilmBeatmapConverter(IBeatmap beatmap) : base(beatmap, new ManiaRuleset())
    {
        TargetColumns = FilmDescriptor.TryParse(beatmap.Metadata.Source, out var film) ? film.Width : 0;
        Dual = false;
    }

    public override bool CanConvert() => TargetColumns >= 1 && TargetColumns <= 18 &&
        FilmDescriptor.TryParse(Beatmap.Metadata.Source, out _);

    protected override Beatmap<ManiaHitObject> ConvertBeatmap(IBeatmap original, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // RealmRulesetStore converts an empty probe at startup without checking CanConvert().
        if (original.HitObjects.Count == 0 && string.IsNullOrEmpty(original.Metadata.Source))
            return new ManiaBeatmap(new StageDefinition(1));
        if (!CanConvert()) throw new InvalidDataException("Re-export this map with osu-paint before using Pixel Film.");
        FilmDescriptor.TryParse(original.Metadata.Source, out var film);
        var converted = CreateBeatmap();
        converted.BeatmapInfo = original.BeatmapInfo;
        converted.ControlPointInfo = original.ControlPointInfo;
        converted.AudioLeadIn = original.AudioLeadIn;
        // One silent completion marker; the picture is drawn from the frame payload.
        converted.HitObjects.Add(new Note { StartTime = film.EndMs, Column = 0 });
        return converted;
    }
}
