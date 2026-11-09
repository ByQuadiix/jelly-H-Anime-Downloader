using MediaBrowser.Model.Plugins;

namespace Jellyfin.Plugin.HAnimeDownloader.Configuration;

public class PluginConfiguration : BasePluginConfiguration
{
    /// <summary>Basis-URL des Downloader-Backends, vom Jellyfin-Server aus erreichbar.</summary>
    public string BackendUrl { get; set; } = "http://hanime-downloader:8080";

    /// <summary>Gemeinsamer Schluessel (muss dem API_KEY des Backends entsprechen).</summary>
    public string ApiKey { get; set; } = string.Empty;
}
