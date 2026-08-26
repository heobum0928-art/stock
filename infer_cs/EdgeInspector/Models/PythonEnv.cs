using System.Diagnostics;
using System.IO;

namespace EdgeInspector.Models;

// 파이썬 서브프로세스를 venv(train/.venv)로 확실히 실행하기 위한 환경 구성.
// 시스템/사용자 환경에 PYTHONHOME·PYTHONPATH(예: Matrox MIL Scripting)가 걸려 있으면
// venv의 site-packages 탐색을 방해해 "설치된 라이브러리를 못 찾는" 현상이 날 수 있다.
// GUI 앱은 이런 환경을 그대로 상속하므로, venv 실행 전에 명시적으로 정리한다.
public static class PythonEnv
{
    // psi.FileName은 venv의 python.exe(절대경로)여야 한다. venvDir = train/.venv.
    public static void ConfigureVenv(ProcessStartInfo psi, string venvDir)
    {
        // venv 파이썬이 자기 site-packages를 쓰도록 방해 변수를 제거한다.
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables.Remove("PYTHONSTARTUP");

        // 한글 로그/경로가 깨지지 않게 UTF-8 강제.
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        // venv 활성화와 동등한 효과: VIRTUAL_ENV 설정 + PATH 앞에 Scripts 추가.
        psi.EnvironmentVariables["VIRTUAL_ENV"] = venvDir;
        var scripts = Path.Combine(venvDir, "Scripts");
        var oldPath = psi.EnvironmentVariables.ContainsKey("PATH") ? psi.EnvironmentVariables["PATH"] : "";
        psi.EnvironmentVariables["PATH"] = scripts + Path.PathSeparator + oldPath;
    }
}
