namespace BegWork.Dashboard.Core.Refresh;

public interface IClock
{
    DateTimeOffset UtcNow { get; }
}

public interface IDelayProvider
{
    Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken);
}

public sealed class SystemClock : IClock
{
    public DateTimeOffset UtcNow => DateTimeOffset.UtcNow;

    public static readonly SystemClock Instance = new();
}

public sealed class TaskDelayProvider : IDelayProvider
{
    public Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken) =>
        Task.Delay(duration, cancellationToken);

    public static readonly TaskDelayProvider Instance = new();
}
