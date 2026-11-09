using System.Net.Mime;
using System.Reflection;
using System.Text.RegularExpressions;
using Jellyfin.Plugin.HAnimeDownloader.Configuration;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.HAnimeDownloader.Api;

/// <summary>
/// Liefert das Client-Skript aus und leitet API-Aufrufe angemeldeter Jellyfin-Benutzer an das Backend weiter.
/// Das Backend ist damit nie direkt aus dem Browser erreichbar und braucht keine eigene Benutzerverwaltung.
/// </summary>
[ApiController]
[Route("HAnimeDownloader")]
public class DownloaderController : ControllerBase
{
    private static readonly Regex SafePath = new(@"^[A-Za-z0-9_\-./]{1,100}$", RegexOptions.Compiled);
    private static readonly HashSet<string> AllowedMethods = new(StringComparer.OrdinalIgnoreCase) { "GET", "POST", "DELETE" };

    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<DownloaderController> _logger;

    public DownloaderController(IHttpClientFactory httpClientFactory, ILogger<DownloaderController> logger)
    {
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    /// <summary>Client-Skript (wird in index.html eingebunden, muss ohne Anmeldung ladbar sein).</summary>
    [HttpGet("client.js")]
    [AllowAnonymous]
    public ActionResult GetClientScript()
    {
        var assembly = typeof(Plugin).Assembly;
        var stream = assembly.GetManifestResourceStream("Jellyfin.Plugin.HAnimeDownloader.Web.client.js");
        if (stream is null)
        {
            return NotFound();
        }

        Response.Headers.CacheControl = "no-cache";
        return File(stream, "application/javascript; charset=utf-8");
    }

    /// <summary>Authentifizierter Proxy zum Backend.</summary>
    [Route("api/{**path}")]
    [AcceptVerbs("GET", "POST", "DELETE")]
    [Authorize(Policy = "DefaultAuthorization")]
    public async Task<ActionResult> Proxy(string? path, CancellationToken cancellationToken)
    {
        var config = Plugin.Instance?.Configuration ?? new PluginConfiguration();
        if (string.IsNullOrWhiteSpace(config.BackendUrl) || string.IsNullOrWhiteSpace(config.ApiKey))
        {
            return Problem("Backend-URL oder API-Key sind in den Plugin-Einstellungen nicht gesetzt.", statusCode: 503);
        }

        path ??= string.Empty;
        if (!SafePath.IsMatch(path) || path.Contains("..", StringComparison.Ordinal) || !AllowedMethods.Contains(Request.Method))
        {
            return BadRequest();
        }

        var target = $"{config.BackendUrl.TrimEnd('/')}/api/{path}{Request.QueryString}";
        using var message = new HttpRequestMessage(new HttpMethod(Request.Method), target);
        message.Headers.Add("X-Api-Key", config.ApiKey);
        message.Headers.Add("X-Jellyfin-User", Uri.EscapeDataString(User.Identity?.Name ?? "unbekannt"));

        if (Request.Method is "POST" or "DELETE" && (Request.ContentLength ?? 0) > 0)
        {
            using var buffer = new MemoryStream();
            await Request.Body.CopyToAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (buffer.Length > 1_000_000)
            {
                return StatusCode(StatusCodes.Status413PayloadTooLarge);
            }

            var content = new ByteArrayContent(buffer.ToArray());
            content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(MediaTypeNames.Application.Json);
            message.Content = content;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(120);
            using var response = await client.SendAsync(message, cancellationToken).ConfigureAwait(false);
            var body = await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
            var contentType = response.Content.Headers.ContentType?.ToString() ?? MediaTypeNames.Application.Json;
            return new FileContentResult(body, contentType);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            _logger.LogWarning(ex, "H!Anime Downloader: Backend nicht erreichbar ({Target})", config.BackendUrl);
            return StatusCode(StatusCodes.Status502BadGateway, new { detail = "Backend nicht erreichbar. Bitte URL in den Plugin-Einstellungen pruefen." });
        }
    }
}
