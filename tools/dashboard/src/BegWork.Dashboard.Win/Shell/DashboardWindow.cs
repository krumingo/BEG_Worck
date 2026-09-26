using System.Diagnostics;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;
using BegWork.Dashboard.Core.Rendering;
using BegWork.Dashboard.Win.Hosting;
using BegWork.Dashboard.Win.Interop;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace BegWork.Dashboard.Win.Shell;

/// <summary>
/// The docked panel itself: a frameless, topmost, non-activating strip hosting a
/// WebView2 that renders the projected read-model.
///
/// Focus is the constraint that shapes this class. The panel sits beside the
/// windows the operator is actually working in, and a refresh every few seconds
/// must never interrupt typing. So: it is shown without activation, every
/// reposition passes SWP_NOACTIVATE, and content updates are posted into the
/// existing document as web messages instead of renavigating it.
/// </summary>
internal sealed class DashboardWindow : Window
{
    private readonly DashboardSettings _settings;
    private readonly DashboardHost _host;
    private readonly IRedactingLog _log;
    private readonly WebView2 _view = new();

    private AppBarHost? _appBar;
    private HwndSource? _source;
    private bool _documentLoaded;
    private string? _pendingFragment;

    public DashboardWindow(DashboardSettings settings, DashboardHost host, IRedactingLog log)
    {
        _settings = settings;
        _host = host;
        _log = log;

        Title = "BEG_WORK control panel";
        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        Topmost = true;
        // Showing without activation is the first half of "never steal focus"; the
        // second half is SWP_NOACTIVATE on every later placement.
        ShowActivated = false;
        Background = new SolidColorBrush(Color.FromRgb(0x10, 0x13, 0x1A));
        Width = settings.EffectiveWidth;
        Height = 800;
        Content = _view;

        _host.FragmentReady += OnFragmentReady;
        Loaded += async (_, _) => await InitialiseWebViewAsync().ConfigureAwait(true);
        PreviewKeyDown += OnPreviewKeyDown;
    }

    /// <summary>
    /// The panel has no frame, no taskbar button and no Alt+Tab entry, so these are
    /// the only ways out of it. They act only while the user has deliberately
    /// clicked the panel, since an unfocused window receives no key input.
    /// Escape hides it; relaunching the executable brings it back through the
    /// single-instance signal. Ctrl+Shift+Q exits.
    /// </summary>
    private void OnPreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Hide();
            e.Handled = true;
            return;
        }

        if (e.Key == Key.Q
            && (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift))
               == (ModifierKeys.Control | ModifierKeys.Shift))
        {
            e.Handled = true;
            Close();
        }
    }

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);

        _source = (HwndSource)PresentationSource.FromVisual(this)!;
        _source.AddHook(WndProc);

        var hwnd = _source.Handle;

        // A tool window stays out of Alt+Tab and the taskbar, which is what an
        // always-present strip should do; it can still be clicked and scrolled.
        var exStyle = NativeMethods.GetWindowLong(hwnd, NativeMethods.GWL_EXSTYLE);
        NativeMethods.SetWindowLong(
            hwnd, NativeMethods.GWL_EXSTYLE, exStyle | NativeMethods.WS_EX_TOOLWINDOW);

        _appBar = new AppBarHost(hwnd, _log);

        if (_settings.ReserveDesktopSpace)
        {
            if (!_appBar.TryRegister() && _appBar.Notice is { } notice)
            {
                _host.AddShellNotice(notice);
            }
        }
        else
        {
            _host.AddShellNotice(
                "Desktop space reservation is disabled in settings; docking as a topmost overlay.");
        }

        ApplyPlacement();
    }

    private void ApplyPlacement()
    {
        if (_source is not { } source || _appBar is not { } appBar)
        {
            return;
        }

        var hwnd = source.Handle;
        var monitor = MonitorLayout.Select(_settings.MonitorIndex);
        var width = MonitorLayout.ToPhysicalWidth(hwnd, _settings.EffectiveWidth);

        var placed = appBar.Apply(monitor, width);
        _log.Information(
            $"placed panel at {placed.Left},{placed.Top} {placed.Width}x{placed.Height} "
            + $"({appBar.Mode}) on {monitor.Device}");
    }

    private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (_appBar is not { } appBar)
        {
            return IntPtr.Zero;
        }

        if (appBar.CallbackMessage != 0 && msg == (int)appBar.CallbackMessage)
        {
            if (appBar.HandleCallback(wParam))
            {
                ApplyPlacement();
            }
            handled = true;
            return IntPtr.Zero;
        }

        switch (msg)
        {
            // Monitor added/removed/resolution changed, DPI changed because the
            // panel moved to a different display, or the work area changed because
            // the taskbar moved or another AppBar appeared. All three mean the
            // dock rectangle is no longer right.
            case NativeMethods.WM_DISPLAYCHANGE:
            case NativeMethods.WM_DPICHANGED:
                ApplyPlacement();
                break;

            case NativeMethods.WM_SETTINGCHANGE when (int)wParam == NativeMethods.SPI_SETWORKAREA:
                ApplyPlacement();
                break;

            case NativeMethods.WM_WINDOWPOSCHANGED:
                appBar.NotifyWindowPosChanged();
                break;

            case NativeMethods.WM_ACTIVATE:
                appBar.NotifyActivated();
                break;
        }

        return IntPtr.Zero;
    }

    private async Task InitialiseWebViewAsync()
    {
        try
        {
            var userData = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "BEG_Work", "dashboard", "webview2");
            System.IO.Directory.CreateDirectory(userData);

            var environment = await CoreWebView2Environment
                .CreateAsync(browserExecutableFolder: null, userDataFolder: userData)
                .ConfigureAwait(true);
            await _view.EnsureCoreWebView2Async(environment).ConfigureAwait(true);
        }
        catch (WebView2RuntimeNotFoundException)
        {
            _log.Error("WebView2 Runtime is not installed; the panel cannot render.");
            MessageBox.Show(
                "The Microsoft Edge WebView2 Runtime is required and was not found.\n\n"
                + "Install the Evergreen WebView2 Runtime and start the panel again.",
                "BEG_WORK control panel",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Application.Current.Shutdown(2);
            return;
        }
        catch (Exception exception)
        {
            _log.Error($"WebView2 initialisation failed: {exception.Message}");
            return;
        }

        var core = _view.CoreWebView2;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreHostObjectsAllowed = false;
        core.Settings.IsZoomControlEnabled = false;
        core.Settings.IsWebMessageEnabled = true;

        // Evidence links belong in the operator's browser, not in a 460 px strip.
        core.NewWindowRequested += (_, args) =>
        {
            args.Handled = true;
            OpenExternally(args.Uri);
        };
        core.NavigationStarting += (_, args) =>
        {
            if (!_documentLoaded)
            {
                return;
            }
            args.Cancel = true;
            OpenExternally(args.Uri);
        };
        core.NavigationCompleted += (_, _) =>
        {
            _documentLoaded = true;
            if (_pendingFragment is { } pending)
            {
                _pendingFragment = null;
                Push(pending);
            }
        };

        core.NavigateToString(DashboardHtmlRenderer.RenderDocument(_settings.EffectiveWidth));
    }

    private void OnFragmentReady(string fragment)
    {
        if (!Dispatcher.CheckAccess())
        {
            _ = Dispatcher.InvokeAsync(() => OnFragmentReady(fragment));
            return;
        }

        if (!_documentLoaded || _view.CoreWebView2 is null)
        {
            _pendingFragment = fragment;
            return;
        }

        Push(fragment);
    }

    /// <summary>
    /// Updates the page by message rather than navigation: navigation would reset
    /// scroll position every few seconds and can move focus into the WebView.
    /// </summary>
    private void Push(string fragment)
    {
        try
        {
            _view.CoreWebView2?.PostWebMessageAsJson(
                JsonSerializer.Serialize(new { html = fragment }));
        }
        catch (Exception exception)
        {
            _log.Error($"pushing content to the WebView failed: {exception.Message}");
        }
    }

    private void OpenExternally(string uri)
    {
        if (!Uri.TryCreate(uri, UriKind.Absolute, out var parsed)
            || (parsed.Scheme != Uri.UriSchemeHttps && parsed.Scheme != Uri.UriSchemeHttp))
        {
            return;
        }

        try
        {
            Process.Start(new ProcessStartInfo(parsed.AbsoluteUri) { UseShellExecute = true });
        }
        catch (Exception exception)
        {
            _log.Warning($"could not open {parsed.Host} in the default browser: {exception.GetType().Name}");
        }
    }

    /// <summary>Brings the panel forward when a second launch signals this instance.</summary>
    public void RevealWithoutStealingFocus()
    {
        if (!Dispatcher.CheckAccess())
        {
            _ = Dispatcher.InvokeAsync(RevealWithoutStealingFocus);
            return;
        }

        if (!IsVisible)
        {
            Show();
        }
        ApplyPlacement();
    }

    protected override void OnClosed(EventArgs e)
    {
        _host.FragmentReady -= OnFragmentReady;
        _source?.RemoveHook(WndProc);
        // Removing the AppBar gives the user their desktop space back.
        _appBar?.Dispose();
        _view.Dispose();
        base.OnClosed(e);
    }
}
