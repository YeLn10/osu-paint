using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using osu.Framework;
using osu.Framework.Allocation;
using osu.Framework.Audio.Track;
using osu.Framework.Bindables;
using osu.Framework.Graphics;
using osu.Framework.Graphics.Sprites;
using osu.Framework.Platform;
using osu.Framework.Timing;
using osu.Game.Beatmaps;
using osu.Game.Configuration;
using osu.Game.Rulesets.Mania.Objects;
using osu.Game.Rulesets.Objects.Drawables;
using osu.Game.Rulesets.PixelFilm;
using osu.Game.Rulesets.UI;
using osu.Game.Skinning;

internal sealed class RenderingProbe : Game
{
    private readonly ManualClock clock = new ManualClock();
    private Drawable playfield = null!;
    private DrawableHitObject<ManiaHitObject> marker = null!;
    private int step;
    public bool Passed { get; private set; }
    private readonly byte[] bytes;
    private readonly string source;
    private readonly FixtureWorkingBeatmap working;

    public RenderingProbe()
    {
        const string json = "{\"format\":\"osu-paint-film-v1\",\"width\":2,\"height\":1,\"end_ms\":2200,\"frames\":[{\"start_ms\":2000,\"end_ms\":2100,\"rows\":[\"#.\"]},{\"start_ms\":2100,\"end_ms\":2200,\"rows\":[\".#\"]}]}";
        bytes = Encoding.UTF8.GetBytes(json);
        source = "osu-paint-film-v1 2200 2 " + Convert.ToHexString(SHA256.HashData(bytes));
        working = new FixtureWorkingBeatmap(bytes);
    }

    protected override IReadOnlyDependencyContainer CreateChildDependencies(IReadOnlyDependencyContainer parent)
    {
        var dependencies = new DependencyContainer(base.CreateChildDependencies(parent));
        dependencies.CacheAs(new Bindable<WorkingBeatmap>(working));
        dependencies.CacheAs<IGameplaySettings>(new FixtureGameplaySettings());
        dependencies.CacheAs<ISkinSource>(new FixtureSkinSource());
        return dependencies;
    }

    [BackgroundDependencyLoader]
    private void load()
    {
        Type type = typeof(PixelFilmRuleset).Assembly.GetType("osu.Game.Rulesets.PixelFilm.FilmPlayfield")!;
        playfield = (Drawable)Activator.CreateInstance(type, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, new object[] { source }, null)!;
        playfield.Clock = new FramedClock(clock);
        Add(playfield);
        var original = new Beatmap();
        original.Metadata.Source = source;
        original.Difficulty.CircleSize = 2;
        var ruleset = new PixelFilmRuleset();
        var converted = (osu.Game.Rulesets.Mania.Beatmaps.ManiaBeatmap)ruleset.CreateBeatmapConverter(original).Convert();
        converted.HitObjects[0].ApplyDefaults(converted.ControlPointInfo, converted.Difficulty);
        using var drawable = (DrawableRuleset<ManiaHitObject>)ruleset.CreateDrawableRulesetWith(converted);
        marker = drawable.CreateDrawableRepresentation(converted.HitObjects[0]);
        marker.Clock = new FramedClock(clock);
        Add(marker);
    }

    protected override void UpdateAfterChildren()
    {
        base.UpdateAfterChildren();
        if (Passed) return;
        if (step == 0) { clock.CurrentTime = 2000; step++; return; }
        var field = playfield.GetType().GetField("picture", BindingFlags.NonPublic | BindingFlags.Instance)!;
        var sprite = (Sprite)field.GetValue(playfield)!;
        var textures = (osu.Framework.Graphics.Textures.Texture[])playfield.GetType()
            .GetField("textures", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(playfield)!;
        bool correct = step == 1 ? sprite.Texture == textures[0] : step == 2 ? sprite.Texture == textures[1] : sprite.Texture == null;
        if (!correct) throw new Exception("Real framework sprite selected a mixed or wrong frame.");
        if (marker.Judged != (step == 3) || marker.Alpha != 0 || marker.DisplayResult)
            throw new Exception("Completion must stay invisible and judge automatically at the film end.");
        bool atlas = (bool)typeof(osu.Framework.Graphics.Textures.Texture).GetProperty("IsAtlasTexture",
            BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(textures[0])!;
        if (atlas || textures[0].Width != 2 || sprite.RelativeSizeAxes != Axes.Both)
            throw new Exception("Film texture must be full size and outside the atlas.");
        if (step == 1) { clock.CurrentTime = 2100; step++; }
        else if (step == 2) { clock.CurrentTime = 2200; step++; }
        else {
            Passed = true;
            Console.WriteLine("PASS: actual dependency loading, framework sprite switch, automatic invisible completion.");
            Host.Exit();
        }
    }
}

internal sealed class FixtureWorkingBeatmap : WorkingBeatmap
{
    private readonly byte[] data;
    private readonly IBeatmap? rawBeatmap;
    public FixtureWorkingBeatmap(byte[] data, IBeatmap? beatmap = null) : base(beatmap?.BeatmapInfo ?? new BeatmapInfo(), null!) {
        this.data = data; rawBeatmap = beatmap;
    }
    public override Stream GetStream(string path) => path == "pixel-film.json" ? new MemoryStream(data) : throw new NotSupportedException(path);
    protected override IBeatmap GetBeatmap() => rawBeatmap ?? throw new NotSupportedException();
    public override osu.Framework.Graphics.Textures.Texture GetBackground() => throw new NotSupportedException();
    protected override Track GetBeatmapTrack() => throw new NotSupportedException();
    protected override ISkin GetSkin() => throw new NotSupportedException();
}

internal sealed class FixtureGameplaySettings : IGameplaySettings
{
    public IBindable<float> ComboColourNormalisationAmount { get; } = new BindableFloat(1);
    public IBindable<float> PositionalHitsoundsLevel { get; } = new BindableFloat(1);
}

internal sealed class FixtureSkinSource : SkinProvidingContainer { }

internal sealed class ProbeHost : HeadlessGameHost
{
    public ProbeHost() : base("pixel-film-probe", new HostOptions(), false) { }
    public override IEnumerable<string> UserStoragePaths => new[] {
        Path.Combine(Path.GetDirectoryName(typeof(RenderingProbe).Assembly.Location)!, "headless-data") };
}
