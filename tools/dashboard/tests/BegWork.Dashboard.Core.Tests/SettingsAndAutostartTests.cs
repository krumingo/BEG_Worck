using System.Text.Json;
using BegWork.Dashboard.Core.Config;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class SettingsAndAutostartTests
{
    private sealed class RecordingInstaller(bool installed) : IAutostartInstaller
    {
        public bool Installed { get; private set; } = installed;

        public int InstallCalls { get; private set; }

        public int RemoveCalls { get; private set; }

        public int QueryCalls { get; private set; }

        public bool IsInstalled()
        {
            QueryCalls++;
            return Installed;
        }

        public void Install()
        {
            InstallCalls++;
            Installed = true;
        }

        public void Remove()
        {
            RemoveCalls++;
            Installed = false;
        }
    }

    [Fact]
    public void AutostartIsOffInTheShippedDefaults()
    {
        Assert.False(DashboardSettings.Default.Autostart);
    }

    [Fact]
    public void AutostartIsOffWhenTheSettingsFileOmitsIt()
    {
        var settings = JsonSerializer.Deserialize<DashboardSettings>("""{"width":440}""");

        Assert.NotNull(settings);
        Assert.False(settings!.Autostart);
        Assert.Equal(440, settings.EffectiveWidth);
    }

    [Fact]
    public void RunningWithDefaultsNeverTouchesTheStartupFolder()
    {
        var installer = new RecordingInstaller(installed: false);

        var action = AutostartCoordinator.Apply(DashboardSettings.Default, installer);

        Assert.Equal(AutostartAction.NoAction, action);
        Assert.Equal(0, installer.InstallCalls);
        Assert.Equal(0, installer.RemoveCalls);
        Assert.False(installer.Installed);
    }

    [Fact]
    public void AutostartIsInstalledOnlyWhenTheUserTurnsItOn()
    {
        var installer = new RecordingInstaller(installed: false);

        var action = AutostartCoordinator.Apply(
            DashboardSettings.Default with { Autostart = true }, installer);

        Assert.Equal(AutostartAction.Install, action);
        Assert.Equal(1, installer.InstallCalls);
        Assert.True(installer.Installed);
    }

    [Fact]
    public void TurningAutostartOffRemovesAnExistingShortcut()
    {
        var installer = new RecordingInstaller(installed: true);

        var action = AutostartCoordinator.Apply(DashboardSettings.Default, installer);

        Assert.Equal(AutostartAction.Remove, action);
        Assert.Equal(1, installer.RemoveCalls);
        Assert.False(installer.Installed);
    }

    [Fact]
    public void ApplyingTheSameStateTwiceIsAnIdempotentNoOp()
    {
        var installer = new RecordingInstaller(installed: true);
        var settings = DashboardSettings.Default with { Autostart = true };

        Assert.Equal(AutostartAction.NoAction, AutostartCoordinator.Apply(settings, installer));
        Assert.Equal(AutostartAction.NoAction, AutostartCoordinator.Apply(settings, installer));
        Assert.Equal(0, installer.InstallCalls);
        Assert.Equal(0, installer.RemoveCalls);
    }

    [Theory]
    [InlineData(0, DashboardSettings.MinimumWidth)]
    [InlineData(300, DashboardSettings.MinimumWidth)]
    [InlineData(420, 420)]
    [InlineData(460, 460)]
    [InlineData(500, 500)]
    [InlineData(1200, DashboardSettings.MaximumWidth)]
    public void WidthIsClampedToTheApprovedRange(int configured, int expected)
    {
        Assert.Equal(expected, (DashboardSettings.Default with { Width = configured }).EffectiveWidth);
    }

    [Fact]
    public void TheDefaultWidthIsTheApprovedFourHundredAndSixty()
    {
        Assert.Equal(460, DashboardSettings.Default.EffectiveWidth);
        Assert.Equal(DashboardSettings.DefaultWidth, DashboardSettings.Default.EffectiveWidth);
    }

    [Theory]
    [InlineData(1, DashboardSettings.MinimumRefreshSeconds)]
    [InlineData(5, 5)]
    [InlineData(8, 8)]
    [InlineData(10, 10)]
    [InlineData(600, DashboardSettings.MaximumRefreshSeconds)]
    public void RefreshCadenceIsClampedToFiveToTenSeconds(int configured, int expected)
    {
        Assert.Equal(
            expected, (DashboardSettings.Default with { RefreshSeconds = configured }).EffectiveRefreshSeconds);
    }

    [Fact]
    public void StaleThresholdCannotUndercutTheCadence()
    {
        var settings = DashboardSettings.Default with { RefreshSeconds = 10, StaleAfterSeconds = 1 };

        Assert.Equal(20, settings.EffectiveStaleAfterSeconds);
    }

    [Fact]
    public void RepositoryIsSplitIntoOwnerAndName()
    {
        var settings = DashboardSettings.Default;

        Assert.Equal("krumingo", settings.Owner);
        Assert.Equal("BEG_Worck", settings.Name);
        Assert.Equal("codex/claude-queue", settings.Branch);
    }
}
