using Jellyfin.Plugin.HAnimeDownloader.Configuration;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;

namespace Jellyfin.Plugin.HAnimeDownloader;

/// <summary>H!Anime Downloader – bindet die Download-Oberflaeche per FileTransformation in Jellyfin ein.</summary>
public class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
{
    public Plugin(IApplicationPaths applicationPaths, IXmlSerializer xmlSerializer)
        : base(applicationPaths, xmlSerializer)
    {
        Instance = this;
    }

    public static Plugin? Instance { get; private set; }

    public override Guid Id => Guid.Parse("e286ec7b-b08d-40dc-ac58-3788907d65f7");

    public override string Name => "H!Anime Downloader";

    public override string Description => "Web-Oberflaeche zum Herunterladen von Serien direkt in die Jellyfin-Bibliothek.";

    public IEnumerable<PluginPageInfo> GetPages()
    {
        yield return new PluginPageInfo
        {
            Name = "HAnimeDownloader",
            EmbeddedResourcePath = $"{GetType().Namespace}.Configuration.configPage.html"
        };
    }
}
