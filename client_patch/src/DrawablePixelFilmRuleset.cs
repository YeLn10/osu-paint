using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using osu.Framework.Allocation;
using osu.Framework.Bindables;
using osu.Framework.Graphics;
using osu.Framework.Graphics.Rendering;
using osu.Framework.Graphics.Shapes;
using osu.Framework.Graphics.Sprites;
using osu.Framework.Graphics.Textures;
using osu.Framework.Input;
using osu.Game.Beatmaps;
using osu.Game.Rulesets.Mania;
using osu.Game.Rulesets.Mania.Objects;
using osu.Game.Rulesets.Objects.Drawables;
using osu.Game.Rulesets.Scoring;
using osu.Game.Rulesets.UI;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using osuTK.Graphics;

namespace osu.Game.Rulesets.PixelFilm;

internal sealed class DrawablePixelFilmRuleset : DrawableRuleset<ManiaHitObject>
{
    public DrawablePixelFilmRuleset(PixelFilmRuleset ruleset, IBeatmap beatmap) : base(ruleset, beatmap) { }
    protected override Playfield CreatePlayfield() => new FilmPlayfield(Beatmap.Metadata.Source);
    protected override PassThroughInputManager CreateInputManager() => new ManiaInputManager(Ruleset.RulesetInfo, 0);
    public override DrawableHitObject<ManiaHitObject> CreateDrawableRepresentation(ManiaHitObject h) => new EndMarker(h);
    public override double GameplayStartTime => 0;
    public override bool AllowGameplayOverlays => false;

    private sealed class EndMarker : DrawableHitObject<ManiaHitObject>
    {
        public EndMarker(ManiaHitObject h) : base(h) { Alpha = 0; }
        public override bool DisplayResult => false;
        protected override void UpdateInitialTransforms() => Alpha = 0;
        protected override void CheckForResult(bool userTriggered, double timeOffset)
        {
            if (timeOffset >= 0) ApplyResult(HitResult.Perfect);
        }
    }
}

internal sealed class FilmPlayfield : Playfield
{
    private readonly string source;
    private readonly Sprite picture = new Sprite { RelativeSizeAxes = Axes.Both };
    private FilmDocument film = null!;
    private Texture[] textures = Array.Empty<Texture>();
    private int current = -2;

    public FilmPlayfield(string source)
    {
        this.source = source;
        RelativeSizeAxes = Axes.Both;
        AddInternal(new Box { RelativeSizeAxes = Axes.Both, Colour = Color4.White });
        AddInternal(picture);
    }

    [BackgroundDependencyLoader]
    private void load(Bindable<WorkingBeatmap> working, IRenderer renderer)
    {
        using var stream = working.Value.GetStream("pixel-film.json") ?? throw new InvalidDataException("Missing pixel-film.json. Re-export this map.");
        using var bytes = new MemoryStream();
        stream.CopyTo(bytes);
        film = new FilmDocument(bytes.ToArray(), source);
        textures = new Texture[film.Frames.Length];
        var cache = new Dictionary<string, Texture>();
        for (int index = 0; index < textures.Length; index++)
        {
            string pixels = string.Concat(film.Frames[index].Rows);
            if (cache.TryGetValue(pixels, out var reused)) { textures[index] = reused; continue; }
            using var image = new Image<Rgba32>(film.Width, film.Height);
            for (int y = 0; y < film.Height; y++)
                for (int x = 0; x < film.Width; x++)
                    image[x, y] = film.Frames[index].Rows[y][x] == '#' ? new Rgba32(0, 0, 0, 255) : new Rgba32(255, 255, 255, 255);
            textures[index] = renderer.CreateTexture(film.Width, film.Height, false, TextureFilteringMode.Nearest,
                WrapMode.ClampToEdge, WrapMode.ClampToEdge);
            textures[index].SetData(new TextureUpload(image.Clone()));
            cache.Add(pixels, textures[index]);
        }
    }

    protected override void Update()
    {
        base.Update();
        int next = film.FrameAt(Time.Current);
        if (next == current) return;
        // The update thread publishes one complete Sprite draw node; there are no moving cells or fades.
        picture.Texture = next < 0 ? null : textures[next];
        current = next;
    }

    protected override void Dispose(bool isDisposing)
    {
        base.Dispose(isDisposing);
        foreach (var texture in textures.Distinct()) texture?.Dispose();
    }
}
