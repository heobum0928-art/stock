using System.Runtime.InteropServices;
using System.Windows;
using EdgeInspector.Examples;

namespace EdgeInspector;

public partial class App : Application
{
    private const int ATTACH_PARENT_PROCESS = -1;

    [DllImport("kernel32.dll")]
    private static extern bool AttachConsole(int dwProcessId);

    [DllImport("kernel32.dll")]
    private static extern bool FreeConsole();

    // "dotnet run --project infer_cs/EdgeInspector -- --examples"로 실행하면
    // 창을 띄우는 대신 train/data/images 전체에 대해 일괄 추론 후 종료한다.
    protected override void OnStartup(StartupEventArgs e)
    {
        // 시작 마커 — 어느 빌드가 실행 중인지 + logs 쓰기 가능 여부를 즉시 확인(진단용).
        try
        {
            System.IO.Directory.CreateDirectory(@"C:\EdgeAI\logs");
            var buildTime = System.IO.File.GetLastWriteTime(
                System.Reflection.Assembly.GetExecutingAssembly().Location);
            System.IO.File.AppendAllText(@"C:\EdgeAI\logs\app_start.txt",
                $"{DateTime.Now:HH:mm:ss} 앱 시작 · 빌드시각 {buildTime:MM-dd HH:mm:ss} · args=[{string.Join(" ", e.Args)}]\n");
        }
        catch { }

        if (e.Args.Contains("--selftest"))
        {
            // WinExe 서브시스템이라 콘솔 부착이 환경에 따라 신뢰할 수 없어(Git Bash 등)
            // 결과를 임시 로그 파일로도 남긴다(EDGEINSPECTOR_SHOT 하네스와 같은 패턴).
            AttachConsole(ATTACH_PARENT_PROCESS);
            int rc = 0;
            var logPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "edgeinspector_selftest.log");
            try
            {
                var sw = new System.IO.StringWriter();
                var old = Console.Out;
                Console.SetOut(sw);
                rc = Models.LabelingEngineSelfTest.Run();
                Console.SetOut(old);
                System.IO.File.WriteAllText(logPath, sw.ToString());
                Console.Write(sw.ToString());
            }
            finally { FreeConsole(); Shutdown(rc); }
            return;
        }
        if (e.Args.Contains("--examples"))
        {
            AttachConsole(ATTACH_PARENT_PROCESS);
            try
            {
                ExampleRunner.RunBatch();
            }
            finally
            {
                FreeConsole();
                Shutdown();
            }
            return;
        }

        base.OnStartup(e);

        // 처리되지 않은 예외(바인딩 오류, NullReferenceException 등)가 WPF 기본 크래시 창으로
        // 직행하지 않도록 전역 핸들러를 건다 — 로그 남기고 안내 후 안전 종료.
        DispatcherUnhandledException += App_DispatcherUnhandledException;

        // "--domain <표시이름>"이 있으면 뷰어를 그 도메인이 선택된 YOLO 탭으로 연다(스튜디오 연동).
        string? initialDomain = null;
        var di = Array.IndexOf(e.Args, "--domain");
        if (di >= 0 && di + 1 < e.Args.Length)
            initialDomain = e.Args[di + 1];
        new MainWindow(initialDomain).Show();
    }

    private void App_DispatcherUnhandledException(object sender,
        System.Windows.Threading.DispatcherUnhandledExceptionEventArgs e)
    {
        string logPath = "(로그 저장 실패)";
        try
        {
            var logDir = @"C:\EdgeAI\logs";
            System.IO.Directory.CreateDirectory(logDir);
            logPath = System.IO.Path.Combine(logDir, $"crash_{DateTime.Now:yyyyMMdd_HHmmss}.log");
            System.IO.File.WriteAllText(logPath, e.Exception.ToString());
        }
        catch { /* 로그 저장 자체가 실패해도 안내는 계속 진행 */ }

        try
        {
            MessageBox.Show(
                $"예상치 못한 문제가 발생했습니다. 프로그램을 안전하게 종료합니다.\n\n로그: {logPath}\n지원 요청 시 이 파일을 보내주세요.",
                "EdgeAI Vision Studio - 오류",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        catch { /* MessageBox조차 실패하면 그냥 종료 진행 */ }

        // 이미 상태가 꼬였을 수 있으므로 계속 실행을 시도하지 않고 안전하게 종료한다.
        e.Handled = true;
        Shutdown();
    }
}
