using System.Runtime.InteropServices;
using BegWork.Dashboard.Core.Logging;

namespace BegWork.Dashboard.Win.Interop;

internal enum DockMode
{
    /// <summary>Registered AppBar: the shell reserves the strip, so maximised windows stop short of it.</summary>
    ReservedAppBar,

    /// <summary>Fallback: a topmost strip that overlaps whatever is behind it.</summary>
    TopmostOverlay,
}

/// <summary>
/// Docks the panel to the right edge of one monitor.
///
/// Preferred mode registers a Windows AppBar so the desktop work area shrinks and
/// the panel never covers the Codex or Claude windows. Registration can fail — the
/// shell refuses a second AppBar on an edge it has already granted, and it can be
/// denied outright in some session states — so failure is expected, handled, and
/// reported to the UI rather than being treated as fatal: a visible overlay is far
/// more useful than no panel.
/// </summary>
internal sealed class AppBarHost(IntPtr hwnd, IRedactingLog log) : IDisposable
{
    private readonly uint _callbackMessage =
        NativeMethods.RegisterWindowMessage("BegWorkDashboardAppBarMessage");

    private bool _registered;
    private bool _suspendedForFullscreen;

    public DockMode Mode { get; private set; } = DockMode.TopmostOverlay;

    public uint CallbackMessage => _callbackMessage;

    /// <summary>Human-readable note for the status banner when the preferred mode was not available.</summary>
    public string? Notice { get; private set; }

    public bool TryRegister()
    {
        if (_registered)
        {
            return true;
        }

        var data = new APPBARDATA
        {
            cbSize = Marshal.SizeOf<APPBARDATA>(),
            hWnd = hwnd,
            uCallbackMessage = _callbackMessage,
        };

        if (NativeMethods.SHAppBarMessage(NativeMethods.ABM_NEW, ref data) == UIntPtr.Zero)
        {
            Mode = DockMode.TopmostOverlay;
            Notice = "AppBar registration was refused; docking as a topmost overlay, "
                     + "so maximised windows may run underneath the panel.";
            log.Warning("SHAppBarMessage(ABM_NEW) failed; falling back to topmost overlay.");
            return false;
        }

        _registered = true;
        Mode = DockMode.ReservedAppBar;
        Notice = null;
        log.Information("AppBar registered on the right edge.");
        return true;
    }

    /// <summary>
    /// Places the panel, asking the shell to reserve the strip when registered.
    /// Returns the rectangle actually used, in physical pixels.
    /// </summary>
    public RECT Apply(MonitorArea monitor, int physicalWidth)
    {
        var desired = new RECT
        {
            Left = monitor.Monitor.Right - physicalWidth,
            Top = monitor.Work.Top,
            Right = monitor.Monitor.Right,
            Bottom = monitor.Work.Bottom,
        };

        if (_registered && !_suspendedForFullscreen)
        {
            var data = new APPBARDATA
            {
                cbSize = Marshal.SizeOf<APPBARDATA>(),
                hWnd = hwnd,
                uEdge = NativeMethods.ABE_RIGHT,
                rc = desired,
            };

            // QUERYPOS lets the shell move the proposed rectangle clear of the
            // taskbar and any other AppBar; the width is then re-imposed against
            // whatever right edge came back.
            NativeMethods.SHAppBarMessage(NativeMethods.ABM_QUERYPOS, ref data);
            data.rc.Left = data.rc.Right - physicalWidth;
            NativeMethods.SHAppBarMessage(NativeMethods.ABM_SETPOS, ref data);
            desired = data.rc;
        }
        else
        {
            // Overlay mode respects the work area so the panel does not sit on top
            // of the taskbar.
            desired.Left = monitor.Work.Right - physicalWidth;
            desired.Right = monitor.Work.Right;
        }

        NativeMethods.SetWindowPos(
            hwnd,
            _suspendedForFullscreen ? NativeMethods.HWND_NOTOPMOST : NativeMethods.HWND_TOPMOST,
            desired.Left,
            desired.Top,
            desired.Width,
            desired.Height,
            // Never SWP_SHOWWINDOW without NOACTIVATE: repositioning must not pull
            // focus away from the window the operator is typing in.
            NativeMethods.SWP_NOACTIVATE);

        return desired;
    }

    /// <summary>
    /// Handles the shell's AppBar notifications. Returns true when the caller should
    /// re-apply the position.
    /// </summary>
    public bool HandleCallback(IntPtr wParam)
    {
        switch ((int)wParam)
        {
            case NativeMethods.ABN_POSCHANGED:
            case NativeMethods.ABN_WINDOWARRANGE:
                return true;

            case NativeMethods.ABN_FULLSCREENAPP:
                // A fullscreen app took the monitor. Windows does not let a topmost
                // strip sit reliably over exclusive fullscreen, so the panel yields
                // instead of fighting for z-order, and comes back afterwards.
                _suspendedForFullscreen = !_suspendedForFullscreen;
                log.Information(
                    _suspendedForFullscreen
                        ? "Fullscreen application detected; yielding topmost."
                        : "Fullscreen application gone; restoring topmost.");
                return true;

            default:
                return false;
        }
    }

    public void NotifyWindowPosChanged()
    {
        if (!_registered)
        {
            return;
        }

        var data = new APPBARDATA { cbSize = Marshal.SizeOf<APPBARDATA>(), hWnd = hwnd };
        NativeMethods.SHAppBarMessage(NativeMethods.ABM_WINDOWPOSCHANGED, ref data);
    }

    public void NotifyActivated()
    {
        if (!_registered)
        {
            return;
        }

        var data = new APPBARDATA { cbSize = Marshal.SizeOf<APPBARDATA>(), hWnd = hwnd };
        NativeMethods.SHAppBarMessage(NativeMethods.ABM_ACTIVATE, ref data);
    }

    public void Dispose()
    {
        if (!_registered)
        {
            return;
        }

        // Leaving an AppBar registered after exit permanently shrinks the user's
        // desktop until they log out, so removal is not optional.
        var data = new APPBARDATA { cbSize = Marshal.SizeOf<APPBARDATA>(), hWnd = hwnd };
        NativeMethods.SHAppBarMessage(NativeMethods.ABM_REMOVE, ref data);
        _registered = false;
    }
}
