using System.Collections.Generic;

namespace BegWork.Dashboard.Win.Interop;

/// <summary>A monitor's physical work area (the desktop minus the taskbar and any AppBars).</summary>
internal sealed record MonitorArea(IntPtr Handle, RECT Monitor, RECT Work, bool IsPrimary, string Device);

/// <summary>
/// Enumerates monitors in physical pixels.
///
/// Positioning is done in physical coordinates rather than WPF device-independent
/// units on purpose: the panel is placed by <c>SetWindowPos</c> against a work area
/// the shell reports in physical pixels, and round-tripping that through per-monitor
/// DPI scaling is where off-by-a-few-pixels docking bugs come from.
/// </summary>
internal static class MonitorLayout
{
    private const uint MONITORINFOF_PRIMARY = 0x00000001;

    public static IReadOnlyList<MonitorArea> All()
    {
        var monitors = new List<MonitorArea>();

        NativeMethods.EnumDisplayMonitors(
            IntPtr.Zero,
            IntPtr.Zero,
            (IntPtr handle, IntPtr _, ref RECT _, IntPtr _) =>
            {
                if (TryDescribe(handle) is { } area)
                {
                    monitors.Add(area);
                }
                return true;
            },
            IntPtr.Zero);

        // Left-to-right so a configured index means something stable to the user.
        monitors.Sort((left, right) => left.Monitor.Left.CompareTo(right.Monitor.Left));
        return monitors;
    }

    /// <summary>
    /// The monitor at <paramref name="index"/>, or the primary one when the index is
    /// out of range — which happens routinely when a display is unplugged.
    /// </summary>
    public static MonitorArea Select(int index)
    {
        var monitors = All();
        if (monitors.Count == 0)
        {
            return Fallback();
        }

        if (index >= 0 && index < monitors.Count)
        {
            return monitors[index];
        }

        return monitors.FirstOrDefault(monitor => monitor.IsPrimary) ?? monitors[0];
    }

    public static MonitorArea ForWindow(IntPtr hwnd)
    {
        var handle = NativeMethods.MonitorFromWindow(hwnd, NativeMethods.MONITOR_DEFAULTTONEAREST);
        return TryDescribe(handle) ?? Fallback();
    }

    private static MonitorArea? TryDescribe(IntPtr handle)
    {
        var info = new MONITORINFOEX { cbSize = System.Runtime.InteropServices.Marshal.SizeOf<MONITORINFOEX>() };
        if (!NativeMethods.GetMonitorInfo(handle, ref info))
        {
            return null;
        }

        return new MonitorArea(
            handle,
            info.rcMonitor,
            info.rcWork,
            (info.dwFlags & MONITORINFOF_PRIMARY) != 0,
            info.szDevice);
    }

    private static MonitorArea Fallback()
    {
        var primary = NativeMethods.MonitorFromPoint(
            new NativeMethods.POINT { X = 0, Y = 0 }, NativeMethods.MONITOR_DEFAULTTOPRIMARY);
        return TryDescribe(primary)
               ?? new MonitorArea(
                   IntPtr.Zero,
                   new RECT { Left = 0, Top = 0, Right = 1920, Bottom = 1080 },
                   new RECT { Left = 0, Top = 0, Right = 1920, Bottom = 1040 },
                   true,
                   "\\\\.\\DISPLAY1");
    }

    /// <summary>Converts a logical (96-dpi) width to physical pixels for one window.</summary>
    public static int ToPhysicalWidth(IntPtr hwnd, int logicalWidth)
    {
        var dpi = hwnd == IntPtr.Zero ? 96u : NativeMethods.GetDpiForWindow(hwnd);
        if (dpi == 0)
        {
            dpi = 96;
        }
        return (int)Math.Round(logicalWidth * dpi / 96.0);
    }
}
