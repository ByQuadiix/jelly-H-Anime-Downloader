using System.Reflection;
using System.Runtime.Loader;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json.Linq;

namespace Jellyfin.Plugin.HAnimeDownloader.Web;

/// <summary>Registriert beim Serverstart die index.html-Transformation im FileTransformation-Plugin.</summary>
public sealed class FileTransformationRegistrar : IHostedService
{
    private static readonly Guid TransformationId = Guid.Parse("c4a1e0f2-7b1d-4e3a-9a52-3f6d1c8b7e41");

    private readonly ILogger<FileTransformationRegistrar> _logger;
    private CancellationTokenSource? _cts;

    public FileTransformationRegistrar(ILogger<FileTransformationRegistrar> logger)
    {
        _logger = logger;
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        // Im Hintergrund mit Wiederholungen, damit der Serverstart nie blockiert und die Ladereihenfolge egal ist.
        _ = Task.Run(() => RegisterWithRetryAsync(_cts.Token), CancellationToken.None);
        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken)
    {
        _cts?.Cancel();
        return Task.CompletedTask;
    }

    private async Task RegisterWithRetryAsync(CancellationToken token)
    {
        const int attempts = 12;
        for (var attempt = 1; attempt <= attempts && !token.IsCancellationRequested; attempt++)
        {
            try
            {
                if (TryRegister())
                {
                    _logger.LogInformation("H!Anime Downloader: index.html-Transformation registriert.");
                    return;
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "H!Anime Downloader: Registrierung bei FileTransformation fehlgeschlagen (Versuch {Attempt}/{Max}).", attempt, attempts);
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(5), token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }

        _logger.LogError("H!Anime Downloader: Das FileTransformation-Plugin wurde nicht gefunden. Bitte installieren und Jellyfin neu starten – sonst erscheint die Oberflaeche nicht.");
    }

    private bool TryRegister()
    {
        var assembly = AssemblyLoadContext.All
            .SelectMany(context => context.Assemblies)
            .FirstOrDefault(a => a.FullName?.Contains(".FileTransformation", StringComparison.Ordinal) ?? false);

        var interfaceType = assembly?.GetType("Jellyfin.Plugin.FileTransformation.PluginInterface");
        var method = interfaceType?.GetMethod("RegisterTransformation");
        if (method is null)
        {
            return false;
        }

        var callbackType = typeof(IndexHtmlTransform);
        var payload = new JObject
        {
            ["id"] = TransformationId.ToString(),
            ["fileNamePattern"] = "index.html",
            ["callbackAssembly"] = callbackType.Assembly.FullName,
            ["callbackClass"] = callbackType.FullName,
            ["callbackMethod"] = nameof(IndexHtmlTransform.Transform)
        };

        method.Invoke(null, new object?[] { payload });
        return true;
    }
}
