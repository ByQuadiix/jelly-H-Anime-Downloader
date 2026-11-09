namespace Jellyfin.Plugin.HAnimeDownloader.Web;

/// <summary>Payload, das das FileTransformation-Plugin an den Callback uebergibt ({ "contents": "..." }).</summary>
public class PatchRequestPayload
{
    public string? Contents { get; set; }
}

/// <summary>Callback fuer FileTransformation: haengt das Client-Skript an die index.html an.</summary>
public static class IndexHtmlTransform
{
    private const string Marker = "data-hanime-downloader";

    // Relativer Pfad: funktioniert auch mit Jellyfin-BaseUrl (z. B. /jellyfin/web/ -> /jellyfin/HAnimeDownloader/...).
    private const string ScriptTag =
        "<script defer " + Marker + " src=\"../HAnimeDownloader/client.js\"></script>";

    public static string Transform(PatchRequestPayload payload)
    {
        var html = payload?.Contents ?? string.Empty;
        if (html.Length == 0 || html.Contains(Marker, StringComparison.Ordinal))
        {
            return html;
        }

        var index = html.LastIndexOf("</body>", StringComparison.OrdinalIgnoreCase);
        return index >= 0 ? html.Insert(index, ScriptTag) : html + ScriptTag;
    }
}
