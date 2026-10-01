using System;
using System.IO;
using System.Linq;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text;
using osu.Game.Beatmaps;
using osu.Game.Rulesets.Mania;
using osu.Game.Rulesets.Mania.Beatmaps;
using osu.Game.Rulesets.Mania.Objects;
using osu.Game.Rulesets.PixelFilm;
using osu.Game.Screens.Select;

class ClientTests
{
    static void Main(string[] args)
    {
        AssemblyLoadContext.Default.Resolving += (_, name) => {
            string path = Path.Combine(args[0], name.Name + ".dll");
            if (!File.Exists(path)) path = Path.Combine(Path.GetDirectoryName(typeof(ClientTests).Assembly.Location)!, name.Name + ".dll");
            return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
        };
        try {
            Check();
            using var host = new ProbeHost();
            var probe = new RenderingProbe();
            host.ExceptionThrown += error => { Console.Error.WriteLine(error); host.Exit(); return true; };
            using var deadline = new System.Threading.Timer(_ => host.Exit(), null, 15000, System.Threading.Timeout.Infinite);
            host.Run(probe);
            Assert(probe.Passed, "Framework rendering probe failed or timed out");
        }
        catch (Exception error) { Console.Error.WriteLine(error); Environment.ExitCode = 1; }
    }

    static void Assert(bool passed, string name)
    {
        if (!passed) throw new Exception(name);
    }

    static void Check()
    {
        var pixelFilm = new PixelFilmRuleset();
        Assert(pixelFilm.RulesetInfo.OnlineID == -1 && pixelFilm.ShortName != "mania", "Separate custom mode identity");
        foreach (int variant in pixelFilm.AllVariants) pixelFilm.GetDefaultKeyBindings(variant).ToArray();
        var criteria = new FilterCriteria { Ruleset = pixelFilm.RulesetInfo, AllowConvertedBeatmaps = true,
            RulesetCriteria = pixelFilm.CreateRulesetFilterCriteria() };
        var mania = new ManiaRuleset();
        for (int keys = 1; keys <= 18; keys++)
        {
            var beatmap = new Beatmap { BeatmapInfo = new BeatmapInfo { Ruleset = mania.RulesetInfo },
                Difficulty = new BeatmapDifficulty { CircleSize = keys } };
            beatmap.Metadata.Source = $"osu-paint-film-v1 3000 {keys} " + new string('a', 64);
            beatmap.HitObjects.Add(new Note { StartTime = 100000, Column = keys - 1 });
            Assert(!beatmap.BeatmapInfo.AllowGameplayWithRuleset(pixelFilm.RulesetInfo, true), "Original mania map needs a standard entry map");
            beatmap.BeatmapInfo.Ruleset = new osu.Game.Rulesets.RulesetInfo { OnlineID = 0, ShortName = "osu" };
            beatmap.Difficulty.CircleSize = 5;
            Assert(beatmap.BeatmapInfo.AllowGameplayWithRuleset(pixelFilm.RulesetInfo, true), "Generated map is visible at song select");
            Assert(BeatmapCarouselFilterMatching.CheckCriteriaMatch(beatmap.BeatmapInfo, criteria), "Entry passes the actual song select filter");
            Assert(pixelFilm.GetVariantForBeatmap(beatmap.BeatmapInfo) == keys, $"Exact {keys}K mode variant");
            var converter = pixelFilm.CreateBeatmapConverter(beatmap);
            Assert(converter.CanConvert(), "Generated map accepted");
            var working = new FixtureWorkingBeatmap(Array.Empty<byte>(), beatmap);
            var converted = (ManiaBeatmap)working.GetPlayableBeatmap(pixelFilm.RulesetInfo);
            Assert(converted.Stages.Count == 1 && converted.TotalColumns == keys, $"Full {keys}K single stage");
            Assert(converted.HitObjects.Count == 1 && converted.HitObjects[0].StartTime == 3000, "Completion uses film end, not frozen note time");
            using var drawable = pixelFilm.CreateDrawableRulesetWith(converted);
            Assert(!drawable.AllowGameplayOverlays, "Film hides gameplay HUD");
            beatmap.Metadata.Source = "ordinary beatmap";
            Assert(!pixelFilm.CreateBeatmapConverter(beatmap).CanConvert(), "Ordinary maps excluded");
            Assert(!BeatmapCarouselFilterMatching.CheckCriteriaMatch(beatmap.BeatmapInfo, criteria), "Unsupported maps hidden at song select");
        }
        const string json = "{\"format\":\"osu-paint-film-v1\",\"width\":2,\"height\":1,\"end_ms\":2200,\"frames\":[{\"start_ms\":2000,\"end_ms\":2100,\"rows\":[\"#.\"]},{\"start_ms\":2100,\"end_ms\":2200,\"rows\":[\".#\"]}]}";
        byte[] data = Encoding.UTF8.GetBytes(json);
        string source = "osu-paint-film-v1 2200 2 " + Convert.ToHexString(SHA256.HashData(data));
        var film = new FilmDocument(data, source);
        foreach (double hz in new[] { 60d, 120, 165 })
            for (int phase = 0; phase < 100; phase++)
                for (int tick = 0; tick < 40; tick++)
                {
                    double time = 1980 + (tick + phase / 100d) * 1000 / hz;
                    int index = film.FrameAt(time);
                    int expected = time < 2000 || time >= 2200 ? -1 : time < 2100 ? 0 : 1;
                    Assert(index == expected, "Whole-frame selection at arbitrary refresh phase");
                }
        Assert(film.FrameAt(2100) == 1 && film.FrameAt(2200) == -1 && film.FrameAt(2000) == 0, "Exact boundary and rewind");
        data[0] ^= 1;
        try { new FilmDocument(data, source); throw new Exception("Corrupted payload was accepted"); }
        catch (InvalidDataException) { }
        Console.WriteLine("PASS: target client loaded, 1-18K single stage, correct completion, 12000 refresh samples, payload binding, custom mode identity.");
    }
}
