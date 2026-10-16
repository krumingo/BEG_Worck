using System.Threading;

namespace BegWork.Dashboard.Win.Hosting;

/// <summary>
/// Keeps one panel per user session.
///
/// Two copies would mean two AppBar registrations fighting over the same edge and
/// twice the polling. A second launch signals the first to show itself and exits,
/// which is what a user double-clicking the shortcut again actually wants.
/// </summary>
internal sealed class SingleInstance : IDisposable
{
    // Local\ rather than Global\: the scope is the interactive session, and a
    // Global name would need privileges the panel deliberately does not request.
    private const string MutexName = @"Local\BEG_Work.Dashboard.SingleInstance";
    private const string SignalName = @"Local\BEG_Work.Dashboard.Show";

    private readonly Mutex _mutex;
    private readonly EventWaitHandle _signal;
    private RegisteredWaitHandle? _registration;

    private SingleInstance(Mutex mutex, EventWaitHandle signal, bool isFirst)
    {
        _mutex = mutex;
        _signal = signal;
        IsFirstInstance = isFirst;
    }

    public bool IsFirstInstance { get; }

    public static SingleInstance Acquire()
    {
        var mutex = new Mutex(initiallyOwned: true, MutexName, out var created);
        var signal = new EventWaitHandle(false, EventResetMode.AutoReset, SignalName);
        return new SingleInstance(mutex, signal, created);
    }

    /// <summary>Asks an already-running instance to bring itself to the front.</summary>
    public void SignalExistingInstance() => _signal.Set();

    public void OnShowRequested(Action callback)
    {
        _registration = ThreadPool.RegisterWaitForSingleObject(
            _signal, (_, _) => callback(), null, Timeout.Infinite, executeOnlyOnce: false);
    }

    public void Dispose()
    {
        _registration?.Unregister(null);
        if (IsFirstInstance)
        {
            try
            {
                _mutex.ReleaseMutex();
            }
            catch (ApplicationException)
            {
                // Not held on this thread during shutdown; nothing to release.
            }
        }
        _signal.Dispose();
        _mutex.Dispose();
    }
}
